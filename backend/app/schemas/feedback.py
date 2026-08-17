"""feedback 模块请求/响应模型（feedback-contract v1.2 + plans-contract v1.2 回显字段）。"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

STAGE_VALUES = Literal["short", "mid", "long"]


# ---------- achievements ----------

class AchievementCreateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100) # 缺失在 Service 判 2002；超长 2001
    url: str | None = None # http/https 协议 + ≤500 由 Service 校验（3407）
    description: str | None = Field(None, max_length=500)
    stage: STAGE_VALUES | None = None
    task_id: uuid.UUID | None = None


class AchievementUpdateRequest(BaseModel):
    """部分更新：未传字段保持不变；description/stage/task_id 显式传 null = 清除。

    通过 model_fields_set 区分「未传」与「显式 null」。
    """
    name: str | None = Field(None, min_length=1, max_length=100)
    url: str | None = None
    description: str | None = Field(None, max_length=500)
    stage: STAGE_VALUES | None = None
    task_id: uuid.UUID | None = None


class AchievementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    name: str
    url: str
    description: str | None
    stage: str | None
    task_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AchievementListOut(BaseModel):
    plan_id: uuid.UUID
    items: list[AchievementOut] = []


class AchievementDeleteOut(BaseModel):
    id: uuid.UUID
    deleted: bool = True


# ---------- reassessments ----------

class ReassessSubmitOut(BaseModel):
    task_id: uuid.UUID
    status: str = "pending"


class ReassessmentListItem(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    status: str
    decision: str
    summary: str | None
    created_at: datetime
    decided_at: datetime | None


class ReassessmentListOut(BaseModel):
    plan_id: uuid.UUID
    items: list[ReassessmentListItem] = []


class ReassessmentDetailOut(BaseModel):
    """重评结果详情（四部分 + 决策状态）。result JSONB 展开为结构化字段。"""
    id: uuid.UUID
    plan_id: uuid.UUID
    task_id: uuid.UUID | None
    status: str
    decision: str
    summary: str | None
    gap_change: dict | None
    plan_adjustment: dict | None
    stage_checks: dict | None
    adjustment_explanation: dict | None
    created_at: datetime
    decided_at: datetime | None


class ReassessApplyOut(BaseModel):
    reassess_id: uuid.UUID
    plan_id: uuid.UUID
    decision: str = "applied"
    applied_at: datetime
    progress: int


class ReassessDiscardOut(BaseModel):
    reassess_id: uuid.UUID
    plan_id: uuid.UUID
    decision: str = "discarded"
    discarded_at: datetime


# ---------- plans-contract v1.2 回显 ----------

class LatestReassessOut(BaseModel):
    task_id: uuid.UUID
    status: str
    result_ref: str | None
    created_at: datetime
    finished_at: datetime | None
