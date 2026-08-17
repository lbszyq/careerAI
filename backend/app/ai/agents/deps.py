"""Agent 运行上下文（依赖注入：DB 会话 / LLM / Embedding / 进度回调）。

节点函数签名统一为 (state, deps)；LangGraph 通过 functools.partial 绑定 deps。
"""
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import LLMClient
from app.ai.rag.embedding import EmbeddingProvider


@dataclass
class AgentDeps:
    db: AsyncSession | None = None # 当前 DB 会话（常模查询等；RAG 检索见 rag_session_factory）
    llm: LLMClient | None = None # LLMClient；is_available=False 时节点走规则兜底
    embedding: EmbeddingProvider | None = None # 向量化提供方
    on_progress: Callable[[int, str], Awaitable[None]] | None = None # 节点边界进度上报（）
    rag_session_factory: Callable[[], AsyncSession] | None = None # RAG 只读会话工厂（：独立会话避免并行节点共享冲突）
    trace_id: str | None = None # 任务级 trace_id；运行时主路径经 contextvars 传播
    parent_span_id: str | None = None # 父 span id（task root span；/）
