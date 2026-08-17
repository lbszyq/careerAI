"""QA 抽查共享 fixture（只读，不修改业务代码）。

与 backend/tests/conftest.py 同模式：mock 隔离 DB/Redis/LLM。
本目录为 独立 QA 抽查集，自包含（不依赖 backend/tests 内部 fixture）。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 强制 QA 环境标记：Fake embedding 判定 + NullPool（不覆盖外部真实环境变量内容）
os.environ["TESTING"] = "true"
os.environ.setdefault("JWT_SECRET", "tc008-qa-test-only-secret-" + "x" * 20)

import pytest
from app.db.base import get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession


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