"""反馈闭环业务编排（feedback-contract v1.2）：成果 CRUD / 重评异步 / 决策应用。

分层：Controller → Service（本文件）→ Repository。不可信输入约束：
- T-01：URL 协议 http/https + 长度 ≤500 双重校验（后端侧，前端表单侧由 同步）；仅文本存储，服务端不抓取。
- T-02：成果/重评归属按 plan → user 隔离（C-007）；跨用户 403，计划不存在 4104。
- T-04：本模块不基于 URL 发起任何外发请求。
"""
import uuid
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode
from app.models import User
from app.repositories.feedback_repository import AchievementRepository, ReassessmentRepository
from app.repositories.plan_repository import PlanRepository
from app.repositories.task_job_repository import TaskJobRepository
from app.schemas.feedback import (
    AchievementCreateRequest,
    AchievementDeleteOut,
    AchievementListOut,
    AchievementOut,
    AchievementUpdateRequest,
    LatestReassessOut,
    ReassessApplyOut,
    ReassessDiscardOut,
    ReassessmentDetailOut,
    ReassessmentListItem,
    ReassessmentListOut,
    ReassessSubmitOut,
)
from app.services.audit_service import AuditService
from app.services.error_codes import FeedbackErrorCode, PlanErrorCode
from app.services.task_service import TaskService

STAGE_LABELS = ("short", "mid", "long")
VALID_TASK_STATUS = ("todo", "doing", "done")
_URL_TOO_LONG = 500



def _achievement_out(row) -> AchievementOut:
    """显式构造（async ORM 下 from_attributes 可能触发 lazy 加载 MissingGreenlet）。"""
    return AchievementOut(
        id=row.id, plan_id=row.plan_id, name=row.name, url=row.url, description=row.description,
        stage=row.stage, task_id=row.task_id, created_at=row.created_at, updated_at=row.updated_at,
    )


def _reassessment_item_out(row) -> ReassessmentListItem:
    return ReassessmentListItem(
        id=row.id, task_id=row.task_id, status=row.status, decision=row.decision, summary=row.summary,
        created_at=row.created_at, decided_at=row.decided_at,
    )


def validate_achievement_url(url: str | None) -> None:
    """T-01 后端校验：协议 http/https + 长度 ≤500，不合法抛 3407。"""
    if not url or len(url) > _URL_TOO_LONG:
        raise ApiError(FeedbackErrorCode.ACHIEVEMENT_URL_INVALID,
                       "URL 仅支持 http/https 协议且不超过 500 字符", 400)
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        scheme = ""
    if scheme not in ("http", "https"):
        raise ApiError(FeedbackErrorCode.ACHIEVEMENT_URL_INVALID,
                       "URL 仅支持 http/https 协议且不超过 500 字符", 400)


class FeedbackService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.plan_repo = PlanRepository(session)
        self.ach_repo = AchievementRepository(session)
        self.reassess_repo = ReassessmentRepository(session)
        self.job_repo = TaskJobRepository(session)

    # ---------- 归属校验（C-007） ----------

    async def _get_owned_plan(self, user: User, plan_id: uuid.UUID):
        """区分「计划不存在(4104)」与「计划非本人(403)」（T-02 跨用户 403）。"""
        row = await self.plan_repo.get_with_owner(plan_id)
        if row is None:
            raise ApiError(PlanErrorCode.PLAN_NOT_FOUND, "成长计划不存在", 404)
        plan, owner_id = row
        if owner_id != user.id:
            raise ApiError(ErrorCode.FORBIDDEN, "无权访问该成长计划", 403)
        return plan

    # ---------- achievements CRUD ----------

    async def list_achievements(self, user: User, plan_id: uuid.UUID) -> AchievementListOut:
        await self._get_owned_plan(user, plan_id)
        items = await self.ach_repo.list_by_plan(plan_id)
        return AchievementListOut(plan_id=plan_id, items=[_achievement_out(a) for a in items])

    async def create_achievement(
        self, user: User, plan_id: uuid.UUID, req: AchievementCreateRequest
    ) -> AchievementOut:
        await self._get_owned_plan(user, plan_id)
        if not req.name:
            raise ApiError(ErrorCode.MISSING_REQUIRED, "name 必填", 400)
        if not req.url:
            raise ApiError(ErrorCode.MISSING_REQUIRED, "url 必填", 400)
        validate_achievement_url(req.url)
        if req.task_id is not None:
            await self._ensure_task_in_plan(plan_id, req.task_id)
        row = await self.ach_repo.create(plan_id, req.name, req.url, req.description, req.stage, req.task_id)
        await self.session.commit()
        return _achievement_out(row)

    async def update_achievement(
        self, user: User, plan_id: uuid.UUID, achievement_id: uuid.UUID, req: AchievementUpdateRequest
    ) -> AchievementOut:
        await self._get_owned_plan(user, plan_id)
        fields = req.model_fields_set
        if not fields:
            raise ApiError(ErrorCode.INVALID_PARAM, "请求体为空，至少传入 1 个可修改字段", 400)
        if "name" in fields and req.name is None:
            raise ApiError(ErrorCode.INVALID_PARAM, "name 不可清除，请传入合法值", 400)
        if "url" in fields and req.url is None:
            raise ApiError(ErrorCode.INVALID_PARAM, "url 不可清除，请传入合法值", 400)
        if "url" in fields:
            validate_achievement_url(req.url)
        if "task_id" in fields and req.task_id is not None:
            await self._ensure_task_in_plan(plan_id, req.task_id)

        row = await self.ach_repo.get(plan_id, achievement_id)
        if row is None:
            raise ApiError(FeedbackErrorCode.ACHIEVEMENT_NOT_FOUND, "成果不存在或不属于该计划", 404)
        if "name" in fields:
            row.name = req.name
        if "url" in fields:
            row.url = req.url
        if "description" in fields:
            row.description = req.description # None = 清除
        if "stage" in fields:
            row.stage = req.stage # None = 解除关联
        if "task_id" in fields:
            row.task_id = req.task_id # None = 解除关联
        await self.session.flush()
        await self.session.refresh(row) # onupdate 列（updated_at）需刷新后才可同步读取（async 下 commit 后访问会 MissingGreenlet）
        await self.session.commit()
        return _achievement_out(row)

    async def delete_achievement(self, user: User, plan_id: uuid.UUID, achievement_id: uuid.UUID):
        """DELETE achievements（关键操作）：REQUIRE_CONFIRMATION=true 时延迟确认。"""
        payload = {"plan_id": str(plan_id), "achievement_id": str(achievement_id)}
        if get_settings().REQUIRE_CONFIRMATION:
            return await AuditService(self.session).defer(
                user, "delete_achievement", "achievement", str(achievement_id), payload
            )
        result = await self._delete_achievement(user, plan_id, achievement_id)
        await AuditService(self.session).record_auto_approved(
            user, "delete_achievement", "achievement", str(achievement_id), payload
        )
        return result

    async def _delete_achievement(self, user: User, plan_id: uuid.UUID, achievement_id: uuid.UUID) -> AchievementDeleteOut:
        await self._get_owned_plan(user, plan_id)
        row = await self.ach_repo.get(plan_id, achievement_id)
        if row is None:
            raise ApiError(FeedbackErrorCode.ACHIEVEMENT_NOT_FOUND, "成果不存在或不属于该计划", 404)
        await self.ach_repo.delete(row)
        await self.session.commit()
        return AchievementDeleteOut(id=achievement_id)

    async def _ensure_task_in_plan(self, plan_id: uuid.UUID, task_id: uuid.UUID) -> None:
        task = await self.plan_repo.get_task(plan_id, task_id)
        if task is None:
            raise ApiError(FeedbackErrorCode.ACHIEVEMENT_ASSOCIATION_INVALID, "关联任务不属于该计划", 400)

    # ---------- reassessments 提交/查询 ----------

    async def create_reassessment(self, user: User, plan_id: uuid.UUID) -> ReassessSubmitOut:
        await self._get_owned_plan(user, plan_id)
        has_ach = await self.ach_repo.exists_for_plan(plan_id)
        tasks = await self.plan_repo.get_tasks(plan_id)
        has_progress = any(t.status in ("doing", "done") for t in tasks)
        if not has_ach and not has_progress:
            raise ApiError(FeedbackErrorCode.REASSESS_NOT_ELIGIBLE, "请先上传成果或标记任务进度", 400)
        if await self.job_repo.has_plan_reassess_processing(user.id, plan_id):
            raise ApiError(FeedbackErrorCode.REASSESS_IN_PROGRESS, "该计划已有进行中的重评任务", 409)

        job = await TaskService(self.session).create_and_dispatch(
            user, "plan_reassess", {"plan_id": str(plan_id)}
        )
        # plan 关联上下文：用于并发检查与 latest_reassess 回显；执行器成功时保留并叠加 summary
        job.result = {"plan_id": str(plan_id)}
        await self.session.commit()
        return ReassessSubmitOut(task_id=job.id, status=job.status)

    async def list_reassessments(self, user: User, plan_id: uuid.UUID) -> ReassessmentListOut:
        await self._get_owned_plan(user, plan_id)
        recs = await self.reassess_repo.list_by_plan(plan_id)
        return ReassessmentListOut(
            plan_id=plan_id, items=[_reassessment_item_out(r) for r in recs]
        )

    async def get_reassessment(
        self, user: User, plan_id: uuid.UUID, reassess_id: uuid.UUID
    ) -> ReassessmentDetailOut:
        await self._get_owned_plan(user, plan_id)
        rec = await self.reassess_repo.get(plan_id, reassess_id)
        if rec is None:
            raise ApiError(FeedbackErrorCode.REASSESSMENT_NOT_FOUND, "重评记录不存在或不属于该计划", 404)
        result = rec.result or {}
        return ReassessmentDetailOut(
            id=rec.id, plan_id=rec.plan_id, task_id=rec.task_id, status=rec.status, decision=rec.decision,
            summary=rec.summary,
            gap_change=result.get("gap_change"), plan_adjustment=result.get("plan_adjustment"),
            stage_checks=result.get("stage_checks"), adjustment_explanation=result.get("adjustment_explanation"),
            created_at=rec.created_at, decided_at=rec.decided_at,
        )

    # ---------- 决策（apply / discard） ----------

    async def _load_decidable(self, user: User, plan_id: uuid.UUID, reassess_id: uuid.UUID):
        """共用决策前置：4104/403 → 4108 → 3404 → 3405（防御）。"""
        await self._get_owned_plan(user, plan_id)
        rec = await self.reassess_repo.get(plan_id, reassess_id)
        if rec is None:
            raise ApiError(FeedbackErrorCode.REASSESSMENT_NOT_FOUND, "重评记录不存在或不属于该计划", 404)
        if rec.decision != "undecided":
            raise ApiError(FeedbackErrorCode.REASSESS_ALREADY_DECIDED, "该重评记录已应用或放弃，不可重复操作", 409)
        if rec.status != "succeeded":
            raise ApiError(FeedbackErrorCode.REASSESS_NOT_DECIDABLE, "该重评记录不可应用或放弃", 409)
        return rec

    async def apply_reassessment(self, user: User, plan_id: uuid.UUID, reassess_id: uuid.UUID):
        """应用重评（关键操作）：REQUIRE_CONFIRMATION=true 时延迟确认。"""
        payload = {"plan_id": str(plan_id), "reassess_id": str(reassess_id)}
        if get_settings().REQUIRE_CONFIRMATION:
            return await AuditService(self.session).defer(
                user, "apply_reassessment", "reassessment", str(reassess_id), payload
            )
        result = await self._apply_reassessment(user, plan_id, reassess_id)
        await AuditService(self.session).record_auto_approved(
            user, "apply_reassessment", "reassessment", str(reassess_id), payload
        )
        return result

    async def _apply_reassessment(
        self, user: User, plan_id: uuid.UUID, reassess_id: uuid.UUID
    ) -> ReassessApplyOut:
        plan = await self._get_owned_plan(user, plan_id)
        rec = await self._load_decidable(user, plan_id, reassess_id)
        result = rec.result or {}
        plan_adjustment = result.get("plan_adjustment") or {}
        await self._apply_changes(plan, plan_adjustment)
        await self.reassess_repo.decide(rec, "applied")
        progress = await self.plan_repo.recalc_progress(plan_id)
        await self.session.commit()
        return ReassessApplyOut(
            reassess_id=rec.id, plan_id=plan.id, decision="applied",
            applied_at=rec.decided_at, progress=progress,
        )

    async def discard_reassessment(self, user: User, plan_id: uuid.UUID, reassess_id: uuid.UUID):
        """放弃重评（关键操作）：REQUIRE_CONFIRMATION=true 时延迟确认。"""
        payload = {"plan_id": str(plan_id), "reassess_id": str(reassess_id)}
        if get_settings().REQUIRE_CONFIRMATION:
            return await AuditService(self.session).defer(
                user, "discard_reassessment", "reassessment", str(reassess_id), payload
            )
        result = await self._discard_reassessment(user, plan_id, reassess_id)
        await AuditService(self.session).record_auto_approved(
            user, "discard_reassessment", "reassessment", str(reassess_id), payload
        )
        return result

    async def _discard_reassessment(
        self, user: User, plan_id: uuid.UUID, reassess_id: uuid.UUID
    ) -> ReassessDiscardOut:
        plan = await self._get_owned_plan(user, plan_id)
        rec = await self._load_decidable(user, plan_id, reassess_id)
        await self.reassess_repo.decide(rec, "discarded")
        await self.session.commit()
        return ReassessDiscardOut(
            reassess_id=rec.id, plan_id=plan.id, decision="discarded", discarded_at=rec.decided_at
        )

    async def _apply_changes(self, plan, plan_adjustment: dict) -> None:
        """应用规则（feedback-contract）：增删改 plan_tasks 与 growth_plans.stages；
        所有 status=done 任务保持 done（不回退，含 conflicts 中任务，用户完成为准）。

        /（分层双源语义）：本方法是「运行时状态」写方——只写 plan_tasks /
        growth_plans.stages 表，**不回写 career_reports.result JSONB 生成快照**（报告=生成时
        快照 C-005 不可变，勾选/重评属实时状态，由 GET /plans/{id} 从表读取反映）。
        """
        changes = plan_adjustment.get("changes") or []
        conflicts = {
            str(c.get("task_id")) for c in (plan_adjustment.get("conflicts") or []) if c.get("task_id")
        }
        for ch in changes:
            if not isinstance(ch, dict):
                continue
            action = ch.get("action")
            target = ch.get("target")
            stage = ch.get("stage")
            task_id_raw = ch.get("task_id")
            if action == "add" and target == "task" and ch.get("name"):
                sort_order = await self.plan_repo.max_sort_order(plan.id) + 1
                await self.plan_repo.add_task(plan.id, ch["name"], stage, sort_order)
            elif action == "remove" and target == "task" and task_id_raw:
                task = await self.plan_repo.get_task(plan.id, uuid.UUID(str(task_id_raw)))
                if task is not None and not (task.status == "done" and str(task.id) in conflicts):
                    await self.plan_repo.delete_task(task)
            elif action == "modify" and target == "task" and task_id_raw:
                task = await self.plan_repo.get_task(plan.id, uuid.UUID(str(task_id_raw)))
                if task is None or task.status == "done":
                    continue # 保留用户已完成标记
                if ch.get("name"):
                    task.name = ch["name"]
                if ch.get("status") in VALID_TASK_STATUS:
                    task.status = ch["status"]
                if ch.get("stage") in STAGE_LABELS:
                    task.stage = ch["stage"]
                await self.session.flush()
            elif target == "stage" and stage in STAGE_LABELS:
                await self._apply_stage_change(plan, stage, ch)

    @staticmethod
    async def _apply_stage_change(plan, stage: str, ch: dict) -> None:
        """合并 growth_plans.stages[stage] 的文本字段（add/modify 均可；字段缺失则不变）。"""
        stages = dict(plan.stages or {})
        meta = dict(stages.get(stage) or {})
        for key in ("label", "goal", "why", "verify", "resume_value", "stage_completion"):
            if key in ch and ch[key] is not None:
                meta[key] = ch[key]
        stages[stage] = meta
        plan.stages = stages

    # ---------- GET /plans/{plan_id} 回显（plans-contract v1.2） ----------

    async def build_plan_echo(self, user: User, plan) -> dict:
        """回显：achievements / reassess_eligible(+reason) / latest_reassess / completion_check。

        存量计划优雅降级：achievements=[]、eligible=false、latest=null、completion_check=unchecked。
        """
        achievements = await self.ach_repo.list_by_plan(plan.id)
        tasks = await self.plan_repo.get_tasks(plan.id)
        eligible = bool(achievements) or any(t.status in ("doing", "done") for t in tasks)
        reason = None if eligible else "请先上传成果或标记任务进度"

        latest = None
        latest_job = await self.job_repo.latest_plan_reassess(user.id, plan.id)
        if latest_job is not None:
            latest = LatestReassessOut(
                task_id=latest_job.id, status=latest_job.status, result_ref=latest_job.result_ref,
                created_at=latest_job.created_at, finished_at=latest_job.finished_at,
            )

        completion_checks: dict = {}
        latest_suc = await self.reassess_repo.latest_succeeded(plan.id)
        if latest_suc is not None and isinstance(latest_suc.result, dict):
            stage_checks = latest_suc.result.get("stage_checks") or {}
            for stage in STAGE_LABELS:
                check = stage_checks.get(stage) or {}
                completion_checks[stage] = "pass" if check.get("result") == "pass" else "fail"

        return {
            "achievements": [_achievement_out(a) for a in achievements],
            "reassess_eligible": eligible,
            "reassess_eligible_reason": reason,
            "latest_reassess": latest,
            "completion_checks": completion_checks,
        }
