"""market 模块请求/响应模型（market-contract，公开访问）。"""
import uuid
from datetime import datetime

from pydantic import BaseModel


class MarketJobOut(BaseModel):
    id: uuid.UUID
    job_title: str
    city: str
    industry: str
    salary: dict | None
    trend: str | None
    heat: str | None
    data_source: str | None
    confidence: float | None


class MarketListOut(BaseModel):
    total: int
    page: int
    page_size: int
    data_quarter: str | None
    lag_note: str
    items: list[MarketJobOut]


class MarketJobDetailOut(BaseModel):
    id: uuid.UUID
    job_title: str
    city: str
    industry: str
    salary: dict | None
    trend: str | None
    heat: str | None
    required_skills: list[str]
    data_source: str | None
    data_quarter: str | None
    confidence: float | None
    updated_at: datetime


class MarketFacetsOut(BaseModel):
    cities: list[str]
    industries: list[str]
    quarters: list[str]
