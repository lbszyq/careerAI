"""认证端点：注册 / 登录 / 刷新 / 当前用户（）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    LoginResult,
    RefreshRequest,
    RegisterRequest,
    RegisterResult,
    TokenPair,
    UserOut,
)
from app.schemas.common import ApiResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse[RegisterResult])
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await AuthService(db).register(req.username, req.phone, req.password)
    await db.commit()
    return ApiResponse(data=result)


@router.post("/login", response_model=ApiResponse[LoginResult])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    return ApiResponse(data=await AuthService(db).login(req.account, req.password))


@router.post("/refresh", response_model=ApiResponse[TokenPair])
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    return ApiResponse(data=await AuthService(db).refresh(req.refresh_token))


@router.get("/me", response_model=ApiResponse[UserOut])
async def me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return ApiResponse(data=await AuthService(db).me(current_user))