"""任务触发端点越权（IDOR）与限流测试（用户审计）。

覆盖验证标准：
- 标准 1（越权，锚点 job.user_id）：5 个 executor 对他人身份/资源一律 mark_failed 且不产生副作用
  （resume_parse 以 assert_not_awaited 证明 B 画像未覆写；plan_reassess 无重评记录落库）
- 标准 1b（合法路径回归）：合法用户（params.user_id == job.user_id、资源归属本人）5 个 executor 正常完成
- 标准 2（白名单 +）：trigger 枚举 5 注册类型，未知/内部类型 TASK_TYPE_UNSUPPORTED；非法 UUID 安全失败
- 标准 3（限流）：TASK_QUOTA_EXCEEDED（3004）超限返回配额错误；非配额类型不触发新配额
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from helpers import make_token, make_user

from app.core.errors import ErrorCode, TaskErrorCode
from app.models import TaskJob
from app.repositories.task_job_repository import TaskJobRepository
from app.repositories.user_repository import UserRepository
from app.services import task_service as task_service_module
from app.services.error_codes import TaskQuotaErrorCode
from app.tasks.executors import (
    plan_reassess_executor,
    plan_regenerate_executor,
    report_stage1_executor,
    report_stage2_executor,
    resume_parse_executor,
)

TRIGGER_URL = "/api/v1/tasks/trigger"


# ---------- 测试辅助：最小 AsyncSession 替身（不依赖真实 DB） ----------


class _Row:
    """scalars() 包装：first()/all()。"""

    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value

    def all(self):
        return self._value if isinstance(self._value, list) else [self._value]


class _ExecResult:
    """execute() 结果包装（first()/scalars()）。"""

    def __init__(self, value):
        self._value = value

    def scalars(self):
        return _Row(self._value)

    def first(self):
        return self._value


class FakeSession:
    """执行器测试用最小 AsyncSession 替身。

    - get(TaskJob, ...) 恒返回 job（任务归属锚点读取）；其余 get 从 get_map 取
    - execute() 按顺序消费 execute_values；不足时默认返回 job（_is_cancelled 等任务查询）
    - add/flush/commit 仅记录，不真正落库
    """

    def __init__(self, job, get_map=None, execute_values=None):
        self.job = job
        self.get_map = get_map or {}
        self.execute_values = list(execute_values or [])
        self._i = 0
        self.added = []
        self.flushes = 0
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, pk):
        if model is TaskJob:
            return self.job
        return self.get_map.get(pk)

    async def execute(self, stmt):
        if self._i < len(self.execute_values):
            value = self.execute_values[self._i]
            self._i += 1
            return value if isinstance(value, _ExecResult) else _ExecResult(value)
        return _ExecResult(self.job)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1


def _job(owner_id, status="running") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), user_id=owner_id, task_type="x", status=status, progress=0,
        stage=None, result=None, result_ref=None, error_message=None,
        celery_task_id=None, trace_id=None, finished_at=None,
    )


def _profile(owner_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), user_id=owner_id, name="张三", school="清华", major="计算机",
        education="本科", gpa=3.8, graduation_year=2026,
        skills=["python"], internships=[], projects=[], certificates=[],
        preferred_cities=[], preferred_industries=[], expected_salary=None,
    )


def _report(owner_id, report_id=None, profile_id=None) -> SimpleNamespace:
    return SimpleNamespace(
        id=report_id or uuid.uuid4(), user_id=owner_id, profile_id=profile_id, result={}
    )


def _direction(report_id) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), report_id=report_id, job_title="算法工程师")


def _plan(report_id) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), report_id=report_id)


def _gap(report_id) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), report_id=report_id, target_job="算法工程师", items=[])


# ---------- 标准 2：白名单（枚举 5 注册类型，防空集） ----------


def test_public_task_types_match_registry_and_enumeration():
    """标准 2：trigger 白名单 == 5 个注册类型（防空集：未来注册内部类型必须显式决策）。"""
    from app.services.task_service import PUBLIC_TASK_TYPES
    from app.tasks.executors.registry import ExecutorRegistry

    assert {
        "resume_parse",
        "report_stage1",
        "report_stage2",
        "plan_regenerate",
        "plan_reassess",
    } == PUBLIC_TASK_TYPES
    assert set(PUBLIC_TASK_TYPES) == set(ExecutorRegistry.all_types())


# ---------- 标准 2/3：trigger 端点（API 层） ----------


def test_trigger_unsupported_type_returns_3001(client, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    resp = client.post(
        TRIGGER_URL,
        json={"task_type": "internal_hack_type", "params": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == TaskErrorCode.TASK_TYPE_UNSUPPORTED


def test_trigger_foreign_user_id_returns_1002(client, monkeypatch):
    """标准 1（API 层）：params.user_id != current_user.id → 403/1002。"""
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    victim_id = uuid.uuid4()
    resp = client.post(
        TRIGGER_URL,
        json={"task_type": "resume_parse", "params": {"user_id": str(victim_id)}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == TaskErrorCode.TASK_NOT_OWNED


def test_trigger_invalid_user_id_returns_2001(client, monkeypatch):
    """标准 2：user_id 非法 UUID → 400/2001，不触发任务创建。"""
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    resp = client.post(
        TRIGGER_URL,
        json={"task_type": "resume_parse", "params": {"user_id": "not-a-uuid"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.INVALID_PARAM


def test_trigger_own_user_id_succeeds(client, monkeypatch):
    """标准 1b：params.user_id == current_user.id 正常创建任务。"""
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    job = _job(user.id, status="pending")
    monkeypatch.setattr(TaskJobRepository, "create", AsyncMock(return_value=job))
    monkeypatch.setattr(TaskJobRepository, "count_quota_today", AsyncMock(return_value=0))
    fake_run = MagicMock()
    fake_run.delay = MagicMock(return_value=SimpleNamespace(id="celery-1"))
    monkeypatch.setattr(task_service_module, "run_task_job", fake_run)

    resp = client.post(
        TRIGGER_URL,
        json={"task_type": "resume_parse", "params": {"user_id": str(user.id)}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["task_id"] == str(job.id)


def test_trigger_plan_reassess_without_user_id_succeeds(client, monkeypatch):
    """标准 1b：plan_reassess 合法参数不含 user_id（归属在 executor 经 JOIN 校验）。"""
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    job = _job(user.id, status="pending")
    monkeypatch.setattr(TaskJobRepository, "create", AsyncMock(return_value=job))
    monkeypatch.setattr(TaskJobRepository, "count_quota_today", AsyncMock(return_value=0))
    fake_run = MagicMock()
    fake_run.delay = MagicMock(return_value=SimpleNamespace(id="celery-1"))
    monkeypatch.setattr(task_service_module, "run_task_job", fake_run)

    resp = client.post(
        TRIGGER_URL,
        json={"task_type": "plan_reassess", "params": {"plan_id": str(uuid.uuid4())}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_trigger_quota_exceeded_returns_3004(client, monkeypatch):
    """标准 3：配额类型任务超限 → 429 + TASK_QUOTA_EXCEEDED（3004）。"""
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(TaskJobRepository, "count_quota_today", AsyncMock(return_value=2))
    monkeypatch.setattr(
        task_service_module, "get_settings", lambda: SimpleNamespace(AI_DAILY_TASK_LIMIT=2)
    )
    resp = client.post(
        TRIGGER_URL,
        json={"task_type": "plan_reassess", "params": {"plan_id": str(uuid.uuid4())}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 429
    assert resp.json()["code"] == TaskQuotaErrorCode.TASK_QUOTA_EXCEEDED


async def test_create_and_dispatch_skips_quota_for_report_stage1(monkeypatch):
    """标准 3/：report_stage1 不适用新任务配额（沿用 reports 3202），不触发 count_quota_today。"""
    from app.services.task_service import TaskService

    user = make_user()
    job = _job(user.id, status="pending")
    repo = MagicMock()
    repo.create = AsyncMock(return_value=job)
    session = AsyncMock()
    session.commit = AsyncMock()
    service = TaskService(session)
    service.job_repo = repo
    fake_run = MagicMock()
    fake_run.delay = MagicMock(return_value=SimpleNamespace(id="celery-1"))
    monkeypatch.setattr(task_service_module, "run_task_job", fake_run)

    await service.create_and_dispatch(user, "report_stage1", {"profile_id": str(uuid.uuid4())})

    repo.count_quota_today.assert_not_called()
    repo.create.assert_awaited_once()


# ---------- 标准 1/1b：resume_parse ----------


async def test_resume_parse_foreign_user_id_marked_failed_no_upsert(monkeypatch):
    """标准 1：A 的 job 传 params.user_id=B → mark_failed 且 upsert 未被调用（B 画像未覆写）。"""
    attacker, victim = uuid.uuid4(), uuid.uuid4()
    job = _job(attacker)
    monkeypatch.setattr(resume_parse_executor, "AsyncSessionLocal", lambda: FakeSession(job))
    upsert = AsyncMock()
    monkeypatch.setattr(resume_parse_executor, "upsert_resume_profile", upsert)
    monkeypatch.setattr(resume_parse_executor, "router_node", AsyncMock())
    monkeypatch.setattr(resume_parse_executor, "get_llm_client", MagicMock())

    await resume_parse_executor.ResumeParseExecutor().execute(
        str(job.id), {"user_id": str(victim), "raw_text": "..."}
    )

    assert job.status == "failed"
    assert "无权" in job.error_message
    upsert.assert_not_awaited()


@pytest.mark.parametrize(
    "params", [{"user_id": ""}, {"raw_text": "x"}, {"user_id": "not-a-uuid"}]
)
async def test_resume_parse_invalid_user_id_safe_fail(monkeypatch, params):
    """标准 2：user_id 缺失/非法 UUID → 安全失败不崩溃（try/except）。"""
    job = _job(uuid.uuid4())
    monkeypatch.setattr(resume_parse_executor, "AsyncSessionLocal", lambda: FakeSession(job))
    upsert = AsyncMock()
    monkeypatch.setattr(resume_parse_executor, "upsert_resume_profile", upsert)

    await resume_parse_executor.ResumeParseExecutor().execute(str(job.id), dict(params))

    assert job.status == "failed"
    assert "user_id" in job.error_message
    upsert.assert_not_awaited()


async def test_resume_parse_legit_succeeds(monkeypatch):
    """标准 1b：合法用户（params.user_id == job.user_id）正常 upsert。"""
    owner = uuid.uuid4()
    job = _job(owner)
    monkeypatch.setattr(resume_parse_executor, "AsyncSessionLocal", lambda: FakeSession(job))
    upsert = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(resume_parse_executor, "upsert_resume_profile", upsert)
    monkeypatch.setattr(
        resume_parse_executor,
        "router_node",
        AsyncMock(return_value={"profile": {"name": "张三"}, "profile_complete": True}),
    )
    monkeypatch.setattr(resume_parse_executor, "get_llm_client", MagicMock())

    await resume_parse_executor.ResumeParseExecutor().execute(
        str(job.id), {"user_id": str(owner), "raw_text": "..."}
    )

    assert job.status == "succeeded"
    upsert.assert_awaited_once()
    assert upsert.await_args.args[1] == owner


# ---------- 标准 1/1b：report_stage1 ----------


def _stage1_mocks(monkeypatch):
    save = AsyncMock(return_value=(uuid.uuid4(), []))
    monkeypatch.setattr(report_stage1_executor, "save_stage1_result", save)
    monkeypatch.setattr(report_stage1_executor, "safe_run_graph", AsyncMock(return_value={"report": {}}))
    monkeypatch.setattr(report_stage1_executor, "build_stage1_graph", MagicMock())
    monkeypatch.setattr(report_stage1_executor, "get_llm_client", MagicMock())
    monkeypatch.setattr(report_stage1_executor, "get_embedding_provider", MagicMock())
    return save


async def test_stage1_foreign_user_and_profile_marked_failed(monkeypatch):
    """标准 1：A 的 job 传 params.user_id=B + profile_id=B的 → 拒绝（锚点 job.user_id）。"""
    attacker, victim = uuid.uuid4(), uuid.uuid4()
    job = _job(attacker)
    victim_profile = _profile(victim)
    monkeypatch.setattr(report_stage1_executor, "AsyncSessionLocal", lambda: FakeSession(job))
    save = _stage1_mocks(monkeypatch)

    await report_stage1_executor.ReportStage1Executor().execute(
        str(job.id), {"user_id": str(victim), "profile_id": str(victim_profile.id)}
    )

    assert job.status == "failed"
    assert "无权" in job.error_message
    save.assert_not_awaited()


async def test_stage1_foreign_profile_with_own_user_id_marked_failed(monkeypatch):
    """标准 1 深水区：params.user_id=本人、profile_id 属他人 → 画像查询锚定 job.user_id 查无 → 拒绝。"""
    owner, victim = uuid.uuid4(), uuid.uuid4()
    job = _job(owner)
    victim_profile = _profile(victim)
    # 画像归属查询锚定 job.user_id：受害者画像不匹配 owner，模拟查无（None）
    session = FakeSession(job, execute_values=[_ExecResult(job), _ExecResult(None), _ExecResult(job), _ExecResult(job)])
    monkeypatch.setattr(report_stage1_executor, "AsyncSessionLocal", lambda: session)
    save = _stage1_mocks(monkeypatch)

    await report_stage1_executor.ReportStage1Executor().execute(
        str(job.id), {"user_id": str(owner), "profile_id": str(victim_profile.id)}
    )

    assert job.status == "failed"
    assert "画像不存在或非本人" in job.error_message
    save.assert_not_awaited()


async def test_stage1_legit_succeeds(monkeypatch):
    """标准 1b：本人画像（归属 job.user_id）正常完成。"""
    owner = uuid.uuid4()
    job = _job(owner)
    profile = _profile(owner)
    session = FakeSession(job, execute_values=[_ExecResult(job), _ExecResult(profile), _ExecResult(job), _ExecResult(job)])
    monkeypatch.setattr(report_stage1_executor, "AsyncSessionLocal", lambda: session)
    save = _stage1_mocks(monkeypatch)

    await report_stage1_executor.ReportStage1Executor().execute(
        str(job.id), {"user_id": str(owner), "profile_id": str(profile.id)}
    )

    assert job.status == "succeeded"
    save.assert_awaited_once()


# ---------- 标准 1/1b：report_stage2 ----------


def _stage2_mocks(monkeypatch):
    save = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr(report_stage2_executor, "save_stage2_result", save)
    monkeypatch.setattr(report_stage2_executor, "safe_run_graph", AsyncMock(return_value={"report": {}}))
    monkeypatch.setattr(report_stage2_executor, "build_stage2_graph", MagicMock())
    monkeypatch.setattr(report_stage2_executor, "get_llm_client", MagicMock())
    monkeypatch.setattr(report_stage2_executor, "get_embedding_provider", MagicMock())
    return save


async def test_stage2_foreign_report_marked_failed(monkeypatch):
    """标准 1：A 的 job 传 params.user_id=B + report_id=B的 → 拒绝。"""
    attacker, victim = uuid.uuid4(), uuid.uuid4()
    job = _job(attacker)
    victim_report = _report(victim)
    monkeypatch.setattr(
        report_stage2_executor, "AsyncSessionLocal",
        lambda: FakeSession(job, get_map={victim_report.id: victim_report}),
    )
    save = _stage2_mocks(monkeypatch)

    await report_stage2_executor.ReportStage2Executor().execute(
        str(job.id),
        {"user_id": str(victim), "report_id": str(victim_report.id), "direction_id": str(uuid.uuid4())},
    )

    assert job.status == "failed"
    assert "无权" in job.error_message
    save.assert_not_awaited()


async def test_stage2_foreign_report_with_own_user_id_marked_failed(monkeypatch):
    """标准 1 深水区：params.user_id=本人、report_id 属他人 → 报告归属比对锚定 job.user_id 拒绝。"""
    owner, victim = uuid.uuid4(), uuid.uuid4()
    job = _job(owner)
    victim_report = _report(victim)
    monkeypatch.setattr(
        report_stage2_executor, "AsyncSessionLocal",
        lambda: FakeSession(job, get_map={victim_report.id: victim_report}),
    )
    save = _stage2_mocks(monkeypatch)

    await report_stage2_executor.ReportStage2Executor().execute(
        str(job.id),
        {"user_id": str(owner), "report_id": str(victim_report.id), "direction_id": str(uuid.uuid4())},
    )

    assert job.status == "failed"
    assert "报告不存在或非本人" in job.error_message
    save.assert_not_awaited()


async def test_stage2_legit_succeeds(monkeypatch):
    """标准 1b：本人报告 + 方向正常完成。"""
    owner = uuid.uuid4()
    job = _job(owner)
    report = _report(owner, profile_id=None)
    direction = _direction(report.id)
    session = FakeSession(
        job,
        get_map={report.id: report, direction.id: direction},
        execute_values=[_ExecResult(job), _ExecResult(job), _ExecResult(job)],
    )
    monkeypatch.setattr(report_stage2_executor, "AsyncSessionLocal", lambda: session)
    save = _stage2_mocks(monkeypatch)

    await report_stage2_executor.ReportStage2Executor().execute(
        str(job.id),
        {"user_id": str(owner), "report_id": str(report.id), "direction_id": str(direction.id)},
    )

    assert job.status == "succeeded"
    save.assert_awaited_once()


# ---------- 标准 1/1b：plan_regenerate ----------


def _plan_regenerate_mocks(monkeypatch):
    update = AsyncMock()
    monkeypatch.setattr(plan_regenerate_executor, "update_plan", update)
    monkeypatch.setattr(plan_regenerate_executor, "safe_run_graph", AsyncMock(return_value={"report": {}}))
    monkeypatch.setattr(plan_regenerate_executor, "build_plan_regenerate_graph", MagicMock())
    monkeypatch.setattr(plan_regenerate_executor, "get_llm_client", MagicMock())
    monkeypatch.setattr(plan_regenerate_executor, "get_embedding_provider", MagicMock())
    return update


async def test_plan_regenerate_foreign_report_marked_failed(monkeypatch):
    """标准 1：A 的 job 传 params.report_id=B的 → 拒绝。"""
    attacker, victim = uuid.uuid4(), uuid.uuid4()
    job = _job(attacker)
    victim_report = _report(victim)
    monkeypatch.setattr(
        plan_regenerate_executor, "AsyncSessionLocal",
        lambda: FakeSession(job, get_map={victim_report.id: victim_report}),
    )
    update = _plan_regenerate_mocks(monkeypatch)

    await plan_regenerate_executor.PlanRegenerateExecutor().execute(
        str(job.id), {"user_id": str(victim), "report_id": str(victim_report.id)}
    )

    assert job.status == "failed"
    assert "无权" in job.error_message
    update.assert_not_awaited()


async def test_plan_regenerate_legit_succeeds(monkeypatch):
    """标准 1b：本人报告 + 已具备 gap/plan 正常完成。"""
    owner = uuid.uuid4()
    job = _job(owner)
    report = _report(owner, profile_id=None)
    gap = _gap(report.id)
    plan = _plan(report.id)
    session = FakeSession(
        job,
        get_map={report.id: report},
        execute_values=[_ExecResult(job), _ExecResult(gap), _ExecResult(plan), _ExecResult(job), _ExecResult(job)],
    )
    monkeypatch.setattr(plan_regenerate_executor, "AsyncSessionLocal", lambda: session)
    update = _plan_regenerate_mocks(monkeypatch)

    await plan_regenerate_executor.PlanRegenerateExecutor().execute(
        str(job.id), {"user_id": str(owner), "report_id": str(report.id)}
    )

    assert job.status == "succeeded"
    update.assert_awaited_once()


# ---------- 标准 1/1b：plan_reassess（get_with_owner JOIN） ----------


async def test_plan_reassess_foreign_plan_marked_failed_no_record(monkeypatch):
    """标准 1：A 的 job 传 params.plan_id=B的（get_with_owner JOIN 归属=B）→ 拒绝，无重评记录落库。"""
    attacker, victim = uuid.uuid4(), uuid.uuid4()
    job = _job(attacker)
    plan = _plan(uuid.uuid4())
    session = FakeSession(job, execute_values=[_ExecResult(job), _ExecResult((plan, victim))])
    monkeypatch.setattr(plan_reassess_executor, "AsyncSessionLocal", lambda: session)
    gen = AsyncMock()
    monkeypatch.setattr(plan_reassess_executor, "generate_reassessment", gen)

    await plan_reassess_executor.PlanReassessExecutor().execute(str(job.id), {"plan_id": str(plan.id)})

    assert job.status == "failed"
    assert "无权" in job.error_message
    assert session.added == [] # B 无重评记录（不落库副作用）
    gen.assert_not_awaited()


async def test_plan_reassess_legit_succeeds(monkeypatch):
    """标准 1b：本人计划（JOIN 归属 == job.user_id）正常完成重评。"""
    owner = uuid.uuid4()
    job = _job(owner)
    report_id = uuid.uuid4()
    plan = _plan(report_id)
    report = _report(owner, report_id=report_id)
    tasks = [SimpleNamespace(id=uuid.uuid4(), name="t1", stage="short", status="doing")]
    session = FakeSession(
        job,
        get_map={report.id: report},
        execute_values=[
            _ExecResult(job),
            _ExecResult((plan, owner)),
            _ExecResult(tasks),
            _ExecResult([]),
            _ExecResult(job),
            _ExecResult(job),
            _ExecResult(job),
        ],
    )
    monkeypatch.setattr(plan_reassess_executor, "AsyncSessionLocal", lambda: session)
    result = {
        "summary": "重评完成",
        "gap_change": {"summary": "s", "resolved_items": [], "remaining_items": []},
        "plan_adjustment": {"summary": "p", "changes": [], "conflicts": []},
        "stage_checks": {},
        "adjustment_explanation": {"summary": "e", "evidence_refs": []},
    }
    gen = AsyncMock(return_value=result)
    monkeypatch.setattr(plan_reassess_executor, "generate_reassessment", gen)

    await plan_reassess_executor.PlanReassessExecutor().execute(str(job.id), {"plan_id": str(plan.id)})

    assert job.status == "succeeded"
    gen.assert_awaited_once()
    assert job.result == {"plan_id": str(plan.id), "summary": "重评完成"}
