"""audit 确认端点：批准 / 拒绝待确认的关键操作。

REQUIRE_CONFIRMATION=true 时，关键操作先落 pending 并返回 confirmation_id；
本端点按该 id 执行批准（重放原操作）或拒绝（不执行）。
"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import User
from app.schemas.audit import OperationDecisionOut
from app.schemas.common import ApiResponse
from app.services.audit_service import AuditService

router = APIRouter(prefix="/operations", tags=["audit"])


@router.post("/{confirmation_id}/approve", response_model=ApiResponse[OperationDecisionOut])
async def approve_operation(
    confirmation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await AuditService(db).approve(current_user, confirmation_id))


@router.post("/{confirmation_id}/reject", response_model=ApiResponse[OperationDecisionOut])
async def reject_operation(
    confirmation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await AuditService(db).reject(current_user, confirmation_id))
