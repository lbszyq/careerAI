"""FastAPI 公共依赖：当前用户解析。"""
import uuid

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ErrorCode
from app.core.security import decode_token
from app.db.base import get_db
from app.models import User
from app.repositories.user_repository import UserRepository


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Bearer token 鉴权依赖：无效/过期 → 1001/1003；未找到用户 → 1001。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(ErrorCode.UNAUTHORIZED, "未登录或缺少 Authorization 头", 401)
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token, expected_type="access")
    user_id = uuid.UUID(payload["sub"])
    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise ApiError(ErrorCode.UNAUTHORIZED, "用户不存在或已被删除", 401)
    return user