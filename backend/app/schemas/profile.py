"""profile 模块请求/响应模型（profile-contract）。"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Education = Literal["专科", "本科", "硕士", "博士"]


class ProfileUpdate(BaseModel):
    """PUT /profile 请求体：全部字段可空（草稿态，C-001 upsert 单活跃档案）。"""

    name: str | None = Field(default=None, max_length=64)
    school: str | None = Field(default=None, max_length=128)
    major: str | None = Field(default=None, max_length=128)
    education: Education | None = None
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    gpa: float | None = Field(default=None, ge=0)
    skills: list[str] | None = None
    internships: list[dict] | None = None
    projects: list[dict] | None = None
    certificates: list[str] | None = None
    preferred_cities: list[str] | None = None
    preferred_industries: list[str] | None = None
    expected_salary: int | None = Field(default=None, ge=0)


class ProfileOut(BaseModel):
    """GET/PUT /profile 响应（与契约 GET 同构）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    school: str | None
    major: str | None
    education: str | None
    graduation_year: int | None
    gpa: float | None
    skills: list[str]
    internships: list[dict]
    projects: list[dict]
    certificates: list[str]
    preferred_cities: list[str]
    preferred_industries: list[str]
    expected_salary: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
