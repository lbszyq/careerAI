"""plan_regenerate 执行器（）：基于已有差距分析 + 最新市场数据重跑 executor+planner。

：图补齐 executor 节点后，plan 由 executor 基于最新市场数据生成（LLM/规则兜底），
planner 组装报告；gap_analyses 表与 report.result.gap_analysis 保留旧值（update_plan 仅写 plan/suggestion）。
"""
import logging
import uuid

from sqlalchemy import select

from app.ai.agents.deps import AgentDeps
from app.ai.graphs import build_plan_regenerate_graph
from app.ai.llm.client import get_llm_client
from app.ai.persistence import update_plan
from app.ai.rag.embedding import get_embedding_provider
from app.ai.fallback.report_assembler import assemble_stage2_report
from app.ai.schemas import initial_state
from app.db.base import AsyncSessionLocal
from app.models import CareerReport, GapAnalysis, GrowthPlan, UserProfile
from app.tasks.executors.ai_base import AIExecutor, profile_to_dict, safe_run_graph
from app.tasks.executors.registry import ExecutorRegistry

logger = logging.getLogger("careerai.ai.executors.plan_regenerate")


class PlanRegenerateExecutor(AIExecutor):
    task_type = "plan_regenerate"

    async def execute(self, job_id: str, params: dict) -> None:
        try:
            user_id = uuid.UUID(params.get("user_id") or "")
            report_id = uuid.UUID(params.get("report_id") or "")
        except (TypeError, ValueError):
            async with AsyncSessionLocal() as session:
                await self._mark_failed(session, job_id, "参数缺失或非法（user_id/report_id）")
            return

        async with AsyncSessionLocal() as session:
            # 越权锚点（唯一可信 = job.user_id）：params.user_id 必须等于任务归属用户；
            # 报告归属比对同样锚定 job.user_id（不得用攻击者可控的 params.user_id）。
            job = await self._get_job(session, job_id)
            if job is None or job.user_id is None or user_id != job.user_id:
                await self._mark_failed(session, job_id, "无权执行该任务")
                return
            if not await self._update_progress(session, job_id, 20, "目标岗位要求"):
                return
            report_row = await session.get(CareerReport, report_id)
            if report_row is None or report_row.user_id != job.user_id:
                await self._mark_failed(session, job_id, "报告不存在或非本人")
                return
            stmt = select(GapAnalysis).where(GapAnalysis.report_id == report_id)
            gap_row = (await session.execute(stmt)).scalars().first()
            plan_stmt = select(GrowthPlan).where(GrowthPlan.report_id == report_id)
            plan_row = (await session.execute(plan_stmt)).scalars().first()
            if gap_row is None or plan_row is None:
                await self._mark_failed(session, job_id, "该报告尚未完成差距分析，无法重新生成计划（3205）")
                return

            profile = {}
            if report_row.profile_id is not None:
                profile_row = await session.get(UserProfile, report_row.profile_id)
                if profile_row is not None:
                    profile = profile_to_dict(profile_row)

            deps = AgentDeps(
                db=session,
                llm=get_llm_client(),
                embedding=get_embedding_provider(),
                on_progress=self._progress_cb(session, job_id),
            )
            state = initial_state(
                user_id=str(user_id),
                report_id=str(report_id),
                profile=profile,
                target_job=gap_row.target_job,
                gap_items=list(gap_row.items or []),
                preferred_cities=params.get("preferred_cities") or [],
                preferred_industries=params.get("preferred_industries") or [],
                stage="stage2",
            )
            graph = build_plan_regenerate_graph(deps)
            result = await safe_run_graph(session, job_id, graph, state)
            if result is None:
                return # 已 mark_failed
            report = result.get("report") or assemble_stage2_report(result, target_job=gap_row.target_job)

            if await self._is_cancelled(session, job_id):
                return # 取消不更新计划
            await update_plan(session, plan_id=plan_row.id, report=report)
            await session.commit()
            await self._mark_succeeded(
                session,
                job_id,
                result={"plan_id": str(plan_row.id), "stage": "stage2"},
                result_ref=f"/api/v1/plans/{plan_row.id}",
            )

    def _progress_cb(self, session, job_id: str):
        async def on_progress(percent: int, stage: str) -> None:
            await self._update_progress(session, job_id, percent, stage)

        return on_progress


ExecutorRegistry.register(PlanRegenerateExecutor())
