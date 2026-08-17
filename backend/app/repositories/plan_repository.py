"""growth_plans / plan_tasks / gap_analyses 数据访问（归属经 career_reports 校验，C-007）。"""
import uuid

from sqlalchemy import func, select

from app.models import CareerReport, GapAnalysis, GrowthPlan, PlanTask
from app.repositories.base import BaseRepository


class PlanRepository(BaseRepository):
    async def get_owned(self, plan_id: uuid.UUID, user_id: uuid.UUID) -> GrowthPlan | None:
        """计划详情：growth_plans join career_reports 校验归属（计划表无 user_id）。"""
        stmt = (
            select(GrowthPlan)
            .join(CareerReport, CareerReport.id == GrowthPlan.report_id)
            .where(GrowthPlan.id == plan_id, CareerReport.user_id == user_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_with_owner(self, plan_id: uuid.UUID) -> tuple[GrowthPlan, uuid.UUID] | None:
        """返回 (计划, 归属用户 id)；用于反馈端点区分「计划不存在(4104)」与「非本人(403)」。"""
        stmt = (
            select(GrowthPlan, CareerReport.user_id)
            .join(CareerReport, CareerReport.id == GrowthPlan.report_id)
            .where(GrowthPlan.id == plan_id)
        )
        row = (await self.session.execute(stmt)).first()
        return (row[0], row[1]) if row is not None else None

    async def get_tasks(self, plan_id: uuid.UUID) -> list[PlanTask]:
        stmt = (
            select(PlanTask)
            .where(PlanTask.plan_id == plan_id)
            .order_by(PlanTask.sort_order.asc(), PlanTask.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_task(self, plan_id: uuid.UUID, task_id: uuid.UUID) -> PlanTask | None:
        stmt = select(PlanTask).where(PlanTask.id == task_id, PlanTask.plan_id == plan_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def add_task(self, plan_id: uuid.UUID, name: str, stage: str | None, sort_order: int) -> PlanTask:
        from app.models import PlanTask as _PlanTask

        row = _PlanTask(plan_id=plan_id, name=name, stage=stage, status="todo", sort_order=sort_order)
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete_task(self, task: PlanTask) -> None:
        await self.session.delete(task)
        await self.session.flush()

    async def max_sort_order(self, plan_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(PlanTask.sort_order), 0)).where(PlanTask.plan_id == plan_id)
        return int((await self.session.execute(stmt)).scalar())

    async def update_task_status(self, task: PlanTask, status: str) -> None:
        task.status = status
        await self.session.flush()

    async def recalc_progress(self, plan_id: uuid.UUID) -> int:
        """progress = round(done_tasks / total_tasks × 100)，同步回写 growth_plans.progress。"""
        stmt = (
            select(func.count(), func.count().filter(PlanTask.status == "done"))
            .select_from(PlanTask)
            .where(PlanTask.plan_id == plan_id)
        )
        total, done = (await self.session.execute(stmt)).one()
        progress = round((int(done) / int(total)) * 100) if int(total) > 0 else 0
        plan = await self.session.get(GrowthPlan, plan_id)
        if plan is not None:
            plan.progress = progress
            await self.session.flush()
        return progress

    async def get_gap_target_job(self, gap_analysis_id: uuid.UUID | None) -> str | None:
        if gap_analysis_id is None:
            return None
        row = await self.session.get(GapAnalysis, gap_analysis_id)
        return row.target_job if row is not None else None
