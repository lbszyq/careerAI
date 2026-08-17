"""task_jobs 表数据访问。"""
import uuid
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.models import TaskJob
from app.repositories.base import BaseRepository


def _today_start_shanghai() -> datetime:
    """当日 0 点（Asia/Shanghai，任务配额日计数口径，与 reports 配额一致）。"""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return datetime.combine(now.date(), time.min, tzinfo=ZoneInfo("Asia/Shanghai"))


class TaskJobRepository(BaseRepository):
    async def get_by_id(self, job_id: uuid.UUID) -> TaskJob | None:
        return await self.session.get(TaskJob, job_id)

    async def create(self, user_id: uuid.UUID | None, task_type: str) -> TaskJob:
        job = TaskJob(user_id=user_id, task_type=task_type, status="pending", progress=0)
        self.session.add(job)
        await self.session.flush()
        return job

    async def mark_running(self, job: TaskJob, stage: str) -> None:
        job.status = "running"
        job.stage = stage
        await self.session.flush()

    async def update_progress(self, job: TaskJob, progress: int, stage: str) -> None:
        job.status = "running"
        job.progress = progress
        job.stage = stage
        await self.session.flush()

    async def mark_succeeded(
        self, job: TaskJob, result: dict | None = None, result_ref: str | None = None
    ) -> None:
        job.status = "succeeded"
        job.progress = 100
        job.stage = "完成"
        job.result = result
        job.result_ref = result_ref
        job.finished_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def mark_failed(self, job: TaskJob, error_message: str) -> None:
        job.status = "failed"
        job.error_message = error_message
        job.finished_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def mark_cancelled(self, job: TaskJob) -> None:
        """取消：终态 cancelled + finished_at（tasks-contract）。"""
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def has_processing(self, user_id: uuid.UUID, task_type: str) -> bool:
        """同一用户/同类型是否已有进行中任务（pending/running，C-004 串行约束）。"""
        stmt = select(TaskJob.id).where(
            TaskJob.user_id == user_id,
            TaskJob.task_type == task_type,
            TaskJob.status.in_(("pending", "running")),
        )
        result = await self.session.execute(stmt.limit(1))
        return result.first() is not None

    # ---------- 任务配额（越权审计） ----------

    async def count_quota_today(self, user_id: uuid.UUID, task_types: tuple[str, ...]) -> int:
        """当日该用户创建的配额类型任务数（限流计数口径）。

        口径：Asia/Shanghai 自然日内 task_jobs.created_at 计数（含失败/取消——创建即占用配额，防刷）；
        作用域：按用户 × 自然日；配合 TaskQuotaErrorCode.TASK_QUOTA_EXCEEDED（3004）使用。
        """
        stmt = select(func.count()).select_from(TaskJob).where(
            TaskJob.user_id == user_id,
            TaskJob.task_type.in_(task_types),
            TaskJob.created_at >= _today_start_shanghai(),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # ---------- plan_reassess（feedback-contract v1.2） ----------

    async def has_plan_reassess_processing(self, user_id: uuid.UUID, plan_id: uuid.UUID) -> bool:
        """同一计划同一时刻最多 1 个进行中重评任务（pending/running）。

        plan_id 通过触发时写入 task_jobs.result 的上下文（{"plan_id": ...}）关联；
        执行器成功时保留该字段（叠加 summary），失败/取消时不覆盖。
        """
        stmt = select(TaskJob.id).where(
            TaskJob.user_id == user_id,
            TaskJob.task_type == "plan_reassess",
            TaskJob.status.in_(("pending", "running")),
            TaskJob.result["plan_id"].astext == str(plan_id),
        )
        result = await self.session.execute(stmt.limit(1))
        return result.first() is not None

    async def latest_plan_reassess(self, user_id: uuid.UUID, plan_id: uuid.UUID) -> TaskJob | None:
        """该计划最近一次重评任务（含 pending/running/succeeded/failed/cancelled），按创建时间倒序。"""
        stmt = (
            select(TaskJob)
            .where(
                TaskJob.user_id == user_id,
                TaskJob.task_type == "plan_reassess",
                TaskJob.result["plan_id"].astext == str(plan_id),
            )
            .order_by(TaskJob.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
