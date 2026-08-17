"""growth_plans / plan_tasks：成长计划与任务。"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GrowthPlan(Base):
    __tablename__ = "growth_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("career_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gap_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gap_analyses.id", ondelete="SET NULL"), nullable=True
    )
    stages: Mapped[dict | None] = mapped_column(JSONB, nullable=True) # 三阶段时间线
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PlanTask(Base):
    __tablename__ = "plan_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(512), nullable=True) # 推荐资源
    duration: Mapped[str | None] = mapped_column(String(64), nullable=True) # 预估耗时
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True) # short/mid/long
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="todo", server_default="todo"
    ) # todo/doing/done
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )