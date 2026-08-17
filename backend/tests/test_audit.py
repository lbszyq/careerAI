"""关键操作审计与二次确认测试（服务层 mock，不依赖真实 DB）。

覆盖：审计服务落库（auto_approved/pending）、确认/拒绝状态机（approve 执行、
reject 不执行）、错误码（不存在 4110 / 已处理 3408 / 非本人 1002），以及 4 个
关键操作在自动批准 / 待确认两种模式下的接入行为。
"""
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from helpers import make_token, make_user

from app.core.errors import ApiError, ErrorCode
from app.repositories.operation_review_repository import OperationReviewRepository
from app.repositories.user_repository import UserRepository
from app.schemas.audit import OperationConfirmationOut, OperationDecisionOut
from app.services import feedback_service as feedback_module
from app.services import report_service as report_module
from app.services.audit_service import AuditService
from app.services.error_codes import AuditErrorCode
from app.services.feedback_service import FeedbackService
from app.services.report_service import ReportService


def _review(**overrides) -> SimpleNamespace:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "action": "delete_achievement",
        "resource_type": "achievement",
        "resource_id": str(uuid.uuid4()),
        "payload": {"plan_id": str(uuid.uuid4()), "achievement_id": str(uuid.uuid4())},
        "status": "pending",
        "decided_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _require_confirmation(monkeypatch, value: bool):
    fake = SimpleNamespace(REQUIRE_CONFIRMATION=value)
    monkeypatch.setattr(feedback_module, "get_settings", lambda: fake)
    monkeypatch.setattr(report_module, "get_settings", lambda: fake)


# ---------- AuditService：审计落库 ----------


async def test_record_auto_approved_creates_auto_approved(monkeypatch):
    session = AsyncMock()
    user = make_user()
    row = _review(status="auto_approved")
    create = AsyncMock(return_value=row)
    monkeypatch.setattr(OperationReviewRepository, "create", create)

    result = await AuditService(session).record_auto_approved(
        user, "delete_achievement", "achievement", row.resource_id, row.payload
    )

    assert result is row
    create.assert_awaited_once_with(
        user.id, "delete_achievement", "achievement", row.resource_id, row.payload, "auto_approved"
    )


async def test_defer_creates_pending_and_returns_confirmation(monkeypatch):
    session = AsyncMock()
    user = make_user()
    row = _review(status="pending")
    create = AsyncMock(return_value=row)
    monkeypatch.setattr(OperationReviewRepository, "create", create)

    out = await AuditService(session).defer(
        user, "delete_achievement", "achievement", row.resource_id, row.payload
    )

    assert isinstance(out, OperationConfirmationOut)
    assert out.confirmation_id == row.id
    assert out.status == "pending"
    create.assert_awaited_once_with(
        user.id, "delete_achievement", "achievement", row.resource_id, row.payload, "pending"
    )


# ---------- AuditService：确认 / 拒绝状态机 ----------


async def test_approve_executes_and_marks_approved(monkeypatch):
    session = AsyncMock()
    user = make_user()
    row = _review(user_id=user.id, action="delete_achievement")
    monkeypatch.setattr(OperationReviewRepository, "get", AsyncMock(return_value=row))

    def _decide(review, status):
        review.status = status
        review.decided_at = datetime.now(UTC)

    decide = AsyncMock(side_effect=_decide)
    monkeypatch.setattr(OperationReviewRepository, "decide", decide)
    exec_fn = AsyncMock()
    monkeypatch.setattr(FeedbackService, "_delete_achievement", exec_fn)

    out = await AuditService(session).approve(user, row.id)

    exec_fn.assert_awaited_once() # 批准后执行原操作
    decide.assert_awaited_once_with(row, "approved")
    assert out.decision == "approved"
    assert out.confirmation_id == row.id


async def test_reject_marks_rejected_without_executing(monkeypatch):
    session = AsyncMock()
    user = make_user()
    row = _review(user_id=user.id, action="delete_achievement")
    monkeypatch.setattr(OperationReviewRepository, "get", AsyncMock(return_value=row))

    def _decide(review, status):
        review.status = status
        review.decided_at = datetime.now(UTC)

    decide = AsyncMock(side_effect=_decide)
    monkeypatch.setattr(OperationReviewRepository, "decide", decide)
    exec_fn = AsyncMock()
    monkeypatch.setattr(FeedbackService, "_delete_achievement", exec_fn)

    out = await AuditService(session).reject(user, row.id)

    exec_fn.assert_not_awaited() # 拒绝不执行
    decide.assert_awaited_once_with(row, "rejected")
    assert out.decision == "rejected"


async def test_approve_nonexistent_returns_4110(monkeypatch):
    session = AsyncMock()
    user = make_user()
    monkeypatch.setattr(OperationReviewRepository, "get", AsyncMock(return_value=None))

    with pytest.raises(ApiError) as exc:
        await AuditService(session).approve(user, uuid.uuid4())
    assert exc.value.code == AuditErrorCode.CONFIRMATION_NOT_FOUND
    assert exc.value.http_status == 404


async def test_approve_already_processed_returns_3408(monkeypatch):
    session = AsyncMock()
    user = make_user()
    row = _review(user_id=user.id, status="approved")
    monkeypatch.setattr(OperationReviewRepository, "get", AsyncMock(return_value=row))

    with pytest.raises(ApiError) as exc:
        await AuditService(session).approve(user, row.id)
    assert exc.value.code == AuditErrorCode.CONFIRMATION_ALREADY_PROCESSED
    assert exc.value.http_status == 409


async def test_approve_not_owned_returns_1002(monkeypatch):
    session = AsyncMock()
    user = make_user()
    row = _review(user_id=uuid.uuid4(), status="pending") # 另一用户
    monkeypatch.setattr(OperationReviewRepository, "get", AsyncMock(return_value=row))

    with pytest.raises(ApiError) as exc:
        await AuditService(session).approve(user, row.id)
    assert exc.value.code == ErrorCode.FORBIDDEN
    assert exc.value.http_status == 403


# ---------- 4 个关键操作：自动批准模式（执行 + 落 auto_approved） ----------


async def test_delete_achievement_auto_mode(monkeypatch):
    _require_confirmation(monkeypatch, False)
    session = AsyncMock()
    user = make_user()
    plan_id, achievement_id = uuid.uuid4(), uuid.uuid4()
    svc = FeedbackService(session)
    exec_fn = AsyncMock(return_value="deleted")
    monkeypatch.setattr(FeedbackService, "_delete_achievement", exec_fn)
    record = AsyncMock()
    monkeypatch.setattr(AuditService, "record_auto_approved", record)

    result = await svc.delete_achievement(user, plan_id, achievement_id)

    assert result == "deleted"
    exec_fn.assert_awaited_once_with(user, plan_id, achievement_id)
    record.assert_awaited_once()
    args = record.await_args.args
    assert args[0] is user
    assert args[1] == "delete_achievement"
    assert args[2] == "achievement"
    assert args[3] == str(achievement_id)
    assert args[4] == {"plan_id": str(plan_id), "achievement_id": str(achievement_id)}


async def test_apply_reassessment_auto_mode(monkeypatch):
    _require_confirmation(monkeypatch, False)
    session = AsyncMock()
    user = make_user()
    plan_id, reassess_id = uuid.uuid4(), uuid.uuid4()
    svc = FeedbackService(session)
    exec_fn = AsyncMock(return_value="applied")
    monkeypatch.setattr(FeedbackService, "_apply_reassessment", exec_fn)
    record = AsyncMock()
    monkeypatch.setattr(AuditService, "record_auto_approved", record)

    result = await svc.apply_reassessment(user, plan_id, reassess_id)

    assert result == "applied"
    exec_fn.assert_awaited_once_with(user, plan_id, reassess_id)
    record.assert_awaited_once()
    args = record.await_args.args
    assert args[1] == "apply_reassessment"
    assert args[2] == "reassessment"
    assert args[3] == str(reassess_id)
    assert args[4] == {"plan_id": str(plan_id), "reassess_id": str(reassess_id)}


async def test_discard_reassessment_auto_mode(monkeypatch):
    _require_confirmation(monkeypatch, False)
    session = AsyncMock()
    user = make_user()
    plan_id, reassess_id = uuid.uuid4(), uuid.uuid4()
    svc = FeedbackService(session)
    exec_fn = AsyncMock(return_value="discarded")
    monkeypatch.setattr(FeedbackService, "_discard_reassessment", exec_fn)
    record = AsyncMock()
    monkeypatch.setattr(AuditService, "record_auto_approved", record)

    result = await svc.discard_reassessment(user, plan_id, reassess_id)

    assert result == "discarded"
    exec_fn.assert_awaited_once_with(user, plan_id, reassess_id)
    record.assert_awaited_once()
    args = record.await_args.args
    assert args[1] == "discard_reassessment"
    assert args[2] == "reassessment"
    assert args[3] == str(reassess_id)
    assert args[4] == {"plan_id": str(plan_id), "reassess_id": str(reassess_id)}


async def test_regenerate_plan_auto_mode(monkeypatch):
    _require_confirmation(monkeypatch, False)
    session = AsyncMock()
    user = make_user()
    report_id = uuid.uuid4()
    svc = ReportService(session)
    exec_fn = AsyncMock(return_value="regen")
    monkeypatch.setattr(ReportService, "_regenerate_plan", exec_fn)
    record = AsyncMock()
    monkeypatch.setattr(AuditService, "record_auto_approved", record)

    result = await svc.regenerate_plan(user, report_id)

    assert result == "regen"
    exec_fn.assert_awaited_once_with(user, report_id)
    record.assert_awaited_once()
    args = record.await_args.args
    assert args[1] == "regenerate_plan"
    assert args[2] == "report"
    assert args[3] == str(report_id)
    assert args[4] == {"report_id": str(report_id)}


# ---------- 4 个关键操作：待确认模式（不执行，返回待确认 ID） ----------


async def test_delete_achievement_confirm_mode_defers(monkeypatch):
    _require_confirmation(monkeypatch, True)
    session = AsyncMock()
    user = make_user()
    plan_id, achievement_id = uuid.uuid4(), uuid.uuid4()
    svc = FeedbackService(session)
    exec_fn = AsyncMock()
    monkeypatch.setattr(FeedbackService, "_delete_achievement", exec_fn)
    confirmation = OperationConfirmationOut(confirmation_id=uuid.uuid4(), action="delete_achievement")
    defer = AsyncMock(return_value=confirmation)
    monkeypatch.setattr(AuditService, "defer", defer)

    result = await svc.delete_achievement(user, plan_id, achievement_id)

    exec_fn.assert_not_awaited()
    defer.assert_awaited_once()
    assert result is confirmation
    args = defer.await_args.args
    assert args[1] == "delete_achievement"
    assert args[2] == "achievement"
    assert args[3] == str(achievement_id)


async def test_apply_reassessment_confirm_mode_defers(monkeypatch):
    _require_confirmation(monkeypatch, True)
    session = AsyncMock()
    user = make_user()
    plan_id, reassess_id = uuid.uuid4(), uuid.uuid4()
    svc = FeedbackService(session)
    exec_fn = AsyncMock()
    monkeypatch.setattr(FeedbackService, "_apply_reassessment", exec_fn)
    confirmation = OperationConfirmationOut(confirmation_id=uuid.uuid4(), action="apply_reassessment")
    defer = AsyncMock(return_value=confirmation)
    monkeypatch.setattr(AuditService, "defer", defer)

    result = await svc.apply_reassessment(user, plan_id, reassess_id)

    exec_fn.assert_not_awaited()
    defer.assert_awaited_once()
    assert result is confirmation
    args = defer.await_args.args
    assert args[1] == "apply_reassessment"
    assert args[2] == "reassessment"
    assert args[3] == str(reassess_id)


async def test_discard_reassessment_confirm_mode_defers(monkeypatch):
    _require_confirmation(monkeypatch, True)
    session = AsyncMock()
    user = make_user()
    plan_id, reassess_id = uuid.uuid4(), uuid.uuid4()
    svc = FeedbackService(session)
    exec_fn = AsyncMock()
    monkeypatch.setattr(FeedbackService, "_discard_reassessment", exec_fn)
    confirmation = OperationConfirmationOut(confirmation_id=uuid.uuid4(), action="discard_reassessment")
    defer = AsyncMock(return_value=confirmation)
    monkeypatch.setattr(AuditService, "defer", defer)

    result = await svc.discard_reassessment(user, plan_id, reassess_id)

    exec_fn.assert_not_awaited()
    defer.assert_awaited_once()
    assert result is confirmation
    args = defer.await_args.args
    assert args[1] == "discard_reassessment"
    assert args[2] == "reassessment"
    assert args[3] == str(reassess_id)


async def test_regenerate_plan_confirm_mode_defers(monkeypatch):
    _require_confirmation(monkeypatch, True)
    session = AsyncMock()
    user = make_user()
    report_id = uuid.uuid4()
    svc = ReportService(session)
    exec_fn = AsyncMock()
    monkeypatch.setattr(ReportService, "_regenerate_plan", exec_fn)
    confirmation = OperationConfirmationOut(confirmation_id=uuid.uuid4(), action="regenerate_plan")
    defer = AsyncMock(return_value=confirmation)
    monkeypatch.setattr(AuditService, "defer", defer)

    result = await svc.regenerate_plan(user, report_id)

    exec_fn.assert_not_awaited()
    defer.assert_awaited_once()
    assert result is confirmation
    args = defer.await_args.args
    assert args[1] == "regenerate_plan"
    assert args[2] == "report"
    assert args[3] == str(report_id)


# ---------- API 层：确认端点 + 双模式响应信封 ----------


def test_delete_achievement_confirm_mode_returns_confirmation_via_api(client, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    _require_confirmation(monkeypatch, True)
    confirmation_id = uuid.uuid4()
    monkeypatch.setattr(AuditService, "defer", AsyncMock(return_value=OperationConfirmationOut(
        confirmation_id=confirmation_id, action="delete_achievement", status="pending"
    )))

    plan_id, achievement_id = uuid.uuid4(), uuid.uuid4()
    resp = client.delete(
        f"/api/v1/plans/{plan_id}/achievements/{achievement_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["confirmation_id"] == str(confirmation_id)
    assert body["data"]["status"] == "pending"


def test_approve_endpoint_returns_decision(client, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    decision = OperationDecisionOut(
        confirmation_id=uuid.uuid4(), action="delete_achievement",
        decision="approved", status="approved", decided_at=datetime.now(UTC),
    )
    monkeypatch.setattr(AuditService, "approve", AsyncMock(return_value=decision))

    resp = client.post(
        f"/api/v1/operations/{decision.confirmation_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["decision"] == "approved"
    assert body["data"]["confirmation_id"] == str(decision.confirmation_id)


def test_approve_endpoint_nonexistent_returns_4110(client, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(
        AuditService,
        "approve",
        AsyncMock(side_effect=ApiError(AuditErrorCode.CONFIRMATION_NOT_FOUND, "确认记录不存在", 404)),
    )

    resp = client.post(
        f"/api/v1/operations/{uuid.uuid4()}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == AuditErrorCode.CONFIRMATION_NOT_FOUND
    assert body["data"] is None
