"""report_stage1 执行器（）：Stage 1 图 → career_reports + career_directions（仅成功时落库）。"""
import logging
import uuid

from sqlalchemy import select

from app.ai.agents.deps import AgentDeps
from app.ai.fallback.report_assembler import assemble_stage1_report
from app.ai.graphs import build_stage1_graph
from app.ai.llm.client import get_llm_client
from app.ai.persistence import save_stage1_result
from app.ai.rag.embedding import get_embedding_provider
from app.ai.schemas import initial_state
from app.db.base import AsyncSessionLocal
from app.models import UserProfile
from app.tasks.executors.ai_base import AIExecutor, profile_to_dict, safe_run_graph
from app.tasks.executors.registry import ExecutorRegistry

logger = logging.getLogger("careerai.ai.executors.report_stage1")


class ReportStage1Executor(AIExecutor):
    task_type = "report_stage1"

    async def execute(self, job_id: str, params: dict) -> None:
        try:
            user_id = uuid.UUID(params.get("user_id") or "")
            profile_id = uuid.UUID(params.get("profile_id") or "")
        except (TypeError, ValueError):
            async with AsyncSessionLocal() as session:
                await self._mark_failed(session, job_id, "参数缺失或非法（user_id/profile_id）")
            return

        async with AsyncSessionLocal() as session:
            # 越权锚点（唯一可信 = job.user_id）：params.user_id 必须等于任务归属用户；
            # 画像归属查询同样锚定 job.user_id（不得用攻击者可控的 params.user_id 过滤）。
            job = await self._get_job(session, job_id)
            if job is None or job.user_id is None or user_id != job.user_id:
                await self._mark_failed(session, job_id, "无权执行该任务")
                return
            if not await self._update_progress(session, job_id, 10, "解析画像"):
                return
            stmt = select(UserProfile).where(
                UserProfile.id == profile_id, UserProfile.user_id == job.user_id
            )
            profile_row = (await session.execute(stmt)).scalars().first()
            if profile_row is None:
                await self._mark_failed(session, job_id, "画像不存在或非本人")
                return
            profile = profile_to_dict(profile_row)

            deps = AgentDeps(
                db=session,
                llm=get_llm_client(),
                embedding=get_embedding_provider(),
                on_progress=self._progress_cb(session, job_id),
            )
            state = initial_state(
                user_id=str(user_id),
                profile_id=str(profile_id),
                profile=profile,
                preferred_cities=params.get("preferred_cities") or [],
                preferred_industries=params.get("preferred_industries") or [],
                expected_salary=getattr(profile_row, "expected_salary", None),
                stage="stage1",
            )
            graph = build_stage1_graph(deps)
            result = await safe_run_graph(session, job_id, graph, state)
            if result is None:
                return # 已 mark_failed
            report = result.get("report") or assemble_stage1_report(result)

            if await self._is_cancelled(session, job_id):
                return # 取消不落库（决策③ /）
            report_id, _ = await save_stage1_result(
                session, user_id=user_id, profile_id=profile_id, report=report
            )
            await session.commit()
            await self._mark_succeeded(
                session,
                job_id,
                result={"report_id": str(report_id), "stage": "stage1"},
                result_ref=f"/api/v1/reports/{report_id}",
            )

    def _progress_cb(self, session, job_id: str):
        async def on_progress(percent: int, stage: str) -> None:
            await self._update_progress(session, job_id, percent, stage)

        return on_progress


ExecutorRegistry.register(ReportStage1Executor())
