"""数据库引擎与会话（SQLAlchemy 2.0 async + asyncpg）。"""
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

# 测试环境（pytest）与 Celery worker（每任务 asyncio.run 新建 event loop）下连接池
# 跨 event loop 复用会死连接（QA-BUG-003），故用 NullPool；WORKER_MODE 由 workers.py 在
# 首次导入执行器（创建 engine）前设置
worker_mode = os.getenv("WORKER_MODE", "false").lower() in ("true", "1")
poolclass = (
    NullPool
    if os.getenv("TESTING", "false").lower() == "true" or worker_mode
    else None
)

engine = create_async_engine(get_settings().DATABASE_URL, echo=False, pool_pre_ping=True, poolclass=poolclass)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI 依赖：请求级数据库会话。"""
    async with AsyncSessionLocal() as session:
        yield session
