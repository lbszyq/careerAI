"""market_data 批量向量化入库脚本逻辑（向量化：每条记录为一块，季度增量）。"""
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embedding import EmbeddingProvider, get_embedding_provider
from app.models.market import MarketData

logger = logging.getLogger("careerai.ai.rag")


def build_record_text(row: MarketData, *, data_quarter: str | None = None) -> str:
    """每条岗位记录合并为一条文本（：不跨记录分块）。"""
    skills = "、".join(row.required_skills or []) or "暂无"
    parts = [
        f"岗位：{row.job_title}",
        f"城市：{row.city}",
        f"行业：{row.industry}",
        f"薪资P25/P50/P75：{row.salary_p25}/{row.salary_p50}/{row.salary_p75}",
        f"趋势：{row.trend or '未知'}",
        f"热度：{row.heat or '未知'}",
        f"技能要求：{skills}",
        f"来源：{row.data_source or '未知'}",
    ]
    if data_quarter:
        parts.append(f"数据季度：{data_quarter}")
    return "；".join(parts)


async def sync_market_embeddings(
    session: AsyncSession,
    *,
    provider: EmbeddingProvider | None = None,
    force: bool = False,
) -> int:
    """为缺失 embedding（或 force=True 全部）的 market_data 行生成并写回向量。

    返回更新的行数；embedding provider 不可用时返回 0（不报错，由调用方决定是否降级）。
    """
    provider = provider or get_embedding_provider()
    if not provider.is_available():
        logger.warning("vectorize: embedding provider 不可用，跳过")
        return 0
    try:
        columns = await _table_columns(session)
    except Exception: # noqa: BLE001
        return 0

    stmt = select(MarketData)
    if not force:
        stmt = stmt.where(MarketData.embedding.is_(None))
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return 0

    data_quarter_map: dict[str, str] = {}
    if "data_quarter" in columns:
        q = await session.execute(
            text("SELECT id::text, data_quarter FROM market_data WHERE id = ANY(:ids)"),
            {"ids": [str(r.id) for r in rows]},
        )
        data_quarter_map = {r[0]: r[1] for r in q if r[1]}

    texts = [
        build_record_text(r, data_quarter=data_quarter_map.get(str(r.id))) for r in rows
    ]
    vectors = provider.encode(texts)
    updated = 0
    for row, vec in zip(rows, vectors):
        row.embedding = vec
        updated += 1
    await session.flush()
    logger.info("vectorize: updated %d rows", updated)
    return updated


async def _table_columns(session: AsyncSession) -> set[str]:
    from sqlalchemy import text as _text

    stmt = _text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'market_data'"
    )
    rows = await session.execute(stmt)
    return {r[0] for r in rows}
