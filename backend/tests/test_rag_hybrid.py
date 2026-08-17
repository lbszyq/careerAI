"""RAG 混合检索测试：关键词精确匹配 + 向量语义 RRF 融合。
：新增 Rerank 重排（候选池放大 / 排序 / 降级×3 / 边界）+ 关键词层级细化（precision）。
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

import app.ai.rag.retriever as retriever
from app.ai.rag.retriever import (
    MarketHit,
    _apply_rerank,
    _fuse_rrf,
    _keyword_ratio,
    _keyword_search,
    _normalize_text,
    _search_market_impl,
)


def _hit(hit_id: str, job_title: str, similarity: float) -> MarketHit:
    return MarketHit(
        id=hit_id, city="北京", industry="互联网", job_title=job_title,
        salary_p25=None, salary_p50=10000, salary_p75=None, trend=None, heat="中",
        required_skills=[], data_source="legacy-jd", confidence=None,
        data_quarter=None, city_tier=None, similarity=similarity, source_type="job_post",
    )


def _row(hit_id: str, job_title: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=hit_id, city="北京", industry="互联网", job_title=job_title,
        salary_p25=None, salary_p50=10000, salary_p75=None, trend=None, heat="中",
        required_skills=[], data_source="legacy-jd", confidence=None,
        data_quarter=None, city_tier=None, source_type="job_post",
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt, params=None):
        return _FakeResult(self._rows)


def test_normalize_text():
    assert _normalize_text("Java 开发工程师") == "java开发工程师"
    assert _normalize_text("UI 设计师") == "ui设计师"
    assert _normalize_text("后端开发（岗位）") == "后端开发岗位"


def test_keyword_ratio_exact_and_fuzzy():
    # 精确子串
    assert _keyword_ratio(_normalize_text("产品经理的薪资"), _normalize_text("产品经理")) == 1.0
    # 模糊（前缀/根）：后端开发 → 后端开发工程师
    assert _keyword_ratio(_normalize_text("后端开发岗位薪资"), _normalize_text("后端开发工程师")) >= 0.4
    # 无关：会计 vs 后端开发
    assert _keyword_ratio(_normalize_text("后端开发"), _normalize_text("会计")) == 0.0


async def test_keyword_search_recalls_exact_job_title_below_vector_threshold():
    """关键词检索不经过 0.7 阈值：精确岗位名即使向量 <0.7 也能召回。"""
    session = _FakeSession([_row("1", "Java开发工程师"), _row("2", "后端开发工程师")])
    cols = ["id", "city", "industry", "job_title", "salary_p25", "salary_p50", "salary_p75",
            "trend", "heat", "required_skills", "data_source", "confidence"]
    hits = await _keyword_search(session, "Java开发工程师", cols, top_k=10)
    assert hits, "关键词检索应召回精确岗位名"
    assert hits[0].job_title == "Java开发工程师", f"应优先召回精确岗位名：{[h.job_title for h in hits]}"
    assert hits[0].similarity == 1.0


def test_fuse_rrf_keyword_first_and_dedup():
    kw = _hit("kw", "Java开发工程师", 1.0)
    vec_same = _hit("kw", "Java开发工程师", 0.689) # 与关键词同 id（向量 <0.7）
    vec_other = _hit("v2", "后端开发工程师", 0.75)
    fused = _fuse_rrf([vec_same, vec_other], [kw], top_k=10)
    ids = [h.id for h in fused]
    assert ids[0] == "kw", f"关键词命中应排最前：{ids}"
    assert "v2" in ids
    assert len(ids) == len(set(ids)), "同 id 应去重"


async def test_search_market_impl_fuses_keyword_and_vector(monkeypatch):
    """混合检索端到端：向量命中 + 关键词命中 RRF 融合。"""
    cols = set(
        ["id", "city", "industry", "job_title", "salary_p25", "salary_p50", "salary_p75",
         "trend", "heat", "required_skills", "data_source", "confidence",
         "data_quarter", "city_tier", "source_type"]
    )
    monkeypatch.setattr(retriever, "_table_columns", AsyncMock(return_value=cols))
    monkeypatch.setattr(retriever, "_keyword_search", AsyncMock(return_value=[_hit("kw", "Java开发工程师", 1.0)]))
    monkeypatch.setattr(retriever, "_vector_search", AsyncMock(return_value=[_hit("v", "后端开发工程师", 0.75)]))

    class FakeProvider:
        def is_available(self):
            return True

    hits = await _search_market_impl(
        AsyncMock(), "Java开发工程师", top_k=10, threshold=0.7, provider=FakeProvider()
    )
    assert len(hits) == 2
    assert hits[0].job_title == "Java开发工程师", f"关键词命中应排最前：{[h.job_title for h in hits]}"
# ---------------------------------------------------------------------------
# Rerank 重排（reranker.py + retriever._apply_rerank）
# ---------------------------------------------------------------------------
class _ScriptedReranker:
    """测试用可控 reranker：注入打分/可用性/异常/延迟，模拟本地与云端行为。"""

    def __init__(self, scores=None, available=True, exc=None, delay=0.0):
        self._scores = scores
        self._available = available
        self._exc = exc
        self._delay = delay

    def is_available(self):
        return self._available

    def scores(self, query, docs):
        if self._delay:
            time.sleep(self._delay)
        if self._exc:
            raise self._exc
        if self._scores is not None:
            return list(self._scores)
        # 默认：按 doc 与 query 的字符重叠打分（确定性）
        qs = set(query)
        return [round(len(qs & set(d)) / max(len(qs), 1), 4) for d in docs]


def _rerank_hits(n: int, prefix: str = "岗位") -> list[MarketHit]:
    return [_hit(f"h{i}", f"{prefix}{i}", 0.9 - i / 100.0) for i in range(1, n + 1)]


def _cfg(**overrides) -> SimpleNamespace:
    base = dict(
        RERANK_ENABLED=True,
        RERANK_TIMEOUT_SECONDS=5.0,
        RERANK_CANDIDATE_POOL=40,
        RAG_TOP_K=10,
        RAG_SIMILARITY_THRESHOLD=0.7,
        RAG_MAX_CONTEXT_CHARS=6000,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


async def test_apply_rerank_promotes_outside_topk(monkeypatch):
    """P0 前置：候选池 >10 时，Rerank 可将原本 Top-10 外的候选排入 Top-10。"""
    hits = _rerank_hits(12)
    # RRF 序：h1~h10 在 Top-10；h11/h12 在池外。Rerank 打分 h12 最高 → 应排入 Top-10（Top1）
    scores = [0.5] * 11 + [0.99]
    monkeypatch.setattr(retriever, "get_reranker", lambda: _ScriptedReranker(scores=scores))
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())
    out = await _apply_rerank("测试岗位", hits, top_k=10)
    assert len(out) == 10
    assert out[0].id == "h12", f"原本 Top-10 外的候选应被 Rerank 排入 Top-10：{[h.id for h in out]}"
    assert "h12" in {h.id for h in out}
    assert "h11" not in {h.id for h in out} or "h1" not in {h.id for h in out}


async def test_apply_rerank_flips_top1(monkeypatch):
    """两个候选 Rerank 打分翻转后 Top1 变化（重排顺序生效）。"""
    hits = [_hit("a", "前端开发工程师", 0.9), _hit("b", "后端开发工程师", 0.8)]
    # RRF 序 a 在前；Rerank 打分 b > a → Top1 变为 b
    monkeypatch.setattr(retriever, "get_reranker", lambda: _ScriptedReranker(scores=[0.2, 0.9]))
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())
    out = await _apply_rerank("后端开发岗位", hits, top_k=10)
    assert out[0].id == "b", f"Rerank 应翻转 Top1：{[h.id for h in out]}"


async def test_apply_rerank_disabled_keeps_rrf_order(monkeypatch):
    """RERANK_ENABLED=false：直接返回 RRF 原序前 top_k，不调用 reranker。"""
    hits = _rerank_hits(12)
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg(RERANK_ENABLED=False))
    out = await _apply_rerank("测试", hits, top_k=10)
    assert [h.id for h in out] == [h.id for h in hits[:10]]


# ---- 降级：reranker 不可用/初始化失败/超时/云端 HTTP 错误 → RRF 原序，检索不失败 ----
async def _assert_degraded(out: list[MarketHit], hits: list[MarketHit], top_k: int = 10):
    """降级断言：命中集合与 RERANK_ENABLED=false 时完全一致（原 RRF 序前 top_k）。"""
    assert [h.id for h in out] == [h.id for h in hits[:top_k]], "降级应保持 RRF 原序命中集合"


async def test_apply_rerank_degrade_unavailable(monkeypatch):
    """①a：reranker 不可用（is_available=False）→ 降级 RRF 原序，不抛异常。"""
    hits = _rerank_hits(12)
    monkeypatch.setattr(retriever, "get_reranker", lambda: _ScriptedReranker(available=False))
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())
    out = await _apply_rerank("测试", hits, top_k=10)
    await _assert_degraded(out, hits)


async def test_apply_rerank_degrade_init_failure(monkeypatch):
    """①b：reranker 初始化失败（get_reranker 抛异常/权重缺失）→ 降级 RRF 原序。"""
    hits = _rerank_hits(12)

    def _boom():
        raise RuntimeError("reranker 权重缺失")

    monkeypatch.setattr(retriever, "get_reranker", _boom)
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())
    out = await _apply_rerank("测试", hits, top_k=10)
    await _assert_degraded(out, hits)


async def test_apply_rerank_degrade_timeout(monkeypatch):
    """②：rerank 推理超时（>RERANK_TIMEOUT_SECONDS 预算）→ 降级 RRF 原序，不抛异常。"""
    hits = _rerank_hits(12)
    monkeypatch.setattr(retriever, "get_reranker", lambda: _ScriptedReranker(delay=0.3))
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg(RERANK_TIMEOUT_SECONDS=0.05))
    out = await _apply_rerank("测试", hits, top_k=10)
    await _assert_degraded(out, hits)


async def test_apply_rerank_degrade_http_error(monkeypatch):
    """③：云端 rerank HTTP 错误（429）→ 降级 RRF 原序，不抛异常。"""
    hits = _rerank_hits(12)

    class _HttpErr:
        def is_available(self):
            return True

        def scores(self, query, docs):
            raise httpx.HTTPStatusError(
                "429 Too Many Requests",
                request=httpx.Request("POST", "https://rerank.example/v1"),
                response=httpx.Response(429, request=httpx.Request("POST", "https://rerank.example/v1")),
            )

    monkeypatch.setattr(retriever, "get_reranker", lambda: _HttpErr())
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())
    out = await _apply_rerank("测试", hits, top_k=10)
    await _assert_degraded(out, hits)


async def test_apply_rerank_degrade_score_mismatch(monkeypatch):
    """打分数量与候选不符（异常响应）→ 降级 RRF 原序。"""
    hits = _rerank_hits(12)
    monkeypatch.setattr(retriever, "get_reranker", lambda: _ScriptedReranker(scores=[0.9]))
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())
    out = await _apply_rerank("测试", hits, top_k=10)
    await _assert_degraded(out, hits)


# ---- 边界：空 query / 超长 query / 空候选 / 单候选 / 命中集合与字段不增减 ----
async def test_apply_rerank_edge_cases(monkeypatch):
    """：空 query / 超长 query / 空候选 / 单候选均不崩溃且保持命中集合。"""
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())
    monkeypatch.setattr(retriever, "get_reranker", lambda: _ScriptedReranker())

    # 空 query
    out = await _apply_rerank("", _rerank_hits(12), top_k=10)
    assert len(out) == 10
    # 超长 query
    long_q = "岗位" * 5000
    out = await _apply_rerank(long_q, _rerank_hits(12), top_k=10)
    assert len(out) == 10
    # 空候选
    out = await _apply_rerank("测试", [], top_k=10)
    assert out == []
    # 单候选（无需重排）
    single = [_hit("s1", "唯一岗位", 0.9)]
    out = await _apply_rerank("测试", single, top_k=10)
    assert [h.id for h in out] == ["s1"]


async def test_apply_rerank_preserves_hit_fields(monkeypatch):
    """命中集合与字段不因重排而增减：重排只改顺序，MarketHit 字段原样保留。"""
    hits = _rerank_hits(12)
    monkeypatch.setattr(retriever, "get_reranker", lambda: _ScriptedReranker(scores=[0.99, 0.1, 0.95, 0.2, 0.9, 0.3, 0.85, 0.4, 0.8, 0.5, 0.75, 0.6]))
    monkeypatch.setattr(retriever, "get_settings", lambda: _cfg())
    before_ids = {h.id for h in hits}
    before_fields = {(h.id, h.job_title, h.similarity) for h in hits}
    out = await _apply_rerank("测试", hits, top_k=10)
    assert len(out) == 10
    assert {h.id for h in out} <= before_ids, "重排不新增候选"
    for h in out:
        assert (h.id, h.job_title, h.similarity) in before_fields, "重排不改变候选字段"


# ---------------------------------------------------------------------------
# 关键词匹配层级细化（「开发工程师」家族 precision）
# ---------------------------------------------------------------------------
def test_keyword_ratio_hierarchy_shared_root_rejected():
    """「开发工程师」家族同根岗位：query「前端开发工程师」不命中「后端开发工程师」。"""
    assert _keyword_ratio(_normalize_text("前端开发工程师"), _normalize_text("后端开发工程师")) == 0.0, "共享根后缀（开发工程师）+ 方向词不同（前端/后端）→ 拒绝"
    assert _keyword_ratio(_normalize_text("前端开发工程师"), _normalize_text("前端开发工程师")) == 1.0, "精确完整岗位名 → 1.0"
    assert _keyword_ratio(_normalize_text("前端开发"), _normalize_text("前端开发工程师")) == 0.9, "query 是岗位名前缀 → 0.9"
    assert _keyword_ratio(_normalize_text("Java开发"), _normalize_text("Java开发工程师")) == 0.9, "query 是岗位名子串 → 0.9"
    assert _keyword_ratio(_normalize_text("产品经理的薪资"), _normalize_text("产品经理")) == 1.0, "query 包含完整岗位名 → 1.0"


def test_keyword_ratio_shared_root_with_same_direction_ok():
    """共享根但方向一致（query 无方向词/方向词相同）仍命中。"""
    assert _keyword_ratio(_normalize_text("开发工程师"), _normalize_text("后端开发工程师")) >= 0.4, "query 是岗位名子串 → 0.9"
    assert _keyword_ratio(_normalize_text("后端开发工程师的薪资"), _normalize_text("后端开发工程师")) == 1.0


def test_config_has_rerank_settings():
    """验证标准 1：RERANK_ENABLED / RERANK_MODEL 存在于 config.py。"""
    from app.core.config import Settings
    s = Settings()
    assert hasattr(s, "RERANK_ENABLED") and isinstance(s.RERANK_ENABLED, bool)
    assert hasattr(s, "RERANK_MODEL") and isinstance(s.RERANK_MODEL, str)
    assert hasattr(s, "RERANK_CANDIDATE_POOL") and s.RERANK_CANDIDATE_POOL > 10
    assert hasattr(s, "RERANK_TIMEOUT_SECONDS") and s.RERANK_TIMEOUT_SECONDS <= 5.0
