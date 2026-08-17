"""career_reports / career_directions / gap_analyses 数据访问（C-007 数据隔离按 user_id 过滤）。"""
import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.models import CareerDirection, CareerReport, GapAnalysis, GrowthPlan, TaskJob
from app.repositories.base import BaseRepository


def _today_start_shanghai() -> datetime:
    """当日 0 点（Asia/Shanghai，报告生成日配额口径）。"""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return datetime.combine(now.date(), time.min, tzinfo=ZoneInfo("Asia/Shanghai"))


class ReportRepository(BaseRepository):
    async def get_owned(self, report_id: uuid.UUID, user_id: uuid.UUID) -> CareerReport | None:
        stmt = select(CareerReport).where(
            CareerReport.id == report_id, CareerReport.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_by_user(
        self, user_id: uuid.UUID, page: int, page_size: int
    ) -> tuple[int, list[CareerReport]]:
        """当前用户全部报告（：含 pending/running/completed/failed，created_at 倒序；历次报告不可删除，C-005）。

        生成中记录载体是 task_jobs（career_reports 仅在任务成功时落库，决策③），
        由 list_processing_report_jobs 补充合并（见 ReportService.list_reports）。
        """
        base = select(CareerReport).where(CareerReport.user_id == user_id)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = (
            base.order_by(CareerReport.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return int(total), list(rows)

    async def list_processing_report_jobs(self, user_id: uuid.UUID) -> list[TaskJob]:
        """进行中的报告类任务（pending/running）——列表生成中条目的数据源（/Q3）。

        仅报告生成链路任务参与列表：report_stage1 / report_stage2 / plan_regenerate。
        task_jobs.status 进行中枚举即 pending/running（与 一致）。
        """
        stmt = (
            select(TaskJob)
            .where(
                TaskJob.user_id == user_id,
                TaskJob.task_type.in_(("report_stage1", "report_stage2", "plan_regenerate")),
                TaskJob.status.in_(("pending", "running")),
            )
            .order_by(TaskJob.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_completed_today(self, user_id: uuid.UUID) -> int:
        """当日成功生成的报告数（AI_DAILY_REPORT_LIMIT 配额口径，3202）。"""
        stmt = select(func.count()).select_from(CareerReport).where(
            CareerReport.user_id == user_id,
            CareerReport.status == "completed",
            CareerReport.created_at >= _today_start_shanghai(),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_directions(self, report_id: uuid.UUID) -> list[CareerDirection]:
        stmt = (
            select(CareerDirection)
            .where(CareerDirection.report_id == report_id)
            .order_by(CareerDirection.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_directions_by_report_ids(self, report_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[CareerDirection]]:
        if not report_ids:
            return {}
        stmt = (
            select(CareerDirection)
            .where(CareerDirection.report_id.in_(report_ids))
            .order_by(CareerDirection.created_at.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        grouped: dict[uuid.UUID, list[CareerDirection]] = {}
        for row in rows:
            grouped.setdefault(row.report_id, []).append(row)
        return grouped

    async def get_target_jobs_by_report_ids(self, report_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """批量查询报告的目标岗位（gap_analyses.target_job，用户 Stage2 实际所选）。

        Stage2 成功落库时每报告一条 gap（persistence.save_stage2_result），created_at asc 取首条；
        无 gap 报告不在返回 dict 中，由调用方兜底为 null。
        """
        if not report_ids:
            return {}
        stmt = (
            select(GapAnalysis)
            .where(GapAnalysis.report_id.in_(report_ids))
            .order_by(GapAnalysis.created_at.asc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        grouped: dict[uuid.UUID, str] = {}
        for row in rows:
            grouped.setdefault(row.report_id, row.target_job)
        return grouped

    async def get_direction(self, report_id: uuid.UUID, direction_id: uuid.UUID) -> CareerDirection | None:
        stmt = select(CareerDirection).where(
            CareerDirection.id == direction_id, CareerDirection.report_id == report_id
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def has_gap_analysis(self, report_id: uuid.UUID) -> bool:
        stmt = select(GapAnalysis.id).where(GapAnalysis.report_id == report_id)
        return (await self.session.execute(stmt.limit(1))).first() is not None

    async def get_plan_by_report_id(self, report_id: uuid.UUID) -> GrowthPlan | None:
        """QA-BUG-018：报告详情的 plan 摘要注入计划记录 id（growth_plans 按 report_id 查）。"""
        stmt = select(GrowthPlan).where(GrowthPlan.report_id == report_id)
        return (await self.session.execute(stmt)).scalars().first()
