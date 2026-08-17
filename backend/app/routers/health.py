"""/health 健康检查（含 DB / Redis 连通性）。"""
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.base import get_db
from app.schemas.common import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict])
async def health(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    db_status = "ok"
    redis_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
    except Exception:
        redis_status = "error"
    return ApiResponse(
        data={
            "status": "ok" if db_status == "ok" and redis_status == "ok" else "degraded",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "database": db_status,
            "redis": redis_status,
        }
    )