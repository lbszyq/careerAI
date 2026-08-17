"""用户画像端点（profile-contract）：简历上传 / 画像查询 / 草稿保存。"""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.profile import ProfileOut, ProfileUpdate
from app.schemas.task import TaskTriggerResult
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("/resume", response_model=ApiResponse[TaskTriggerResult])
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ProfileService(db).upload_resume(current_user, file))


@router.get("", response_model=ApiResponse[ProfileOut])
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ProfileService(db).get_profile(current_user))


@router.put("", response_model=ApiResponse[ProfileOut])
async def update_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ApiResponse(data=await ProfileService(db).save_profile(current_user, payload))
