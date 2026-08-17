"""market_data 数据访问（公开数据，无用户外键；季度入库，B-001/）。"""
import uuid

from sqlalchemy import case, func, select

from app.models import MarketData
from app.repositories.base import BaseRepository

SORT_CLAUSES = {
    "salary_p50_desc": MarketData.salary_p50.desc().nulls_last(),
    "salary_p50_asc": MarketData.salary_p50.asc().nulls_last(),
    # 热度 高>中>低 排序（中文枚举映射数值）
    "heat_desc": case(
        (MarketData.heat == "高", 3),
        (MarketData.heat == "中", 2),
        (MarketData.heat == "低", 1),
        else_=0,
    ).desc(),
    "default": MarketData.updated_at.desc(),
}


class MarketRepository(BaseRepository):
    def _build_filter(self, cities: list[str], industries: list[str], job_title: str | None):
        conds = []
        if cities:
            conds.append(MarketData.city.in_(cities))
        if industries:
            conds.append(MarketData.industry.in_(industries))
        if job_title:
            conds.append(MarketData.job_title.ilike(f"%{job_title}%"))
        return conds

    async def list_jobs(
        self,
        cities: list[str],
        industries: list[str],
        job_title: str | None,
        sort: str,
        page: int,
        page_size: int,
    ) -> tuple[int, list[MarketData], str | None]:
        conds = self._build_filter(cities, industries, job_title)
        base = select(MarketData).where(*conds) if conds else select(MarketData)
        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        quarter = None
        if conds:
            quarter = (
                await self.session.execute(
                    select(func.max(MarketData.data_quarter)).where(*conds)
                )
            ).scalar_one_or_none()
        order = SORT_CLAUSES.get(sort, SORT_CLAUSES["default"])
        stmt = (
            base.order_by(order, MarketData.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return int(total), list(rows), quarter

    async def get_job(self, job_id: uuid.UUID) -> MarketData | None:
        return await self.session.get(MarketData, job_id)

    async def facets(self) -> tuple[list[str], list[str], list[str]]:
        cities = (
            await self.session.execute(
                select(MarketData.city).distinct().order_by(MarketData.city.asc())
            )
        ).scalars().all()
        industries = (
            await self.session.execute(
                select(MarketData.industry).distinct().order_by(MarketData.industry.asc())
            )
        ).scalars().all()
        quarters = (
            await self.session.execute(
                select(MarketData.data_quarter)
                .distinct()
                .order_by(MarketData.data_quarter.desc())
                .where(MarketData.data_quarter.is_not(None))
            )
        ).scalars().all()
        return list(cities), list(industries), list(quarters)
