"""trace_spans：任务级链路追踪 span（architecture.md）。

每个 span 属于一个 trace_id（一对多，trace_id 不建 UNIQUE 索引），通过 parent_span_id
串成 task → agent → llm/rag 的调用链。span 写入失败只记日志，不影响主业务成功路径。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# span_type 枚举（task|agent|llm|rag）
SPAN_TYPES = ("task", "agent", "llm", "rag")
# status 枚举（running|succeeded|failed）
SPAN_STATUSES = ("running", "succeeded", "failed")


class TraceSpan(Base):
    __tablename__ = "trace_spans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    span_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default="running"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
