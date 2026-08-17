"""/health 健康检查测试（DB/Redis 全部 mock，不依赖 Docker）。"""
from unittest.mock import AsyncMock

from app.routers import health as health_module


def _redis_ok(monkeypatch) -> AsyncMock:
    """from_url 返回 AsyncMock：ping/aclose 均为异步 mock。"""
    redis_mock = AsyncMock()
    monkeypatch.setattr(health_module.aioredis, "from_url", lambda *args, **kwargs: redis_mock)
    return redis_mock


def test_health_ok(client, fake_db, monkeypatch):
    _redis_ok(monkeypatch)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"
    assert body["data"]["database"] == "ok"
    assert body["data"]["redis"] == "ok"


def test_health_degraded_when_db_and_redis_down(client, fake_db, monkeypatch):
    fake_db.execute.side_effect = Exception("db down")
    redis_mock = AsyncMock()
    redis_mock.ping.side_effect = Exception("redis down")
    monkeypatch.setattr(health_module.aioredis, "from_url", lambda *args, **kwargs: redis_mock)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "degraded"
    assert body["data"]["database"] == "error"
    assert body["data"]["redis"] == "error"
