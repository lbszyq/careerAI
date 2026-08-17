"""report_stage2 执行器（）：Stage 2 图 → gap_analyses + growth_plans + plan_tasks（仅成功时落库）。"""
import logging
import uuid

from sqlalchemy import select

from app.ai.agents.deps import AgentDeps
from app.ai.fallback.report_assembler import assemble_stage2_report
from app.ai.graphs import build_stage2_graph
from app.ai.llm.client import get_llm_client
from app.ai.persistence import save_stage2_result
from app.ai.rag.embedding import get_embedding_provider
from app.ai.schemas import initial_state
from app.db.base import AsyncSessionLocal
from app.models import CareerDirection, CareerReport, UserProfile
from app.tasks.executors.ai_base import AIExecutor, profile_to_dict, safe_run_graph
from app.tasks.executors.registry import ExecutorRegistry

logger = logging.getLogger("careerai.ai.executors.report_stage2")


class ReportStage2Executor(AIExecutor):
    task_type = "report_stage2"

    async def execute(self, job_id: str, params: dict) -> None:
        try:
            user_id = uuid.UUID(params.get("user_id") or "")
            report_id = uuid.UUID(params.get("report_id") or "")
            direction_id = uuid.UUID(params.get("direction_id") or "")
        except (TypeError, ValueError):
            async with AsyncSessionLocal() as session:
                await self._mark_failed(session, job_id, "参数缺失或非法（user_id/report_id/direction_id）")
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
            direction = await session.get(CareerDirection, direction_id)
            if direction is None or direction.report_id != report_id:
                await self._mark_failed(session, job_id, "目标方向不存在或不属于该报告")
                return

            profile = {}
            if report_row.profile_id is not None:
                profile_row = await session.get(UserProfile, report_row.profile_id)
                if profile_row is not None:
                    profile = profile_to_dict(profile_row)

            # QA-BUG-013：Stage2 图无 career_analysis 节点，携带 Stage1 画像（scores）
            # 供 planner 整合——Stage2 报告/兜底均能保留画像，避免输出空对象。
            stage1_portrait = (report_row.result or {}).get("portrait") or {}

            deps = AgentDeps(
                db=session,
                llm=get_llm_client(),
                embedding=get_embedding_provider(),
                on_progress=self._progress_cb(session, job_id),
            )
            state = initial_state(
                user_id=str(user_id),
                report_id=str(report_id),
                direction_id=str(direction_id),
                profile=profile,
                target_job=direction.job_title,
                preferred_cities=params.get("preferred_cities") or [],
                preferred_industries=params.get("preferred_industries") or [],
                scores=stage1_portrait,
                stage="stage2",
            )
            graph = build_stage2_graph(deps)
            result = await safe_run_graph(session, job_id, graph, state)
            if result is None:
                return # 已 mark_failed
            report = result.get("report") or assemble_stage2_report(result, target_job=direction.job_title)

            if await self._is_cancelled(session, job_id):
                return # 取消不落库（决策③）
            plan_id = await save_stage2_result(
                session,
                report_id=report_id,
                direction_id=direction_id,
                target_job=direction.job_title,
                report=report,
                confidence=result.get("confidence"), # QA-BUG-017：透传 GraphState 置信度
            )
            await session.commit()
            await self._mark_succeeded(
                session,
                job_id,
                result={"plan_id": str(plan_id), "stage": "stage2"},
                result_ref=f"/api/v1/plans/{plan_id}",
            )

    def _progress_cb(self, session, job_id: str):
        async def on_progress(percent: int, stage: str) -> None:
            await self._update_progress(session, job_id, percent, stage)

        return on_progress


ExecutorRegistry.register(ReportStage2Executor())
