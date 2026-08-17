"""异步任务模块请求/响应模型。"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskTriggerRequest(BaseModel):
    task_type: str = Field(min_length=1, max_length=64)
    params: dict | None = None


class TaskTriggerResult(BaseModel):
    task_id: uuid.UUID
    status: str = "pending"


class TaskCancelResult(BaseModel):
    task_id: uuid.UUID
    status: str


class TaskJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_type: str
    status: str
    progress: int
    stage: str | None
    result_ref: str | None
    result: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
