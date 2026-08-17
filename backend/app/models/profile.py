"""user_profiles：解析后的职业画像（简历原文件不落库）。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    school: Mapped[str | None] = mapped_column(String(128), nullable=True)
    major: Mapped[str | None] = mapped_column(String(128), nullable=True)
    education: Mapped[str | None] = mapped_column(String(32), nullable=True) # 学历
    gpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True) # 毕业年份（同届常模维度 + C-002 门槛）
    skills: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # skills 并行 provenance 数组（与 skills 索引对齐，元素 ∈ {"literal","inferred"}，
    # 记录技能来源：原文显式出现 / 蕴含反推；随画像落库供 Stage2 差距分析消费，方案 b）
    skills_sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    internships: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    projects: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    certificates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    preferred_cities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]") # 意向城市 ≤5
    preferred_industries: Mapped[list] = mapped_column( # 意向行业 ≤5
        JSONB, nullable=False, default=list, server_default="[]"
    )
    expected_salary: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True) # 期望月薪（元/月）
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
