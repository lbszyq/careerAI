"""边界/异常/性能抽查（QA，只读）。

- 边界：空向量库、空报告 direction、空简历
- 异常：LLM 失败兜底、RAG DB 不可用降级
- 性能：search_market 不传 provider 时复用进程级单例 provider（修复）
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.rag import retriever
from app.ai.rag.embedding import FakeEmbeddingProvider
from app.core.errors import ApiError
from app.services.report_service import ReportService

# ---------- 边界 ----------


def test_search_market_empty_vector_db_returns_empty():
    """空向量库（无 embedding 行）→ 返回空列表（调用方标注「数据较少」）。"""
    class EmptySession:
        async def execute(self, stmt, params=None):
            class Result:
                def __iter__(self):
                    return iter(())
            return Result()

    async def _table_columns(session, table):
        return {"id", "job_title", "city", "industry"}

    retriever._table_columns = _table_columns
    hits = asyncio.run(retriever.search_market(EmptySession(), "数据分析", provider=FakeEmbeddingProvider()))
    assert hits == []


def test_search_market_provider_unavailable_returns_empty():
    """Embedding provider 不可用 → RAG 降级为空（不抛错）。"""
    class NoProvider:
        dim = 1024
        def is_available(self):
            return False
        def encode(self, texts):
            raise AssertionError("不可用 provider 不应被调用")

    hits = asyncio.run(retriever.search_market(AsyncMock(), "数据分析", provider=NoProvider()))
    assert hits == []


def test_search_market_db_failure_returns_empty():
    """DB 访问失败 → RAG 降级为空（异常路径，不 500）。"""
    class BrokenSession:
        async def execute(self, stmt, params=None):
            raise RuntimeError("db down")

    async def _table_columns(session, table):
        raise RuntimeError("table missing")

    retriever._table_columns = _table_columns
    hits = asyncio.run(retriever.search_market(BrokenSession(), "数据分析", provider=FakeEmbeddingProvider()))
    assert hits == []


def test_create_gap_analysis_missing_direction_3204():
    """边界：缺少 direction_id → 3204 DIRECTION_REQUIRED。"""
    user = SimpleNamespace(id=uuid.uuid4())
    svc = ReportService(AsyncMock())
    with pytest.raises(ApiError) as ei:
        asyncio.run(svc.create_gap_analysis(user, uuid.uuid4(), SimpleNamespace(direction_id=None)))
    assert ei.value.code == 3204
    assert ei.value.http_status == 400


# ---------- 异常 ----------


def test_router_llm_failure_falls_back_to_rules():
    """LLM 不可用/失败 → 规则解析兜底（router_node 异常路径）。"""
    from app.ai.agents.router import _parse_resume

    profile = asyncio.run(_parse_resume("姓名：张三\n学历：本科\n专业：计算机\n毕业年份：2026", llm=None))
    assert profile["generated_by"] == "rule_template"
    assert profile["name"] == "张三"
    assert profile["major"] == "计算机"


def test_router_llm_error_falls_back_to_rules():
    """LLM 抛错 → 规则解析兜底，不崩溃。"""
    from app.ai.agents.router import _parse_resume
    from app.ai.llm.exceptions import LLMError

    class BrokenLLM:
        is_available = True
        async def complete_json(self, **kwargs):
            raise LLMError("boom")

    profile = asyncio.run(_parse_resume("张三 本科 计算机 2026", llm=BrokenLLM()))
    assert profile["generated_by"] == "rule_template"


# ---------- 性能：bge-m3 重载路径确认（报告项） ----------


def test_search_market_without_provider_reuses_singleton_provider():
    """性能路径确认（修复）：search_market 不传 provider 时复用进程级单例。

    生产环境 BgeM3EmbeddingProvider 的模型缓存是实例级（self._model），
    修复前新建实例 = 重新加载 bge-m3 权重（约 2GB / 20s 量级，实测）。
     后 get_embedding_provider 为进程级单例（@lru_cache(maxsize=1)），
    即使新调用方漏传 provider，也只会加载一次模型。
    """
    created = []

    class EmptySession:
        async def execute(self, stmt, params=None):
            class Result:
                def __iter__(self):
                    return iter(())

            return Result()

    async def _table_columns(session, table):
        return {"id", "job_title", "city", "industry"}

    orig = retriever.get_embedding_provider

    def counting_wrapper():
        provider = orig()
        created.append(provider)
        return provider

    retriever._table_columns = _table_columns
    retriever.get_embedding_provider = counting_wrapper
    try:
        for _ in range(3):
            asyncio.run(retriever.search_market(EmptySession(), "数据分析"))
    finally:
        retriever.get_embedding_provider = orig

    assert len(created) == 3, f"3 次 search_market 均应触发 provider 获取，实际 {len(created)}"
    assert len({id(p) for p in created}) == 1, (
        f"期望复用进程级单例（1 实例），实际 {len({id(p) for p in created})} 个实例"
    )
    print(f"[QA] 3 次 search_market 调用 → {len({id(p) for p in created})} 个 provider 实例（单例复用）")

def test_build_market_context_creates_provider_once():
    """build_market_context 内部循环复用同一 provider（非逐查询新建）。"""
    created = []

    class CountingProvider:
        dim = 1024
        def __init__(self):
            created.append(self)
        def is_available(self):
            return True
        def encode(self, texts):
            return [[0.1] * 1024]

    class EmptySession:
        async def execute(self, stmt, params=None):
            class Result:
                def __iter__(self):
                    return iter(())
            return Result()

    async def _table_columns(session, table):
        return {"id", "job_title", "city", "industry"}

    retriever._table_columns = _table_columns
    retriever.get_embedding_provider = lambda: CountingProvider()

    asyncio.run(retriever.build_market_context(EmptySession(), ["数据分析", "前端开发", "产品经理"]))
    assert len(created) == 1


def test_create_report_incomplete_profile_3203():
    """边界：画像信息不完整（空报告前置）→ 3203 REPORT_PROFILE_INCOMPLETE。"""
    from types import SimpleNamespace as NS

    user = NS(id=uuid.uuid4())
    req = NS(profile_id=uuid.uuid4(), preferred_cities=[], preferred_industries=[])

    EmptyProfile = SimpleNamespace(
        name=None, education=None, major=None, graduation_year=None,
        internships=[], projects=[],
    )

    class FakeRepo:
        async def get_by_id_and_user(self, profile_id, user_id):
            return EmptyProfile

    svc = ReportService(AsyncMock())
    svc.profile_repo = FakeRepo()
    with pytest.raises(ApiError) as ei:
        asyncio.run(svc.create_report(user, req))
    assert ei.value.code == 3203
    assert ei.value.http_status == 400
