"""任务级 Trace 上下文与 span 写入（architecture.md）。

设计要点：
- contextvars 承载跨节点/跨函数 trace 上下文（trace_id + parent_span_id），
  asyncio 任务级隔离；禁止全局可变状态（并发多任务靠 contextvars 隔离）。
- span 写入走独立 session/事务 + try/except 吞异常：失败仅记日志，不影响主业务成功路径。
- error_message 截断 ≤500 + 脱敏（sk- / Bearer / api_key= 等密钥形态），不含密钥。
- trace_id 缺失（span 写入时无上下文）时：task span 新建独立 root span；llm/rag/agent
  span 无上下文则跳过（查询返回空），不报错、不覆盖历史。
"""
import contextvars
import logging
import re
import uuid

from app.db.base import AsyncSessionLocal
from app.models.trace_span import TraceSpan

logger = logging.getLogger("careerai.observability")

MAX_ERROR_LENGTH = 500

_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
_parent_span_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("parent_span_id", default=None)


def get_trace_id() -> str | None:
    """当前协程上下文的 trace_id；无则 None。"""
    return _trace_id_var.get()


def get_parent_span_id() -> str | None:
    """当前协程上下文的父 span id；无则 None。"""
    return _parent_span_id_var.get()


def set_trace_context(trace_id: str | None, parent_span_id: str | None = None) -> tuple:
    """进入一段 trace 上下文，返回 (trace_token, parent_token) 供 reset_trace_context 还原。"""
    return _trace_id_var.set(trace_id), _parent_span_id_var.set(parent_span_id)


def reset_trace_context(tokens: tuple) -> None:
    """还原 set_trace_context 前的上下文。"""
    _trace_id_var.reset(tokens[0])
    _parent_span_id_var.reset(tokens[1])


def sanitize_error(message: str | None) -> str | None:
    """error_message 处理：截断 ≤500 + 脱敏（不含密钥）。None 原样返回。"""
    if message is None:
        return None
    text = _redact_secrets(str(message))
    return text[:MAX_ERROR_LENGTH]


_SECRET_KEYS = r"(?:api[_-]?key|apikey|secret|token|password|authorization|access_token|refresh_token)"


def _redact_secrets(text: str) -> str:
    """脱敏常见密钥形态：OpenAI sk-、Bearer token、key=value / JSON 引号形态。"""
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", text, flags=re.IGNORECASE)
    text = re.sub(r"Bearer\s+\S+", "Bearer ***", text, flags=re.IGNORECASE)
    # key=value 形态（api_key=xxx / api_key: xxx）
    text = re.sub(rf"({_SECRET_KEYS}\s*[=:]\s*)\S+", r"\1***", text, flags=re.IGNORECASE)
    # JSON 引号形态（"api_key":"xxx"）
    text = re.sub(rf'(\"{_SECRET_KEYS}\"\s*:\s*\")\S*?(\")', r"\1***\2", text, flags=re.IGNORECASE)
    return text


async def write_span(
    *,
    trace_id: str,
    parent_span_id: str | None,
    span_type: str,
    name: str,
    status: str = "succeeded",
    duration_ms: int = 0,
    tokens: int = 0,
    cost: float = 0.0,
    hit_count: int = 0,
    error_message: str | None = None,
) -> TraceSpan | None:
    """写入一个新 span（独立 session/事务 + 吞异常）。失败返回 None，不影响主业务。"""
    try:
        async with AsyncSessionLocal() as session:
            span = TraceSpan(
                trace_id=uuid.UUID(trace_id),
                parent_span_id=uuid.UUID(parent_span_id) if parent_span_id else None,
                span_type=span_type,
                name=name,
                status=status,
                error_message=sanitize_error(error_message),
                duration_ms=duration_ms,
                tokens=tokens,
                cost=cost,
                hit_count=hit_count,
            )
            session.add(span)
            await session.commit()
            return span
    except Exception: # noqa: BLE001 span 写入失败只记日志，不影响主业务
        logger.exception(
            "observability: span 写入失败 trace=%s type=%s name=%s", trace_id, span_type, name
        )
        return None


async def finish_span(
    span_id: str | None,
    *,
    status: str,
    duration_ms: int = 0,
    error_message: str | None = None,
    tokens: int = 0,
    cost: float = 0.0,
    hit_count: int = 0,
) -> None:
    """更新 span 终态（running → succeeded/failed），独立 session/事务 + 吞异常。

    幂等：已处终态（succeeded/failed）不再覆盖，避免并发 finish 相互覆盖。
    """
    if span_id is None:
        return
    try:
        async with AsyncSessionLocal() as session:
            span = await session.get(TraceSpan, uuid.UUID(span_id))
            if span is None:
                return
            if span.status in ("succeeded", "failed"):
                return # 已终态，幂等不覆盖
            span.status = status
            span.duration_ms = duration_ms
            span.error_message = sanitize_error(error_message)
            span.tokens = tokens
            span.cost = cost
            span.hit_count = hit_count
            await session.commit()
    except Exception: # noqa: BLE001 span 更新失败只记日志
        logger.exception("observability: span 更新失败 span=%s status=%s", span_id, status)


async def start_task_span(name: str, *, trace_id: str | None = None) -> TraceSpan | None:
    """开启 task root span（parent=None）。trace_id 缺失时新建独立 root span。"""
    tid = trace_id or get_trace_id() or str(uuid.uuid4())
    return await write_span(trace_id=tid, parent_span_id=None, span_type="task", name=name, status="running")


async def start_agent_span(
    name: str, *, trace_id: str | None = None, parent_span_id: str | None = None
) -> TraceSpan | None:
    """开启 agent（图节点）span，parent = 显式 parent_span_id 或当前上下文 parent span。

    trace_id / parent_span_id 支持显式传入（AgentDeps 承载 trace 上下文），
    缺省时回退 contextvars。
    """
    tid = trace_id or get_trace_id()
    if tid is None:
        return None # 无 trace 上下文：跳过（查询返回空，不报错）
    parent = parent_span_id or get_parent_span_id()
    return await write_span(
        trace_id=tid, parent_span_id=parent, span_type="agent", name=name, status="running"
    )


async def record_llm_span(
    *,
    name: str,
    status: str,
    duration_ms: int,
    tokens: int,
    cost: float,
    error_message: str | None = None,
) -> None:
    """记录一次 LLM 调用 span（tokens/cost）。无 trace 上下文时跳过。"""
    tid = get_trace_id()
    if tid is None:
        return
    await write_span(
        trace_id=tid,
        parent_span_id=get_parent_span_id(),
        span_type="llm",
        name=name,
        status=status,
        duration_ms=duration_ms,
        tokens=tokens,
        cost=cost,
        error_message=error_message,
    )


async def record_rag_span(
    *,
    name: str,
    status: str,
    duration_ms: int,
    hit_count: int,
    error_message: str | None = None,
) -> None:
    """记录一次 RAG 检索 span（hit_count）。无 trace 上下文时跳过。"""
    tid = get_trace_id()
    if tid is None:
        return
    await write_span(
        trace_id=tid,
        parent_span_id=get_parent_span_id(),
        span_type="rag",
        name=name,
        status=status,
        duration_ms=duration_ms,
        hit_count=hit_count,
        error_message=error_message,
    )
