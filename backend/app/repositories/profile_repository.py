"""user_profiles 表数据访问（C-001 单活跃档案，upsert 语义）。"""
import uuid

from sqlalchemy import select

from app.models import UserProfile
from app.repositories.base import BaseRepository


class ProfileRepository(BaseRepository):
    async def get_active(self, user_id: uuid.UUID) -> UserProfile | None:
        """最近一次保存/解析的活跃画像（profile-contract：未填写返回 None）。"""
        stmt = (
            select(UserProfile)
            .where(UserProfile.user_id == user_id, UserProfile.is_active.is_(True))
            .order_by(UserProfile.updated_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_id_and_user(self, profile_id: uuid.UUID, user_id: uuid.UUID) -> UserProfile | None:
        stmt = select(UserProfile).where(
            UserProfile.id == profile_id,
            UserProfile.user_id == user_id,
            UserProfile.is_active.is_(True),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def upsert(self, user_id: uuid.UUID, data: dict) -> UserProfile:
        """upsert 活跃画像：有则覆盖，无则新建（不新增多档案，C-001）。"""
        existing = await self.get_active(user_id)
        if existing is not None:
            for key, value in data.items():
                setattr(existing, key, value)
            await self.session.flush()
            return existing
        row = UserProfile(user_id=user_id, **data)
        self.session.add(row)
        await self.session.flush()
        return row
