"""operation_reviews：关键操作审计与二次确认记录（architecture.md）。

对删除成果 / 应用重评 / 放弃重评 / 重算计划 4 个关键操作记录审计，并支持
REQUIRE_CONFIRMATION=true 时先待确认、批准后才执行的人机协同状态机：
- status ∈ pending / approved / rejected / auto_approved
  - REQUIRE_CONFIRMATION=false → 执行成功后落 1 条 auto_approved（默认演示模式）
  - REQUIRE_CONFIRMATION=true → 先落 pending 返回待确认 ID；批准→approved（执行）/拒绝→rejected（不执行）
- payload 保存操作重放参数，供批准后执行；id 同时作为 任务级 trace 打底的稳定锚点。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OperationReview(Base):
    __tablename__ = "operation_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # delete_achievement / apply_reassessment / discard_reassessment / regenerate_plan
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False) # achievement / reassessment / report
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False) # 资源 id 字符串（多态引用，不建 FK）
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False) # 操作重放参数
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending", index=True
    ) # pending / approved / rejected / auto_approved
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
