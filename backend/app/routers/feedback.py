"""反馈闭环端点（feedback-contract v1.2）：成果 CRUD + 重评申请/列表/详情/决策。

路由层只做参数解析与 Service 调用，不包含业务判断（分层）。
"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import User
from app.schemas.audit import OperationConfirmationOut
from app.schemas.common import ApiResponse
from app.schemas.feedback import (
    AchievementCreateRequest,
    AchievementDeleteOut,
    AchievementListOut,
    AchievementOut,
    AchievementUpdateRequest,
    ReassessApplyOut,
    ReassessDiscardOut,
    ReassessmentDetailOut,
    ReassessmentListOut,
    ReassessSubmitOut,
)
from app.services.feedback_service import FeedbackService

router = APIRouter(prefix="/plans", tags=["feedback"])


# ---------- achievements ----------

@router.get("/{plan_id}/achievements", response_model=ApiResponse[AchievementListOut])
async def list_achievements(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).list_achievements(current_user, plan_id))


@router.post("/{plan_id}/achievements", response_model=ApiResponse[AchievementOut])
async def create_achievement(
    plan_id: uuid.UUID,
    req: AchievementCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).create_achievement(current_user, plan_id, req))


@router.patch("/{plan_id}/achievements/{achievement_id}", response_model=ApiResponse[AchievementOut])
async def update_achievement(
    plan_id: uuid.UUID,
    achievement_id: uuid.UUID,
    req: AchievementUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).update_achievement(current_user, plan_id, achievement_id, req))


@router.delete("/{plan_id}/achievements/{achievement_id}", response_model=ApiResponse[AchievementDeleteOut | OperationConfirmationOut])
async def delete_achievement(
    plan_id: uuid.UUID,
    achievement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).delete_achievement(current_user, plan_id, achievement_id))


# ---------- reassessments ----------

@router.post("/{plan_id}/reassessments", response_model=ApiResponse[ReassessSubmitOut])
async def create_reassessment(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).create_reassessment(current_user, plan_id))


@router.get("/{plan_id}/reassessments", response_model=ApiResponse[ReassessmentListOut])
async def list_reassessments(
    plan_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).list_reassessments(current_user, plan_id))


@router.get("/{plan_id}/reassessments/{reassess_id}", response_model=ApiResponse[ReassessmentDetailOut])
async def get_reassessment(
    plan_id: uuid.UUID,
    reassess_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).get_reassessment(current_user, plan_id, reassess_id))


@router.post("/{plan_id}/reassessments/{reassess_id}/apply", response_model=ApiResponse[ReassessApplyOut | OperationConfirmationOut])
async def apply_reassessment(
    plan_id: uuid.UUID,
    reassess_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).apply_reassessment(current_user, plan_id, reassess_id))


@router.post("/{plan_id}/reassessments/{reassess_id}/discard", response_model=ApiResponse[ReassessDiscardOut | OperationConfirmationOut])
async def discard_reassessment(
    plan_id: uuid.UUID,
    reassess_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await FeedbackService(db).discard_reassessment(current_user, plan_id, reassess_id))
