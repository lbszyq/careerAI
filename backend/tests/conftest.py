"""pytest 共享 fixture：mock 隔离 DB/Redis/LLM，不依赖 Docker/外部服务。"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 必须在导入 app 前设置：db.base 据此选 NullPool 池策略，config.TESTING 供 Fake embedding 判定
os.environ.setdefault("TESTING", "true")
# 测试专用 JWT 密钥（≥32 字节，消除 InsecureKeyLengthWarning；环境已有则沿用）
os.environ.setdefault("JWT_SECRET", "tc002-test-only-secret-" + "x" * 20)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.base import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def fake_db() -> AsyncMock:
    """不连真实数据库的 AsyncSession mock（execute/add/flush 均为异步 mock）。"""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def client(fake_db):
    """TestClient：get_db 依赖替换为 fake_db，所有 DB 访问走 mock。"""
    app.dependency_overrides[get_db] = lambda: fake_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
