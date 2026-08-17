"""achievements / reassessments：反馈闭环成果记录与重评记录。

- achievements：用户上传执行成果（名称/URL/说明/关联阶段/任务）；URL 为不可信输入仅文本存储（T-01）。
- reassessments：重评记录，仅任务成功时落库（决策③）；result 存四部分结构。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlanAchievement(Base):
    __tablename__ = "achievements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False) # 成果名称 ≤100
    url: Mapped[str] = mapped_column(String(500), nullable=False) # http/https，≤500，不可信输入仅文本存储
    description: Mapped[str | None] = mapped_column(String(500), nullable=True) # 文字说明 ≤500
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True) # short/mid/long
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_tasks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Reassessment(Base):
    __tablename__ = "reassessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded", server_default="succeeded")
    decision: Mapped[str] = mapped_column(
        String(16), nullable=False, default="undecided", server_default="undecided"
    ) # undecided/applied/discarded
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True) # 重评结论摘要
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True) # 四部分：gap_change/plan_adjustment/stage_checks/adjustment_explanation
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
