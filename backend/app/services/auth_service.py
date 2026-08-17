"""认证业务编排：注册 / 登录 / 刷新 token（Controller 只做参数校验，业务在此）。"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError, AuthErrorCode, ErrorCode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginResult, RegisterResult, TokenPair, UserOut


def _to_token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        token_type="bearer",
        expires_in=get_settings().ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        phone=user.phone,
        role=user.role,
        created_at=user.created_at,
    )


class AuthService:
    def __init__(self, session: AsyncSession):
        self.user_repo = UserRepository(session)

    async def register(
        self, username: str, phone: str | None, password: str
    ) -> RegisterResult:
        # auth-contract：用户名不区分大小写唯一（QA-BUG-001）→ 统一小写存储，查询侧 lower() 匹配
        username = username.lower()
        if await self.user_repo.get_by_username(username) is not None:
            raise ApiError(AuthErrorCode.USERNAME_TAKEN, "用户名已存在", 409)
        if phone:
            existing = await self.user_repo.get_by_phone(phone)
            if existing is not None:
                raise ApiError(AuthErrorCode.PHONE_TAKEN, "手机号已被注册", 409)
        user = await self.user_repo.create(
            username=username, phone=phone, password_hash=hash_password(password)
        )
        # 注册成功即视为已登录：直接签发 token（前端「点击生成报告前」流程需要）
        return RegisterResult(user=_to_user_out(user), tokens=_to_token_pair(user))

    async def login(self, account: str, password: str) -> LoginResult:
        user = await self.user_repo.get_by_account(account)
        # 统一返回 1001，不区分「用户不存在」与「密码错误」，防账号枚举
        if user is None or not verify_password(password, user.password_hash):
            raise ApiError(ErrorCode.UNAUTHORIZED, "用户名或密码错误", 401)
        return LoginResult(user=_to_user_out(user), tokens=_to_token_pair(user))

    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, expected_type="refresh")
        user_id = uuid.UUID(payload["sub"])
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise ApiError(AuthErrorCode.USER_NOT_FOUND, "用户不存在", 401)
        return _to_token_pair(user)

    async def me(self, user: User) -> UserOut:
        return _to_user_out(user)