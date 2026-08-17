"""市场数据 RAG 检索（architecture.md）。

链路：查询向量化 → pgvector 余弦相似（<=>）→ Top-K=10、相似度阈值 ≥0.7
→ 上下文组装（含 data_source/confidence/data_quarter）→ Prompt 注入。

兼容性：data_quarter / city_tier 由 增量迁移提供；表结构未就绪时自动降级
（可选列探测），保证当前 schema 下可运行、迁移落地后完整生效。
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

from pgvector.sqlalchemy import Vector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.ai.rag.embedding import EmbeddingProvider, get_embedding_provider
from app.ai.rag.reranker import get_reranker
from app.observability.tracer import record_rag_span

logger = logging.getLogger("careerai.ai.rag")

_BASE_COLUMNS = [
    "id", "city", "industry", "job_title",
    "salary_p25", "salary_p50", "salary_p75",
    "trend", "heat", "required_skills", "data_source", "confidence",
]
_OPTIONAL_COLUMNS = ["data_quarter", "city_tier", "source_type", "education_requirement", "responsibilities"]

_DATA_GRADE_MAP = {
    "official_stat": "A", # 官方统计（劳科院简报、人社部工资价位、高校就业质量年报等）
    "job_post": "B", # 公开招聘数据（智联 38 城报告、招聘网站公开 JD 聚合等）
    "ai_infer": "C", # AI 推断（RAG 无命中时的 LLM 推断/估计）
}

_DATA_GRADE_NAMES = {"A": "官方统计", "B": "公开招聘数据", "C": "AI 推断"}


def data_grade_for_source_type(source_type: str | None) -> str | None:
    """来源类型 → data_grade（A/B/C）。market-contract v1.1 派生规则：

    等级由数据入库时的 source_type 映射派生，Agent 禁止自判；未知/缺失 → None。
    """
    if not source_type:
        return None
    return _DATA_GRADE_MAP.get(source_type)


def data_grade_name(grade: str | None) -> str | None:
    """data_grade → 中文等级名（置信度原因文案用）；未知 → None。"""
    return _DATA_GRADE_NAMES.get(grade) if grade else None


@dataclass
class MarketHit:
    """单条检索命中（含来源标注，要求）。"""
    id: str
    city: str
    industry: str
    job_title: str
    salary_p25: float | None
    salary_p50: float | None
    salary_p75: float | None
    trend: str | None
    heat: str | None
    required_skills: list
    data_source: str | None
    confidence: float | None
    data_quarter: str | None
    city_tier: str | None
    similarity: float
    education_requirement: str | None = None # 学历要求（下沉列；迁移未落地/缺失 → None）
    responsibilities: list = field(default_factory=list) # 职责字符串数组（下沉列）
    source_type: str | None = None # 来源类型（official_stat/job_post/ai_infer，入库时写入；无则 None）

    @property
    def data_grade(self) -> str | None:
        """来源等级（只读派生，禁止自判）：source_type 缺失/未知 → None。"""
        return data_grade_for_source_type(self.source_type)

    @property
    def salary_note(self) -> str:
        parts = []
        if self.data_quarter:
            parts.append(str(self.data_quarter))
        if self.data_source:
            parts.append(str(self.data_source))
        if self.confidence is not None:
            parts.append(f"置信度{float(self.confidence):.0%}")
        return "，".join(parts) if parts else "暂无来源"

    def to_context_block(self) -> str:
        salary = " / ".join(
            f"{name}={getattr(self, key)}" for key, name in
            (("salary_p25", "P25"), ("salary_p50", "P50"), ("salary_p75", "P75"))
            if getattr(self, key) is not None
        ) or "暂无薪资数据"
        skills = "、".join(self.required_skills or []) or "暂无技能要求"
        education = self.education_requirement or "暂无学历要求"
        responsibilities = "、".join(self.responsibilities or []) or "暂无职责说明"
        grade = self.data_grade
        grade_text = f" | 来源等级：{grade}" if grade else ""
        return (
            f"[岗位]{self.job_title} | [城市]{self.city} | [行业]{self.industry}\n"
            f"薪资(元/月)：{salary} | 趋势：{self.trend or '未知'} | 热度：{self.heat or '未知'}\n"
            f"技能要求：{skills} | 学历要求：{education}\n"
            f"职责：{responsibilities}\n来源：{self.salary_note}{grade_text}"
        )


async def _table_columns(session: AsyncSession, table: str) -> set[str]:
    """探测表当前实际存在的列（迁移未落地时自动降级）。"""
    stmt = text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = :t"
    )
    rows = await session.execute(stmt, {"t": table})
    return {r[0] for r in rows}


# ---- 混合检索：关键词精确匹配 + 向量语义融合 ----
# ---- 关键词匹配层级细化（precision 优化）：精确完整岗位名 > 子串 > 前缀 > LCS 覆盖率 ----

# 关键词命中判定：归一化后「岗位名与 query 的最长公共子串」覆盖岗位名比例下限。
# 岗位名「根」（如后端开发/数据分析/Java开发）在 query 中出现即命中，而非要求完整岗位名。
_KEYWORD_MIN_RATIO = 0.4
# 共享根后缀拒绝：「前端/后端开发工程师」共享「开发工程师」后缀但方向词不同。
# 当 LCS 恰为公共后缀且长度 ≥ 该阈值、两侧前缀（方向词）不同 → 判 0，消除 遗留误召回。
_KEYWORD_MIN_SHARED_ROOT = 3


def _normalize_text(text: str) -> str:
    """归一化：只保留字母数字，转小写（用于岗位名与 query 的关键词匹配，去空白/标点）。"""
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _longest_common_substring_len(a: str, b: str) -> int:
    """最长公共子串长度（DP 滚动数组，用于岗位名与 query 的模糊匹配）。"""
    m, n = len(a), len(b)
    if not m or not n:
        return 0
    prev = [0] * (n + 1)
    best = 0
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _common_suffix_len(a: str, b: str) -> int:
    """公共后缀长度（用于检测「共享岗位根后缀」，如 前端/后端开发工程师 的「开发工程师」）。"""
    n = 0
    for x, y in zip(reversed(a), reversed(b)):
        if x != y:
            break
        n += 1
    return n


def _keyword_ratio(q_norm: str, jt_norm: str) -> float:
    """岗位名与 query 的关键词匹配度（层级细化）：

    1. 精确完整岗位名（q == jt）→ 1.0；
    2. query 包含完整岗位名（如「产品经理的薪资」→「产品经理」）→ 1.0；
    3. query 是岗位名子串/前缀（如「Java 开发」→「Java开发工程师」）→ 0.9；
    4. LCS 覆盖率（0~1），但「共享根后缀冲突」判 0：
       LCS 恰为 query 与岗位名的公共后缀（如「开发工程师」）且两侧前缀（方向词）不同
       → 拒绝（「前端开发工程师」不命中「后端开发工程师」）。
    """
    if not q_norm or not jt_norm:
        return 0.0
    if jt_norm == q_norm:
        return 1.0
    if jt_norm in q_norm:
        return 1.0
    if q_norm in jt_norm:
        return 0.9
    lcs = _longest_common_substring_len(q_norm, jt_norm)
    if lcs == 0:
        return 0.0
    suffix = _common_suffix_len(q_norm, jt_norm)
    if (
        suffix == lcs
        and suffix >= _KEYWORD_MIN_SHARED_ROOT
        and lcs < len(q_norm)
        and lcs < len(jt_norm)
    ):
        # 共享根后缀 + 两侧均有额外前缀（方向词不同，如 前端 vs 后端）→ 拒绝
        return 0.0
    return lcs / len(jt_norm) if lcs / len(jt_norm) >= _KEYWORD_MIN_RATIO else 0.0


def _row_to_hit(row, similarity: float) -> MarketHit:
    """SQL 行 → MarketHit（向量/关键词检索共用，避免两处重复构造）。"""
    return MarketHit(
        id=str(row.id),
        city=row.city or "",
        industry=row.industry or "",
        job_title=row.job_title or "",
        salary_p25=_to_float(row.salary_p25),
        salary_p50=_to_float(row.salary_p50),
        salary_p75=_to_float(row.salary_p75),
        trend=row.trend,
        heat=row.heat,
        required_skills=list(row.required_skills or []),
        data_source=row.data_source,
        confidence=_to_float(row.confidence),
        data_quarter=getattr(row, "data_quarter", None),
        city_tier=getattr(row, "city_tier", None),
        source_type=getattr(row, "source_type", None),
        education_requirement=getattr(row, "education_requirement", None),
        responsibilities=list(getattr(row, "responsibilities", None) or []),
        similarity=round(similarity, 4),
    )


async def _keyword_search(
    session: AsyncSession, query: str, select_cols: list[str], top_k: int
) -> list[MarketHit]:
    """关键词检索：job_title 精确/子串/前缀匹配，召回纯向量检索漏掉的岗位名。

    数据量小（~335 条）可全表扫；仅匹配 job_title，不把城市/行业等字段当关键词误召回。
    """
    col_sql = ", ".join(select_cols)
    stmt = text(f"SELECT {col_sql} FROM market_data WHERE embedding IS NOT NULL")
    try:
        rows = await session.execute(stmt)
    except Exception as exc: # noqa: BLE001 表/列未就绪降级
        logger.warning("rag: 关键词检索失败降级为空: %s", type(exc).__name__)
        return []
    q_norm = _normalize_text(query)
    if not q_norm:
        return []
    matches: list[tuple[float, object]] = [] # (ratio, row)
    for row in rows:
        jt_norm = _normalize_text(str(row.job_title or ""))
        ratio = _keyword_ratio(q_norm, jt_norm)
        if ratio >= _KEYWORD_MIN_RATIO:
            matches.append((ratio, row))
    # 按匹配度降序（最高匹配度=最可能目标岗位名优先，避免「开发工程师」家族误命中抢占排序）
    matches.sort(key=lambda x: x[0], reverse=True)
    return [_row_to_hit(row, 1.0) for _, row in matches[:top_k]]


async def _vector_search(
    session: AsyncSession,
    query: str,
    select_cols: list[str],
    top_k: int,
    threshold: float,
    provider: EmbeddingProvider,
) -> list[MarketHit]:
    """向量检索（pgvector 余弦相似 + 阈值，拆出以便与关键词融合）。"""
    vectors = provider.encode([query])
    query_vec = vectors[0]
    col_sql = ", ".join(select_cols)
    # asyncpg 对 text() 的元组绑定无效：向量以字符串字面量 + CAST 绑定
    vec_sql = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"
    stmt = text(
        f"SELECT {col_sql}, 1 - (embedding <=> CAST(:q AS vector)) AS similarity "
        "FROM market_data WHERE embedding IS NOT NULL "
        "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :top_k"
    )
    try:
        rows = await session.execute(stmt, {"q": vec_sql, "top_k": top_k})
    except Exception as exc: # noqa: BLE001 列/向量索引缺失时降级
        logger.warning("rag: 向量检索失败降级为空: %s", type(exc).__name__)
        return []
    hits: list[MarketHit] = []
    for row in rows:
        similarity = float(row.similarity) if row.similarity is not None else 0.0
        if similarity < threshold:
            continue
        hits.append(_row_to_hit(row, similarity))
    return hits


def _fuse_rrf(
    vector_hits: list[MarketHit], keyword_hits: list[MarketHit], top_k: int
) -> list[MarketHit]:
    """RRF 融合：score = Σ 1/(k+rank)，关键词精确命中优先、向量语义命中补位，去重。

    ：top_k 在此处传候选池大小（RERANK_CANDIDATE_POOL，默认 40），
    候选池放大是 Rerank 能提升 recall@10 的数学前提（Rerank 只改顺序、不改候选集合）。
    """
    rrf_k = 60
    scores: dict[str, float] = {}
    by_id: dict[str, MarketHit] = {}
    for rank, hit in enumerate(keyword_hits):
        scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (rrf_k + rank + 1)
        by_id.setdefault(hit.id, hit)
    for rank, hit in enumerate(vector_hits):
        scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (rrf_k + rank + 1)
        by_id.setdefault(hit.id, hit)
    ordered = sorted(by_id.keys(), key=lambda hid: scores[hid], reverse=True)
    return [by_id[hid] for hid in ordered[:top_k]]


async def _apply_rerank(
    query: str, hits: list[MarketHit], top_k: int
) -> list[MarketHit]:
    """Rerank 重排：候选池内按交叉编码器相关度重新排序后截断 Top-K。

    - 可选增强：RERANK_ENABLED=false / reranker 不可用 / 超时 / 异常 → 降级返回原序前 top_k
      （命中集合与字段不变，检索链路契约不变）；
    - 重排只改变候选内部顺序，不改变候选集合（候选池放大见 _search_market_impl）。
    """
    s = get_settings()
    if not s.RERANK_ENABLED:
        return hits[:top_k]
    try:
        reranker = get_reranker()
    except Exception as exc: # noqa: BLE001 初始化失败降级
        logger.warning("rag: reranker 初始化失败，降级 RRF 原序: %s", type(exc).__name__)
        return hits[:top_k]
    if not reranker.is_available():
        logger.warning("rag: reranker 不可用，降级 RRF 原序")
        return hits[:top_k]
    docs = [hit.job_title for hit in hits]
    try:
        scores = await asyncio.wait_for(
            asyncio.to_thread(reranker.scores, query, docs),
            timeout=s.RERANK_TIMEOUT_SECONDS,
        )
    except Exception as exc: # noqa: BLE001 超时/云端 HTTP 错误等降级
        logger.warning("rag: rerank 调用失败/超时（≤%ss），降级 RRF 原序: %s",
                       s.RERANK_TIMEOUT_SECONDS, type(exc).__name__)
        return hits[:top_k]
    if len(scores) != len(hits):
        logger.warning("rag: rerank 打分数量不匹配，降级 RRF 原序")
        return hits[:top_k]
    ranked = sorted(zip(hits, scores), key=lambda x: x[1], reverse=True)
    return [hit for hit, _ in ranked[:top_k]]


async def search_market(
    session: AsyncSession,
    query: str,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
    provider: EmbeddingProvider | None = None,
) -> list[MarketHit]:
    """向量检索 market_data（Top-K 与相似度阈值见 ，默认 10 / 0.7）。

    RAG 无结果时返回空列表（调用方按 标注「该领域暂时数据较少」）。
    每次检索写一条 rag span（hit_count / duration_ms）。
    """
    started = time.monotonic()
    try:
        hits = await _search_market_impl(
            session, query, top_k=top_k, threshold=threshold, provider=provider
        )
        await record_rag_span(
            name="search_market",
            status="succeeded",
            duration_ms=int((time.monotonic() - started) * 1000),
            hit_count=len(hits),
        )
        return hits
    except Exception as exc: # noqa: BLE001 理论上 impl 已内部降级，此处兜底
        await record_rag_span(
            name="search_market",
            status="failed",
            duration_ms=int((time.monotonic() - started) * 1000),
            hit_count=0,
            error_message=str(exc),
        )
        raise


async def _search_market_impl(
    session: AsyncSession,
    query: str,
    *,
    top_k: int | None = None,
    threshold: float | None = None,
    provider: EmbeddingProvider | None = None,
) -> list[MarketHit]:
    """混合检索：关键词精确匹配 + 向量语义 RRF 融合。

    - 关键词检索命中不经过 0.7 阈值（精确岗位名不再被误过滤）；
    - 向量语义命中补位；两者 RRF 融合去重后统一截断 Top-K。
    """
    s = get_settings()
    top_k = top_k or s.RAG_TOP_K
    threshold = threshold if threshold is not None else s.RAG_SIMILARITY_THRESHOLD
    # 候选池放大（/ P0 前置）：Rerank 只重排候选内部顺序、不改变候选集合，
    # 若候选池维持 top_k，recall@10 数学上不可能提升。故 Rerank 开启时 RRF 融合取
    # RERANK_CANDIDATE_POOL（默认 40）→ Rerank 重排 → 截断 top_k。
    pool_size = s.RERANK_CANDIDATE_POOL if s.RERANK_ENABLED else top_k

    try:
        columns = await _table_columns(session, "market_data")
    except Exception: # noqa: BLE001 表不存在等
        logger.warning("rag: market_data 表不可访问，检索降级为空")
        return []
    select_cols = [c for c in _BASE_COLUMNS if c in columns] + [
        c for c in _OPTIONAL_COLUMNS if c in columns
    ]
    if "id" not in select_cols or "job_title" not in select_cols:
        return []

    # 1. 关键词检索（不依赖 embedding，独立召回精确岗位名，；候选池放大到 pool_size）
    keyword_hits = await _keyword_search(session, query, select_cols, pool_size)

    # 2. 向量检索（需要 embedding provider；候选池放大到 pool_size）
    vector_hits: list[MarketHit] = []
    provider = provider or get_embedding_provider()
    if provider.is_available():
        vector_hits = await _vector_search(session, query, select_cols, pool_size, threshold, provider)
    else:
        logger.warning("rag: embedding provider 不可用，向量检索降级为空（关键词检索仍生效）")

    # 3. RRF 融合（去重，候选池 = pool_size）
    fused = _fuse_rrf(vector_hits, keyword_hits, pool_size)

    # 4. Rerank 重排（可选增强，失败降级 RRF 原序）→ 截断 Top-K
    return await _apply_rerank(query, fused, top_k)


async def build_market_context(
    session: AsyncSession,
    queries: list[str],
    *,
    provider: EmbeddingProvider | None = None,
) -> str:
    """多查询检索 + 去重 + 组装上下文（截断到 RAG_MAX_CONTEXT_CHARS 控制 Token 预算）。"""
    s = get_settings()
    provider = provider or get_embedding_provider()
    seen: set[str] = set()
    blocks: list[str] = []
    for query in queries:
        hits = await search_market(session, query, provider=provider)
        for hit in hits:
            if hit.id in seen:
                continue
            seen.add(hit.id)
            blocks.append(hit.to_context_block())
        if sum(len(b) for b in blocks) >= s.RAG_MAX_CONTEXT_CHARS:
            break
    context = "\n\n".join(blocks)
    if len(context) > s.RAG_MAX_CONTEXT_CHARS:
        context = context[: s.RAG_MAX_CONTEXT_CHARS]
    return context


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
