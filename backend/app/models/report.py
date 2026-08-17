"""career_reports / career_directions / gap_analyses：报告及其衍生结果。"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CareerReport(Base):
    """职业画像报告（：历次报告不可删除）。"""

    __tablename__ = "career_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    ) # pending/processing/completed/failed
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="stage1", server_default="stage1")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True) # 5 维评分/常模对比/优劣势
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CareerDirection(Base):
    """职业方向推荐（3-5 方向 + 匹配度 + 薪资区间/趋势/热度）。"""

    __tablename__ = "career_directions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("career_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), nullable=False)
    match_score: Mapped[int] = mapped_column(Integer, nullable=False) # 0-100
    salary_p25: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_p50: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_p75: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    trend: Mapped[str | None] = mapped_column(String(16), nullable=True) # 增长/稳定/下降
    heat: Mapped[str | None] = mapped_column(String(16), nullable=True) # 高/中/低
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GapAnalysis(Base):
    """差距分析（已具备/部分具备/不具备三级 + 权重 + 目标岗位）。"""

    __tablename__ = "gap_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("career_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    direction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("career_directions.id", ondelete="SET NULL"), nullable=True
    )
    target_job: Mapped[str] = mapped_column(String(128), nullable=False)
    items: Mapped[list | None] = mapped_column(JSONB, nullable=True) # 差距明细（技能/权重/等级）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())