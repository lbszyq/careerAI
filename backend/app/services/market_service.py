"""market 业务编排（公开访问；数据为空返回空列表而非错误）。"""
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ErrorCode
from app.repositories.market_repository import MarketRepository
from app.schemas.market import (
    MarketFacetsOut,
    MarketJobDetailOut,
    MarketJobOut,
    MarketListOut,
)
from app.services.error_codes import MarketErrorCode

VALID_SORTS = {"salary_p50_desc", "salary_p50_asc", "heat_desc", "default"}
_QUARTER_RE = re.compile(r"^(?P<year>\d{4})[Qq](?P<quarter>[1-4])$")
_CN_ORDINAL = {"1": "一", "2": "二", "3": "三", "4": "四"}


class MarketService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MarketRepository(session)

    async def list_jobs(
        self,
        city: str | None,
        industry: str | None,
        job_title: str | None,
        page: int,
        page_size: int,
        sort: str,
    ) -> MarketListOut:
        cities = _parse_multi(city, "城市")
        industries = _parse_multi(industry, "行业")
        if sort not in VALID_SORTS:
            raise ApiError(MarketErrorCode.MARKET_FILTER_INVALID, f"sort 参数非法：{sort}", 400)
        total, rows, quarter = await self.repo.list_jobs(
            cities, industries, job_title, sort, page, page_size
        )
        return MarketListOut(
            total=total,
            page=page,
            page_size=page_size,
            data_quarter=quarter,
            lag_note=_lag_note(quarter),
            items=[_to_job_out(row) for row in rows],
        )

    async def get_job(self, job_id: uuid.UUID) -> MarketJobDetailOut:
        row = await self.repo.get_job(job_id)
        if row is None:
            raise ApiError(MarketErrorCode.JOB_NOT_FOUND, "岗位不存在", 404)
        return MarketJobDetailOut(
            id=row.id,
            job_title=row.job_title,
            city=row.city,
            industry=row.industry,
            salary=_salary_dict(row),
            trend=row.trend,
            heat=row.heat,
            required_skills=list(row.required_skills or []),
            data_source=row.data_source,
            data_quarter=row.data_quarter,
            confidence=_num(row.confidence),
            updated_at=row.updated_at,
        )

    async def facets(self) -> MarketFacetsOut:
        cities, industries, quarters = await self.repo.facets()
        return MarketFacetsOut(cities=cities, industries=industries, quarters=quarters)


def _parse_multi(raw: str | None, label: str) -> list[str]:
    """逗号分隔多值（≤5，market-contract 3401）。"""
    if not raw:
        return []
    values = [v.strip() for v in raw.split(",") if v.strip()]
    if len(values) > 5:
        raise ApiError(MarketErrorCode.MARKET_FILTER_INVALID, f"{label}参数不合法：最多 5 个", 400)
    return values


def _lag_note(quarter: str | None) -> str:
    if not quarter:
        return "暂无可用数据"
    m = _QUARTER_RE.match(quarter)
    if m:
        return (
            f"数据为 {m.group('year')} 年第{_CN_ORDINAL.get(m.group('quarter'), m.group('quarter'))}"
            f"季度官方发布，滞后约 1.5 个月"
        )
    return f"数据为 {quarter} 官方发布，滞后约 1.5 个月"


def _salary_dict(row) -> dict | None:
    if row.salary_p50 is None:
        return None
    return {"p25": _num(row.salary_p25), "p50": _num(row.salary_p50), "p75": _num(row.salary_p75)}


def _to_job_out(row) -> MarketJobOut:
    return MarketJobOut(
        id=row.id,
        job_title=row.job_title,
        city=row.city,
        industry=row.industry,
        salary=_salary_dict(row),
        trend=row.trend,
        heat=row.heat,
        data_source=row.data_source,
        confidence=_num(row.confidence),
    )


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
