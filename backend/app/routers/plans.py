"""计划端点（plans-contract）：计划详情 / 进度 / 任务状态更新。"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.plans import PlanDetailOut, PlanProgressOut, PlanTaskUpdateOut, PlanTaskUpdateRequest
from app.services.plan_service import PlanService

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/{plan_id}", response_model=ApiResponse[PlanDetailOut])
async def get_plan(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await PlanService(db).get_plan(current_user, plan_id))


@router.get("/{plan_id}/progress", response_model=ApiResponse[PlanProgressOut])
async def get_plan_progress(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await PlanService(db).get_progress(current_user, plan_id))


@router.patch("/{plan_id}/tasks/{task_id}", response_model=ApiResponse[PlanTaskUpdateOut])
async def update_task_status(
    plan_id: uuid.UUID,
    task_id: uuid.UUID,
    req: PlanTaskUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await PlanService(db).update_task(current_user, plan_id, task_id, req))
