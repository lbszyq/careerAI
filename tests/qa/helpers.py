"""QA 轻量 helper（自包含，避免依赖 backend/tests/helpers.py 的包结构）。"""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
from app.core.config import get_settings


def make_user(**overrides) -> SimpleNamespace:
    """构造满足 UserOut 读取的最小用户对象。"""
    defaults = {
        "id": uuid.uuid4(),
        "username": "tester",
        "phone": None,
        "role": "user",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_token(sub, token_type: str = "access", *, expired: bool = False) -> str:
    """按生产配置签发 JWT；expired=True 时签发已过期 token。"""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(sub),
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(hours=-1 if expired else 1),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)