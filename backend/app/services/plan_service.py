"""plans 业务编排：计划详情 / 进度 / 任务状态更新（/ + v1.2 反馈闭环回显）。"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ErrorCode
from app.models import User
from app.repositories.feedback_repository import AchievementRepository
from app.repositories.plan_repository import PlanRepository
from app.schemas.plans import (
    PlanDetailOut,
    PlanProgressOut,
    PlanTaskOut,
    PlanTaskUpdateOut,
    PlanTaskUpdateRequest,
)
from app.services.error_codes import PlanErrorCode

STAGE_LABELS = {
    "short": "短期（1 个月内）",
    "mid": "中期（1-3 个月）",
    "long": "长期（3 个月以上）",
}
VALID_TASK_STATUS = {"todo", "doing", "done"}


class PlanService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.plan_repo = PlanRepository(session)

    async def get_plan(self, user: User, plan_id: uuid.UUID) -> PlanDetailOut:
        plan = await self.plan_repo.get_owned(plan_id, user.id)
        if plan is None:
            raise ApiError(PlanErrorCode.PLAN_NOT_FOUND, "成长计划不存在", 404)
        tasks = await self.plan_repo.get_tasks(plan_id)
        target_job = await self.plan_repo.get_gap_target_job(plan.gap_analysis_id)
        # v1.1：阶段级能力化字段来自 growth_plans.stages（AI 落库）；
        # 任务级 acceptance_criteria 来自报告 result.plan.tasks（plan_tasks 无该列，存量缺省）。
        stage_meta = plan.stages if isinstance(plan.stages, dict) else {}
        ai_acceptance = await self._report_task_acceptance(plan.report_id)
        # v1.2：反馈闭环回显（achievements/eligible/latest_reassess/completion_check）
        from app.services.feedback_service import FeedbackService

        echo = await FeedbackService(self.session).build_plan_echo(user, plan)
        # v1.3：覆盖关系由 achievements[].task_id 实时推导，不修改 task.status
        covered_ids = _covered_task_ids(echo["achievements"])
        progress, *_ = _count_progress(tasks, covered_ids)
        return PlanDetailOut(
            id=plan.id,
            report_id=plan.report_id,
            gap_analysis_id=plan.gap_analysis_id,
            target_job=target_job,
            stages=_stage_summary(tasks, stage_meta, echo["completion_checks"]),
            progress=progress,
            tasks=[
                PlanTaskOut(
                    id=t.id,
                    name=t.name,
                    resource=t.resource,
                    duration=t.duration,
                    stage=t.stage,
                    status=t.status,
                    sort_order=t.sort_order,
                    acceptance_criteria=ai_acceptance.get(t.name),
                    covered_by_achievement=str(t.id) in covered_ids,
                )
                for t in tasks
            ],
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            achievements=echo["achievements"],
            reassess_eligible=echo["reassess_eligible"],
            reassess_eligible_reason=echo["reassess_eligible_reason"],
            latest_reassess=echo["latest_reassess"],
        )

    async def _report_task_acceptance(self, report_id: uuid.UUID) -> dict:
        """报告 result.plan.tasks 的 {任务名: acceptance_criteria}（存量/缺省 → 空 dict）。"""
        from app.models import CareerReport

        report = await self.session.get(CareerReport, report_id)
        if report is None or not (report.result or {}):
            return {}
        plan_ai = (report.result or {}).get("plan") or {}
        out: dict = {}
        for t in plan_ai.get("tasks") or []:
            if isinstance(t, dict) and t.get("name"):
                out[str(t["name"])] = t.get("acceptance_criteria")
        return out

    async def get_progress(self, user: User, plan_id: uuid.UUID) -> PlanProgressOut:
        plan = await self.plan_repo.get_owned(plan_id, user.id)
        if plan is None:
            raise ApiError(PlanErrorCode.PLAN_NOT_FOUND, "成长计划不存在", 404)
        tasks = await self.plan_repo.get_tasks(plan_id)
        achievements = await AchievementRepository(self.session).list_by_plan(plan_id)
        covered_ids = _covered_task_ids(achievements)
        progress, done, covered, effective_done = _count_progress(tasks, covered_ids)
        return PlanProgressOut(
            plan_id=plan.id,
            progress=progress,
            total_tasks=len(tasks),
            done_tasks=done,
            covered_tasks=covered,
            effective_done_tasks=effective_done,
            stages=_stage_progress(tasks, covered_ids),
        )

    async def update_task(
        self, user: User, plan_id: uuid.UUID, task_id: uuid.UUID, req: PlanTaskUpdateRequest
    ) -> PlanTaskUpdateOut:
        """/（分层双源语义）：任务状态 PATCH 是「运行时状态」写方——只写
        plan_tasks.status（+ growth_plans.progress 重算），**不回写 career_reports.result
        JSONB 生成快照**（报告=生成时快照 C-005 不可变，勾选状态由 GET /plans/{id} 从表读取）。"""
        status = req.status
        if status not in VALID_TASK_STATUS:
            raise ApiError(PlanErrorCode.PLAN_TASK_STATUS_INVALID, "任务状态只能是 todo/doing/done", 400)
        plan = await self.plan_repo.get_owned(plan_id, user.id)
        if plan is None:
            raise ApiError(PlanErrorCode.PLAN_NOT_FOUND, "成长计划不存在", 404)
        task = await self.plan_repo.get_task(plan_id, task_id)
        if task is None:
            raise ApiError(PlanErrorCode.PLAN_TASK_NOT_FOUND, "任务不存在或不属于该计划", 404)
        await self.plan_repo.update_task_status(task, status) # 幂等：重复设置相同状态直接返回成功
        # v1.3：进度口径 = |done ∪ covered|；recalc_progress 仍按 done 回写，
        # 随后用覆盖口径覆盖列值，保证 growth_plans.progress 与 API 返回一致（无成果时两者等价）。
        tasks = await self.plan_repo.get_tasks(plan_id)
        achievements = await AchievementRepository(self.session).list_by_plan(plan_id)
        progress, *_ = _count_progress(tasks, _covered_task_ids(achievements))
        await self.plan_repo.recalc_progress(plan_id)
        plan.progress = progress
        await self.session.commit()
        return PlanTaskUpdateOut(plan_id=plan.id, task_id=task.id, task_status=task.status, progress=progress)


def _covered_task_ids(achievements) -> set[str]:
    """从成果列表推导被覆盖任务 id 集合（task_id 单值；一个任务可被多个成果引用但只计一次）。"""
    return {
        str(a.task_id)
        for a in achievements
        if getattr(a, "task_id", None) is not None
    }


def _count_progress(tasks: list, covered_ids: set[str] | None = None) -> tuple[int, int, int, int]:
    """v1.3 进度口径：progress = round(100 × |done ∪ covered| / total_tasks)。

    返回 (progress, done, covered, effective_done)：done 仅 status=done；covered 为被成果覆盖
    任务数（含已 done）；effective_done 为去重后的有效完成数（每任务最多计一次）。
    """
    covered_ids = covered_ids or set()
    done = sum(1 for t in tasks if t.status == "done")
    covered = sum(1 for t in tasks if str(t.id) in covered_ids)
    effective_done = sum(1 for t in tasks if t.status == "done" or str(t.id) in covered_ids)
    total = len(tasks)
    return (round(effective_done / total * 100) if total > 0 else 0), done, covered, effective_done


def _stage_summary(tasks: list, stage_meta: dict | None = None, completion_checks: dict | None = None) -> dict:
    """阶段汇总：label/tasks_count 以实际任务为准；能力化字段（goal/why/verify/
    resume_value/stage_completion）来自 AI 落库 stages（v1.1，存量缺省 None，前端优雅降级）；
    completion_check（v1.2）取最近一次成功重评的 stage_checks，无成功重评 = unchecked。
    """
    stage_meta = stage_meta or {}
    completion_checks = completion_checks or {}
    summary: dict = {}
    for key, label in STAGE_LABELS.items():
        count = sum(1 for t in tasks if t.stage == key)
        meta = stage_meta.get(key) or {}
        summary[key] = {
            "label": label,
            "tasks_count": count,
            "goal": meta.get("goal"),
            "why": meta.get("why"),
            "verify": meta.get("verify"),
            "resume_value": meta.get("resume_value"),
            "stage_completion": meta.get("stage_completion"),
            "completion_check": completion_checks.get(key, "unchecked"),
        }
    return summary


def _stage_progress(tasks: list, covered_ids: set[str] | None = None) -> dict:
    """分阶段进度（plans-contract v1.3）：{total, done, covered, effective_done}。"""
    covered_ids = covered_ids or set()
    out: dict = {}
    for key in STAGE_LABELS:
        stage_tasks = [t for t in tasks if t.stage == key]
        done = sum(1 for t in stage_tasks if t.status == "done")
        covered = sum(1 for t in stage_tasks if str(t.id) in covered_ids)
        effective_done = sum(1 for t in stage_tasks if t.status == "done" or str(t.id) in covered_ids)
        out[key] = {
            "total": len(stage_tasks),
            "done": done,
            "covered": covered,
            "effective_done": effective_done,
        }
    return out
