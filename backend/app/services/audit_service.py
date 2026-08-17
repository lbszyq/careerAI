"""关键操作审计与二次确认服务（architecture.md 人机协同）。

双模式（core.config.REQUIRE_CONFIRMATION）：
- false（默认）：关键操作执行成功后落 1 条 status=auto_approved 审计记录（本地演示不打断）。
- true：关键操作不立即执行，落 status=pending 并返回待确认 ID；随后调用
  approve → 执行原操作并置 approved；reject → 不执行并置 rejected。

批准重放：按 action 派发到注册的执行器（懒导入，避免与 feedback/report service
形成循环依赖）；执行器调用对应 service 的内部 _* 方法（不含审计包装），保证
批准不会递归产生新的审计记录。
"""
import uuid
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ErrorCode
from app.models import User
from app.repositories.operation_review_repository import OperationReviewRepository
from app.schemas.audit import OperationConfirmationOut, OperationDecisionOut
from app.services.error_codes import AuditErrorCode

_Executor = Callable[[AsyncSession, User, dict], Awaitable[object]]
_EXECUTORS: dict[str, _Executor] = {}


def _executor(action: str):
    """注册关键操作执行器（批准时重放）。"""

    def deco(fn: _Executor) -> _Executor:
        _EXECUTORS[action] = fn
        return fn

    return deco


@_executor("delete_achievement")
async def _exec_delete_achievement(session: AsyncSession, user: User, payload: dict):
    from app.services.feedback_service import FeedbackService

    return await FeedbackService(session)._delete_achievement(
        user, uuid.UUID(payload["plan_id"]), uuid.UUID(payload["achievement_id"])
    )


@_executor("apply_reassessment")
async def _exec_apply_reassessment(session: AsyncSession, user: User, payload: dict):
    from app.services.feedback_service import FeedbackService

    return await FeedbackService(session)._apply_reassessment(
        user, uuid.UUID(payload["plan_id"]), uuid.UUID(payload["reassess_id"])
    )


@_executor("discard_reassessment")
async def _exec_discard_reassessment(session: AsyncSession, user: User, payload: dict):
    from app.services.feedback_service import FeedbackService

    return await FeedbackService(session)._discard_reassessment(
        user, uuid.UUID(payload["plan_id"]), uuid.UUID(payload["reassess_id"])
    )


@_executor("regenerate_plan")
async def _exec_regenerate_plan(session: AsyncSession, user: User, payload: dict):
    from app.services.report_service import ReportService

    return await ReportService(session)._regenerate_plan(user, uuid.UUID(payload["report_id"]))


class AuditService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = OperationReviewRepository(session)

    async def record_auto_approved(
        self, user: User, action: str, resource_type: str, resource_id: str, payload: dict
    ) -> object:
        """自动批准模式：关键操作执行成功后落 1 条 auto_approved 审计记录。"""
        row = await self.repo.create(
            user.id, action, resource_type, resource_id, payload, "auto_approved"
        )
        await self.session.commit()
        return row

    async def defer(
        self, user: User, action: str, resource_type: str, resource_id: str, payload: dict
    ) -> OperationConfirmationOut:
        """二次确认模式：落 pending 并返回待确认 ID（不执行操作）。"""
        row = await self.repo.create(
            user.id, action, resource_type, resource_id, payload, "pending"
        )
        await self.session.commit()
        return OperationConfirmationOut(confirmation_id=row.id, action=action, status="pending")

    async def _load_pending(self, user: User, confirmation_id: uuid.UUID):
        """确认前置校验：不存在 4110 / 非本人 1002 / 已处理 3408。"""
        row = await self.repo.get(confirmation_id)
        if row is None:
            raise ApiError(AuditErrorCode.CONFIRMATION_NOT_FOUND, "确认记录不存在", 404)
        if row.user_id != user.id:
            raise ApiError(ErrorCode.FORBIDDEN, "无权操作该确认记录", 403)
        if row.status != "pending":
            raise ApiError(
                AuditErrorCode.CONFIRMATION_ALREADY_PROCESSED,
                "该确认记录已处理，不可重复操作",
                409,
            )
        return row

    async def approve(self, user: User, confirmation_id: uuid.UUID) -> OperationDecisionOut:
        """批准：执行原操作并置 approved。执行失败则保持 pending，可重试。"""
        row = await self._load_pending(user, confirmation_id)
        executor = _EXECUTORS.get(row.action)
        if executor is None:
            raise ApiError(ErrorCode.INTERNAL_ERROR, "未知操作类型，无法执行", 500)
        await executor(self.session, user, row.payload or {})
        await self.repo.decide(row, "approved")
        await self.session.commit()
        return OperationDecisionOut(
            confirmation_id=row.id, action=row.action, decision="approved",
            status="approved", decided_at=row.decided_at,
        )

    async def reject(self, user: User, confirmation_id: uuid.UUID) -> OperationDecisionOut:
        """拒绝：不执行原操作，置 rejected。"""
        row = await self._load_pending(user, confirmation_id)
        await self.repo.decide(row, "rejected")
        await self.session.commit()
        return OperationDecisionOut(
            confirmation_id=row.id, action=row.action, decision="rejected",
            status="rejected", decided_at=row.decided_at,
        )
