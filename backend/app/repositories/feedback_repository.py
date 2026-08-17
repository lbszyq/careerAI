"""achievements / reassessments 数据访问（归属经 growth_plans → career_reports 校验，C-007）。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import PlanAchievement, Reassessment
from app.repositories.base import BaseRepository


class AchievementRepository(BaseRepository):
    async def list_by_plan(self, plan_id: uuid.UUID) -> list[PlanAchievement]:
        stmt = (
            select(PlanAchievement)
            .where(PlanAchievement.plan_id == plan_id)
            .order_by(PlanAchievement.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, plan_id: uuid.UUID, achievement_id: uuid.UUID) -> PlanAchievement | None:
        stmt = select(PlanAchievement).where(
            PlanAchievement.id == achievement_id, PlanAchievement.plan_id == plan_id
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def create(
        self,
        plan_id: uuid.UUID,
        name: str,
        url: str,
        description: str | None,
        stage: str | None,
        task_id: uuid.UUID | None,
    ) -> PlanAchievement:
        row = PlanAchievement(plan_id=plan_id, name=name, url=url,
                              description=description, stage=stage, task_id=task_id)
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, achievement: PlanAchievement) -> None:
        await self.session.delete(achievement)
        await self.session.flush()

    async def exists_for_plan(self, plan_id: uuid.UUID) -> bool:
        stmt = select(PlanAchievement.id).where(PlanAchievement.plan_id == plan_id).limit(1)
        return (await self.session.execute(stmt)).first() is not None


class ReassessmentRepository(BaseRepository):
    async def create_succeeded(
        self, plan_id: uuid.UUID, task_id: uuid.UUID | None, summary: str, result: dict
    ) -> Reassessment:
        """重评记录仅在任务成功时落库（决策③）。"""
        row = Reassessment(plan_id=plan_id, task_id=task_id, status="succeeded",
                           decision="undecided", summary=summary, result=result)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_by_plan(self, plan_id: uuid.UUID) -> list[Reassessment]:
        stmt = (
            select(Reassessment)
            .where(Reassessment.plan_id == plan_id)
            .order_by(Reassessment.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, plan_id: uuid.UUID, reassess_id: uuid.UUID) -> Reassessment | None:
        stmt = select(Reassessment).where(
            Reassessment.id == reassess_id, Reassessment.plan_id == plan_id
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_task_id(self, task_id: uuid.UUID) -> Reassessment | None:
        stmt = select(Reassessment).where(Reassessment.task_id == task_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def decide(self, rec: Reassessment, decision: str) -> None:
        rec.decision = decision
        rec.decided_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def latest_succeeded(self, plan_id: uuid.UUID) -> Reassessment | None:
        """最近一次成功重评（按创建时间倒序），用于 completion_check 动态读取。"""
        stmt = (
            select(Reassessment)
            .where(Reassessment.plan_id == plan_id, Reassessment.status == "succeeded")
            .order_by(Reassessment.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
