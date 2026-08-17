"""plan_reassess 执行器（feedback-contract v1.2）：基于成果 + 任务状态重评差距与计划。

- 重评聚焦差距 + 成长计划（画像/方向不重算）。
- 重评记录仅任务成功时落库（决策③：失败/取消不产生半成品记录）；
  落库与 task_jobs 标记成功在同一事务，避免竞态窗口。
- 接缝：调用 app.ai.reassessment.generate_reassessment(...)（交付）。
- 宁缺毋滥：重评 Agent 延迟导入（execute() 内首次调用），ImportError
  → 任务 mark_failed；删除 _mock_reassessment 兜底——组件不可用/结果畸形一律显式失败，
  不输出编造的「差距缩小 N 项」假结果，也不静默落库默认 summary。
- 不可信输入：本执行器不基于成果 URL 发起任何外发请求（T-04）；证据引用仅用服务端已存字段（T-05）。
"""
import logging
import uuid

from app.db.base import AsyncSessionLocal
from app.models import CareerReport, GrowthPlan
from app.repositories.feedback_repository import AchievementRepository, ReassessmentRepository
from app.repositories.plan_repository import PlanRepository
from app.repositories.task_job_repository import TaskJobRepository
from app.tasks.executors.ai_base import AIExecutor
from app.tasks.executors.registry import ExecutorRegistry

logger = logging.getLogger("careerai.ai.executors.plan_reassess")

# 失败接缝：重评 Agent 延迟导入（不在模块顶部 import——ImportError 时执行器
# 仍可注册、plan_reassess 任务类型保持可用，导入失败在 execute() 内显式 mark_failed）。
# 模块级同名属性供测试注入（test_task_authz 等 monkeypatch.setattr(...) 复用）。
generate_reassessment = None # 首次 execute() 时由 _load_reassessment() 回填


def _load_reassessment():
    """延迟导入重评 Agent（宁缺毋滥失败接缝）。

    - 首次调用时导入 app.ai.reassessment.generate_reassessment 并回填模块级属性；
    - 组件不可用（ImportError）→ 原样上抛，由 execute() 捕获并 mark_failed；
    - 测试可 monkeypatch 模块级 generate_reassessment（注入 mock）或本函数（注入失败）。
    """
    global generate_reassessment
    if generate_reassessment is not None:
        return generate_reassessment
    from app.ai.reassessment import generate_reassessment as _gen

    generate_reassessment = _gen
    return generate_reassessment


class PlanReassessExecutor(AIExecutor):
    task_type = "plan_reassess"

    async def execute(self, job_id: str, params: dict) -> None:
        try:
            plan_id = uuid.UUID(params.get("plan_id") or "")
        except (TypeError, ValueError):
            async with AsyncSessionLocal() as session:
                await self._mark_failed(session, job_id, "参数缺失或非法（plan_id）")
            return

        async with AsyncSessionLocal() as session:
            # 越权锚点（唯一可信 = job.user_id）：GrowthPlan 无 user_id 列，
            # 归属经 plan_repository.get_with_owner JOIN career_reports 校验并与 job.user_id 比对
            # （IDOR：防经 trigger 传他人 plan_id 触发重评）；不符 → mark_failed，不落库。
            job = await self._get_job(session, job_id)
            if job is None or job.user_id is None:
                await self._mark_failed(session, job_id, "无权执行该任务")
                return
            if not await self._update_progress(session, job_id, 10, "读取执行证据"):
                return
            owned = await PlanRepository(session).get_with_owner(plan_id)
            if owned is None:
                await self._mark_failed(session, job_id, "成长计划不存在")
                return
            plan, plan_owner_id = owned
            if plan_owner_id != job.user_id:
                await self._mark_failed(session, job_id, "无权访问该成长计划")
                return
            report = await session.get(CareerReport, plan.report_id)
            if report is None:
                await self._mark_failed(session, job_id, "关联报告不存在")
                return

            tasks = await PlanRepository(session).get_tasks(plan_id)
            achievements = await AchievementRepository(session).list_by_plan(plan_id)
            # 前置防御（对齐 3402）：无成果且无任务状态变化 → 失败（不落库）
            has_progress = any(t.status in ("doing", "done") for t in tasks)
            if not achievements and not has_progress:
                await self._mark_failed(session, job_id, "请先上传成果或标记任务进度")
                return

            if not await self._update_progress(session, job_id, 40, "评估差距变化"):
                return
            task_dicts = [
                {"id": str(t.id), "name": t.name, "stage": t.stage, "status": t.status}
                for t in tasks
            ]
            achievement_dicts = [
                {"id": str(a.id), "name": a.name, "url": a.url, "description": a.description,
                 "stage": a.stage, "task_id": str(a.task_id) if a.task_id else None}
                for a in achievements
            ]
            try:
                reassess_fn = _load_reassessment()
            except ImportError:
                logger.exception("plan_reassess: 重评组件导入失败 job=%s", job_id)
                await self._mark_failed(session, job_id, "重新评估组件不可用，请稍后重试")
                return
            try:
                result = await reassess_fn(
                    report=report.result or {},
                    task_statuses=task_dicts,
                    achievements=achievement_dicts,
                )
            except Exception as exc: # noqa: BLE001 失败不落库，任务标记 failed 可重试
                logger.exception("plan_reassess: 重评执行失败 job=%s", job_id)
                await self._mark_failed(session, job_id, "重新评估失败，请稍后重试")
                return

            # 边界：结果畸形（None/非 dict/缺 summary）→ 显式失败，不静默落库
            # 默认「重新评估完成」文案（宁缺毋滥：重评 Agent 契约保证四部分结构含 summary）。
            if not isinstance(result, dict):
                await self._mark_failed(session, job_id, "重新评估结果格式无效，请稍后重试")
                return
            summary = str(result.get("summary") or "").strip()
            if not summary:
                await self._mark_failed(session, job_id, "重新评估结果缺少摘要，请稍后重试")
                return

            if not await self._update_progress(session, job_id, 80, "生成计划调整建议"):
                return
            if await self._is_cancelled(session, job_id):
                return # 取消不产生半成品记录

            rec = await ReassessmentRepository(session).create_succeeded(
                plan_id, uuid.UUID(job_id), summary, result
            )
            # 落库 + 成功标记同一事务（：成功才落库；避免取消竞态）
            job = await self._get_job(session, job_id)
            if job is not None:
                await TaskJobRepository(session).mark_succeeded(
                    job,
                    result={"plan_id": str(plan_id), "summary": summary},
                    result_ref=f"/api/v1/plans/{plan_id}/reassessments/{rec.id}",
                )
            await session.commit()


ExecutorRegistry.register(PlanReassessExecutor())
