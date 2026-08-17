"""audit 模块请求/响应模型（：关键操作审计与二次确认）。"""
import uuid
from datetime import datetime

from pydantic import BaseModel

# 关键操作 action 枚举（与 feedback_service / report_service 接入点保持一致）
ACTION_VALUES = (
    "delete_achievement",
    "apply_reassessment",
    "discard_reassessment",
    "regenerate_plan",
)


class OperationConfirmationOut(BaseModel):
    """REQUIRE_CONFIRMATION=true 时，关键操作返回的待确认结果。"""

    confirmation_id: uuid.UUID
    action: str
    status: str = "pending"
    message: str = "操作已记录，等待二次确认"


class OperationDecisionOut(BaseModel):
    """批准 / 拒绝确认的结果。"""

    confirmation_id: uuid.UUID
    action: str
    decision: str # approved / rejected
    status: str # approved / rejected
    decided_at: datetime


class OperationReviewOut(BaseModel):
    """审计记录摘要（供查询/回显；确认端点不直接返回全量）。"""

    id: uuid.UUID
    action: str
    resource_type: str
    resource_id: str
    status: str
    created_at: datetime
    decided_at: datetime | None
