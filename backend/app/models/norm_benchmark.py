"""norm_benchmarks：常模基准（B-002/ 定案：同届×城市等级×专业大类分组，供 常模对比）。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NormBenchmark(Base):
    """常模基准单元。

    - 分组键：graduation_year（同届）× city_tier（城市等级）× major_category（专业大类）
    - 阈值：salary_p25/p50/p75（前 25%/中 50%/后 25% 分位，元/月）
    - 单元样本 <30（理想 ≥100）时应用层降级「样本不足」，不输出精确分位（C-009/）
    - data_quarter 约定：季度聚合 "YYYYQn"（如 2026Q1）；年度聚合（如高校就业质量年报）存 "YYYY"
    """

    __tablename__ = "norm_benchmarks"
    __table_args__ = (
        UniqueConstraint(
            "graduation_year", "city_tier", "major_category", "data_quarter", name="uq_norm_benchmarks_unit"
        ),
        Index("ix_norm_benchmarks_group", "graduation_year", "city_tier", "major_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    graduation_year: Mapped[int] = mapped_column(Integer, nullable=False) # 毕业年份（同届）
    city_tier: Mapped[str] = mapped_column(String(16), nullable=False) # 城市等级
    major_category: Mapped[str] = mapped_column(String(64), nullable=False) # 专业大类
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False) # 样本量
    salary_p25: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True) # 前 25% 分位阈值（元/月）
    salary_p50: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True) # 中 50% 分位阈值
    salary_p75: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True) # 后 25% 分位阈值
    contains_employed: Mapped[bool] = mapped_column( # 是否含在职样本（报告标注口径）
        Boolean, nullable=False, default=True, server_default="true"
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True) # 置信度 0-1
    data_quarter: Mapped[str] = mapped_column(String(16), nullable=False) # 数据季度/年度：YYYYQn 或 YYYY
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
