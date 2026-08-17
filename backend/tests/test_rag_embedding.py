"""：bge-m3 进程级单例缓存测试。

- get_embedding_provider() 进程内复用同一实例（修复每任务/每查询重载 2GB 权重）
- 测试/DEBUG 环境仍返回 FakeEmbeddingProvider；生产返回 BgeM3EmbeddingProvider
- RAG 降级路径（sentence-transformers 不可用 → is_available()=False → 空结果）保留
"""
import asyncio
from unittest import mock
from unittest.mock import AsyncMock

import app.ai.rag.embedding as embedding_module
from app.ai.rag import retriever
from app.ai.rag.embedding import (
    BgeM3EmbeddingProvider,
    FakeEmbeddingProvider,
    get_embedding_provider,
)


class _EmptySession:
    """空表会话：execute 返回空结果（无 embedding 行 → 检索为空）。"""

    async def execute(self, stmt, params=None):
        class Result:
            def __iter__(self):
                return iter(())

        return Result()


async def _no_columns(session, table):
    return {"id", "job_title", "city", "industry"}


def test_get_embedding_provider_returns_same_instance():
    """标准 1：同一进程多次调用返回同一实例（避免 bge-m3 权重重复加载）。"""
    first = get_embedding_provider()
    second = get_embedding_provider()
    assert first is second


def test_get_embedding_provider_returns_fake_in_testing():
    """标准 3：TESTING 环境仍返回 FakeEmbeddingProvider。"""
    provider = get_embedding_provider()
    assert isinstance(provider, FakeEmbeddingProvider)


def test_search_market_without_provider_reuses_singleton():
    """标准 2：search_market 不传 provider 连续 3 次仅获取到 1 个实例。"""
    created = []
    orig = retriever.get_embedding_provider

    def counting_wrapper():
        provider = orig()
        created.append(provider)
        return provider

    with (
        mock.patch.object(retriever, "_table_columns", _no_columns),
        mock.patch.object(retriever, "get_embedding_provider", counting_wrapper),
    ):
            for _ in range(3):
                asyncio.run(retriever.search_market(_EmptySession(), "数据分析"))

    assert len(created) == 3, "3 次 search_market 均应触发 provider 获取"
    assert len({id(p) for p in created}) == 1, "3 次调用应复用同一 provider 实例"


def test_search_market_bge_m3_unavailable_degrades_to_empty():
    """标准 4：sentence-transformers 不可用 → 降级为空结果（不崩溃、不调 encode）。"""
    with mock.patch.dict("sys.modules", {"sentence_transformers": None}):
        provider = BgeM3EmbeddingProvider(model_name="BAAI/bge-m3")
        assert provider.is_available() is False
        hits = asyncio.run(retriever.search_market(AsyncMock(), "数据分析", provider=provider))
    assert hits == []


def test_get_embedding_provider_returns_fake_when_debug(monkeypatch):
    """标准 3：DEBUG 环境分支不受单例影响，仍返回 FakeEmbeddingProvider。"""
    from types import SimpleNamespace

    get_embedding_provider.cache_clear()
    fake_settings = SimpleNamespace(TESTING=False, DEBUG=True)
    monkeypatch.setattr(embedding_module, "get_settings", lambda: fake_settings)
    try:
        provider = get_embedding_provider()
        assert isinstance(provider, FakeEmbeddingProvider)
    finally:
        get_embedding_provider.cache_clear()
