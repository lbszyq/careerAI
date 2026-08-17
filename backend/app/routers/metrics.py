"""指标汇总端点（/ 扩范围）：按当前用户聚合任务完成率与 span 指标。

- 来源 = trace_spans DB 聚合（token_tracker 为内存单例，非持久化，不可作汇总源）。
- 仅统计当前用户（trace_spans 经 trace_id join task_jobs.user_id），避免跨用户数据泄露。
- 空数据返回 0 值（非除零/NaN）。
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import TaskJob, User
from app.models.trace_span import TraceSpan
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])

logger = logging.getLogger("careerai.metrics")


class MetricsSummaryOut(BaseModel):
    task_completion_rate: float
    avg_duration_ms: float
    total_tokens: int
    total_cost: float


async def compute_metrics_summary(session: AsyncSession, user_id) -> dict:
    """按用户聚合：完成率 / task span 平均耗时 / llm span token 与成本。空数据返回 0。

    口径：
    - task_completion_rate = succeeded / total（total 含 cancelled 等全部任务）。
    - avg_duration_ms 只聚合 status='succeeded' 的 task span（排除 running/failed，
      避免未 finish 的 0ms 拉低均值）。
    - total_tokens / total_cost 只聚合 span_type='llm'（失败调用 tokens=0/cost=0，无影响）。
    """
    total = (await session.execute(
        select(func.count(TaskJob.id)).where(TaskJob.user_id == user_id)
    )).scalar()
    succeeded = (await session.execute(
        select(func.count(TaskJob.id)).where(
            TaskJob.user_id == user_id, TaskJob.status == "succeeded"
        )
    )).scalar()
    total = total or 0
    succeeded = succeeded or 0
    rate = (succeeded / total) if total else 0.0

    avg_dur = (await session.execute(
        select(func.coalesce(func.avg(TraceSpan.duration_ms), 0.0))
        .select_from(TraceSpan)
        .join(TaskJob, TraceSpan.trace_id == TaskJob.trace_id)
        .where(
            TaskJob.user_id == user_id,
            TraceSpan.span_type == "task",
            TraceSpan.status == "succeeded",
        )
    )).scalar()

    total_tokens = (await session.execute(
        select(func.coalesce(func.sum(TraceSpan.tokens), 0))
        .select_from(TraceSpan)
        .join(TaskJob, TraceSpan.trace_id == TaskJob.trace_id)
        .where(TaskJob.user_id == user_id, TraceSpan.span_type == "llm")
    )).scalar()

    total_cost = (await session.execute(
        select(func.coalesce(func.sum(TraceSpan.cost), 0.0))
        .select_from(TraceSpan)
        .join(TaskJob, TraceSpan.trace_id == TaskJob.trace_id)
        .where(TaskJob.user_id == user_id, TraceSpan.span_type == "llm")
    )).scalar()

    return {
        "task_completion_rate": float(rate),
        "avg_duration_ms": float(avg_dur) if avg_dur is not None else 0.0,
        "total_tokens": int(total_tokens) if total_tokens is not None else 0,
        "total_cost": float(total_cost) if total_cost is not None else 0.0,
    }


@router.get("/summary", response_model=ApiResponse[MetricsSummaryOut])
async def metrics_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await compute_metrics_summary(db, current_user.id)
    return ApiResponse(data=MetricsSummaryOut(**data))
