"""reports 模块请求/响应模型（reports-contract）。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ReportCreateRequest(BaseModel):
    profile_id: uuid.UUID
    preferred_cities: list[str] | None = Field(default=None, max_length=5)
    preferred_industries: list[str] | None = Field(default=None, max_length=5)


class GapRequest(BaseModel):
    direction_id: uuid.UUID | None = None


class ReportListItemOut(BaseModel):
    id: uuid.UUID
    stage: str
    status: str # pending/running/completed/failed
    score: int | None
    summary: dict
    created_at: datetime


class ReportDirectionOut(BaseModel):
    id: uuid.UUID
    job_title: str
    match_score: int
    salary: dict | None
    salary_note: str | None
    trend: str | None
    heat: str | None
    data_source: str | None
    education_requirement: str | None = None
    education_match: str | None = None
    competition_note: str | None = None
    certificates_bonus: str | None = None
    recommend_reason: str | None = None
    data_grade: str | None = None # v1.1：市场数据来源等级 A/B/C（入库 source_type 派生，Agent 不自判）
    confidence_reasons: dict | None = None # v1.1：方向推荐置信度原因拆解（supporting/concerns）
    salary_comparison: dict | None = None # v1.3：期望薪资 vs 岗位分位对比（确定性计算）


class ReportDetailOut(BaseModel):
    id: uuid.UUID
    stage: str
    status: str
    portrait: dict | None
    directions: list[ReportDirectionOut]
    gap_analysis: dict | None
    plan: dict | None
    suggestion: dict | None = None # v1.1：AI 策略建议（仅 Stage 2 完整报告，否则 null）
    created_at: datetime
    finished_at: datetime | None
