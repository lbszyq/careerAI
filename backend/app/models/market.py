"""market_data：岗位市场数据（薪资/趋势/热度 + pgvector 向量；季度入库 B-001/）。"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketData(Base):
    __tablename__ = "market_data"
    __table_args__ = (
        # 城市×行业×岗位×数据季度 复合索引（覆盖原 3 列前缀索引，支撑 三维筛选 + 季度回溯）
        Index("ix_market_data_city_industry_job_quarter", "city", "industry", "job_title", "data_quarter"),
        # pgvector HNSW 向量索引（bge-m3 1024 维，余弦距离 <=>，RAG 检索）
        Index(
            "ix_market_data_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    industry: Mapped[str] = mapped_column(String(64), nullable=False)
    job_title: Mapped[str] = mapped_column(String(128), nullable=False)
    salary_p25: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_p50: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    salary_p75: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    trend: Mapped[str | None] = mapped_column(String(16), nullable=True) # 增长/稳定/下降
    heat: Mapped[str | None] = mapped_column(String(16), nullable=True) # 高/中/低
    required_skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    education_requirement: Mapped[str | None] = mapped_column(String(32), nullable=True) # 学历要求：不限/大专/本科/硕士/博士（可带「及以上」）
    responsibilities: Mapped[list | None] = mapped_column(JSONB, nullable=True) # 职责字符串数组（对齐 required_skills 形态）
    embedding: Mapped[list | None] = mapped_column(Vector(1024), nullable=True) # bge-m3 1024 维（）
    data_source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True) # 来源类型 official_stat/job_post/ai_infer（值域见 retriever._DATA_GRADE_MAP，真实数据禁 ai_infer）
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    data_quarter: Mapped[str | None] = mapped_column(String(16), nullable=True) # 数据季度 YYYYQn；年度数据存 YYYY
    city_tier: Mapped[str | None] = mapped_column(String(16), nullable=True) # 城市等级：一线/新一线/二线/三线/四线及以下
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
