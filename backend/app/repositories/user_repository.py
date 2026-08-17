"""users 表数据访问。"""
import uuid

from sqlalchemy import func, select

from app.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        # auth-contract：用户名不区分大小写唯一（QA-BUG-001）→ lower() 匹配，兼容历史大小写混合存量
        result = await self.session.execute(
            select(User).where(func.lower(User.username) == username.lower())
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        result = await self.session.execute(select(User).where(User.phone == phone))
        return result.scalar_one_or_none()

    async def get_by_account(self, account: str) -> User | None:
        """登录用：账号可为用户名（不区分大小写）或手机号（原值匹配）。"""
        result = await self.session.execute(
            select(User).where(
                (func.lower(User.username) == account.lower()) | (User.phone == account)
            )
        )
        return result.scalar_one_or_none()

    async def create(self, username: str, password_hash: str, phone: str | None = None) -> User:
        user = User(username=username, password_hash=password_hash, phone=phone)
        self.session.add(user)
        await self.session.flush()
        return user