"""JWT 签发/校验 + bcrypt 密码哈希（PyJWT + bcrypt，CR-001/ 定案）。"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: uuid.UUID | str) -> str:
    return _create_token(str(user_id), "access", timedelta(minutes=get_settings().ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(user_id: uuid.UUID | str) -> str:
    return _create_token(str(user_id), "refresh", timedelta(days=get_settings().REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str | None = None) -> dict:
    """校验 JWT；过期抛 TOKEN_EXPIRED(1003)，非法抛 UNAUTHORIZED(1001)。"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(ErrorCode.TOKEN_EXPIRED, "token 已过期", 401) from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError(ErrorCode.UNAUTHORIZED, "无效的 token", 401) from exc
    if expected_type and payload.get("type") != expected_type:
        raise ApiError(ErrorCode.UNAUTHORIZED, "token 类型不匹配", 401)
    return payload