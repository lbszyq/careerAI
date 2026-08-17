"""Repository 基类：所有数据库访问必须经过 Repository 层。"""
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session