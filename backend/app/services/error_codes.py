"""模块业务错误码（docs/architecture.md 错误码规范）。

按契约子区间定义：profile 31xx / reports 32xx / plans 33xx / market+feedback+audit 34xx 业务、
41xx 资源、3003 tasks cancel 业务。全局错误码（1001/2001 等）沿用 app.core.errors。
说明：3001/4001/4101/1002 跨模块复用沿用既有 TaskErrorCode/AuthErrorCode（T 登记，
处置结论：显式别名复用，见 architecture.md /）。
"""
from app.core.errors import ErrorCode # noqa: F401 复用全局错误码常量


class ProfileErrorCode:
    """profile 模块（31xx 业务 / 无 41xx 资源，资源段复用 4101 PROFILE_NOT_FOUND）。"""

    PROFILE_LIMIT_REACHED = 3101
    FILE_TYPE_UNSUPPORTED = 3103
    FILE_SIZE_EXCEEDED = 3104
    PROFILE_NOT_FOUND = 4101 # 与 reports 共用 4101（reports-contract 已定义）


class ReportErrorCode:
    """reports 模块（32xx 业务 / 41xx 资源 / 51xx 外部依赖）。"""

    REPORT_STAGE_CONFLICT = 3201
    REPORT_QUOTA_EXCEEDED = 3202
    REPORT_PROFILE_INCOMPLETE = 3203
    DIRECTION_REQUIRED = 3204
    PLAN_REGEN_NOT_ALLOWED = 3205
    PROFILE_NOT_FOUND = 4101
    REPORT_NOT_FOUND = 4102
    DIRECTION_NOT_FOUND = 4103


class PlanErrorCode:
    """plans 模块（33xx 业务 / 41xx 资源）。"""

    PLAN_TASK_STATUS_INVALID = 3301
    PLAN_NOT_FOUND = 4104
    PLAN_TASK_NOT_FOUND = 4106


class FeedbackErrorCode:
    """feedback 模块（feedback-contract v1.2：34xx 业务 / 41xx 资源）。"""

    REASSESS_NOT_ELIGIBLE = 3402
    REASSESS_IN_PROGRESS = 3403
    REASSESS_ALREADY_DECIDED = 3404
    REASSESS_NOT_DECIDABLE = 3405
    ACHIEVEMENT_ASSOCIATION_INVALID = 3406
    ACHIEVEMENT_URL_INVALID = 3407
    REASSESSMENT_NOT_FOUND = 4108
    ACHIEVEMENT_NOT_FOUND = 4109


class MarketErrorCode:
    """market 模块（34xx 业务 / 41xx 资源）。"""

    MARKET_FILTER_INVALID = 3401
    JOB_NOT_FOUND = 4107


class AuditErrorCode:
    """audit 模块（audit-contract v1.0：34xx 业务 / 41xx 资源）。

    归属校验复用全局 FORBIDDEN=1002（非本模块专有码）。
    """

    CONFIRMATION_NOT_FOUND = 4110
    CONFIRMATION_ALREADY_PROCESSED = 3408


class TaskCancelErrorCode:
    """tasks cancel 新增业务码（3003；3001/4001/1002 沿用 TaskErrorCode）。"""

    TASK_ALREADY_FINISHED = 3003


class TaskQuotaErrorCode:
    """tasks 限流新增业务码（越权审计）：3004 属 tasks 业务段 30xx 空闲码。

    不复用 reports 3202 REPORT_QUOTA_EXCEEDED（避免 T 语义耦合）；docs 待 项目负责人 合并后回填。
    """

    TASK_QUOTA_EXCEEDED = 3004
