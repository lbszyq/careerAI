"""plans 模块请求/响应模型（plans-contract v1.3：成果覆盖任务语义）。"""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.feedback import AchievementOut, LatestReassessOut


class PlanTaskOut(BaseModel):
    id: uuid.UUID
    name: str
    resource: str | None
    duration: str | None
    stage: str | None
    status: str
    sort_order: int
    acceptance_criteria: str | None = None # v1.1：任务验证标准（可选，存量缺省）
    covered_by_achievement: bool = False # v1.3：是否被至少 1 个成果关联覆盖（由 achievements[].task_id 实时推导）


class PlanDetailOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    gap_analysis_id: uuid.UUID | None
    target_job: str | None
    stages: dict
    progress: int
    tasks: list[PlanTaskOut]
    created_at: datetime
    updated_at: datetime
    # v1.2 反馈闭环回显（optional/nullable，存量计划优雅降级）
    achievements: list[AchievementOut] = []
    reassess_eligible: bool = False
    reassess_eligible_reason: str | None = None
    latest_reassess: LatestReassessOut | None = None


class PlanProgressOut(BaseModel):
    plan_id: uuid.UUID
    progress: int
    total_tasks: int
    done_tasks: int
    covered_tasks: int = 0 # v1.3：被成果覆盖的任务数（含已 done；用于展示覆盖规模）
    effective_done_tasks: int = 0 # v1.3：去重后的有效完成数 = |done ∪ covered|
    stages: dict


class PlanTaskUpdateRequest(BaseModel):
    status: str # 枚举校验在 Service（契约 3301，区别于 pydantic 2001）


class PlanTaskUpdateOut(BaseModel):
    plan_id: uuid.UUID
    task_id: uuid.UUID
    task_status: str
    progress: int
