"""异步任务端点：触发任务 / 轮询状态 / 取消（+ tasks-contract）。"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.task import TaskCancelResult, TaskJobOut, TaskTriggerRequest, TaskTriggerResult
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TraceSpanOut(BaseModel):
    """任务链路 span 输出（字段对齐 trace_spans 契约）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trace_id: uuid.UUID
    parent_span_id: uuid.UUID | None
    span_type: str
    name: str
    status: str
    error_message: str | None
    duration_ms: int
    tokens: int
    cost: float
    hit_count: int
    created_at: datetime


@router.post("/trigger", response_model=ApiResponse[TaskTriggerResult])
async def trigger_task(
    req: TaskTriggerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await TaskService(db).trigger(current_user, req))


@router.get("/{task_id}", response_model=ApiResponse[TaskJobOut])
async def get_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await TaskService(db).get_job(current_user, task_id))


@router.get("/{task_id}/trace", response_model=ApiResponse[list[TraceSpanOut]])
async def get_task_trace(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await TaskService(db).get_trace(current_user, task_id))


@router.post("/{task_id}/cancel", response_model=ApiResponse[TaskCancelResult])
async def cancel_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await TaskService(db).cancel(current_user, task_id))
