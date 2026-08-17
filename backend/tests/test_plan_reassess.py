"""标准 1：plan_reassess 去 mock 兜底与结果边界测试。

- happy-path：generate_reassessment 正常返回四部分结构 → 任务 succeeded + 重评记录落库；
- 失败接缝：重评组件导入失败（ImportError，注入 _load_reassessment）→ 任务 mark_failed，
  不落库、不输出编造的「差距缩小 N 项」假结果；
- 结果边界：result=None / 非 dict / 缺 summary → 显式失败，不再静默落库默认「重新评估完成」。
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models import TaskJob
from app.tasks.executors import plan_reassess_executor


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
    """执行器测试用最小 AsyncSession 替身（不依赖真实 DB）。

    - get(TaskJob, ...) 恒返回 job；其余 get 从 get_map 取
    - execute() 按顺序消费 execute_values；不足时默认返回 job（_is_cancelled 等任务查询）
    - add/flush/commit 仅记录，不真正落库
    """

    def __init__(self, job, get_map=None, execute_values=None):
        self.job = job
        self.get_map = get_map or {}
        self.execute_values = list(execute_values or [])
        self._i = 0
        self.added = []
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
        pass

    async def commit(self):
        self.commits += 1


def _job(owner_id) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), user_id=owner_id, task_type="plan_reassess", status="running",
        progress=0, stage=None, result=None, result_ref=None, error_message=None,
        celery_task_id=None, trace_id=None, finished_at=None,
    )


def _plan(report_id) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), report_id=report_id)


def _report(owner_id, report_id=None) -> SimpleNamespace:
    return SimpleNamespace(id=report_id or uuid.uuid4(), user_id=owner_id, result={})


def _valid_result() -> dict:
    """feedback-contract v1.2 重评四部分结构（含 summary）。"""
    return {
        "summary": "差距缩小 1 项，短期阶段校验通过",
        "gap_change": {"summary": "s", "resolved_items": [], "remaining_items": []},
        "plan_adjustment": {"summary": "p", "changes": [], "conflicts": []},
        "stage_checks": {},
        "adjustment_explanation": {"summary": "e", "evidence_refs": []},
    }


def _session_until_load(job, plan, report) -> FakeSession:
    """构造能走到「延迟导入 + 调用重评」的会话（7 次 execute 恰好消费完）。"""
    tasks = [SimpleNamespace(id=uuid.uuid4(), name="t1", stage="short", status="doing")]
    return FakeSession(
        job,
        get_map={report.id: report},
        execute_values=[
            _ExecResult(job), # _update_progress(10) → _is_cancelled
            _ExecResult((plan, job.user_id)), # get_with_owner
            _ExecResult(tasks), # get_tasks
            _ExecResult([]), # list_by_plan
            _ExecResult(job), # _update_progress(40)
            _ExecResult(job), # _update_progress(80)
            _ExecResult(job), # _is_cancelled（成功落库前）
        ],
    )


def _session_until_failed(job, plan, report) -> FakeSession:
    """构造能走到 mark_failed 分支的会话（ImportError/结果畸形前只需 5 次 execute）。"""
    tasks = [SimpleNamespace(id=uuid.uuid4(), name="t1", stage="short", status="doing")]
    return FakeSession(
        job,
        get_map={report.id: report},
        execute_values=[
            _ExecResult(job), # _update_progress(10)
            _ExecResult((plan, job.user_id)), # get_with_owner
            _ExecResult(tasks), # get_tasks
            _ExecResult([]), # list_by_plan
            _ExecResult(job), # _update_progress(40)
        ],
    )


# ---------- 标准 1：happy-path ----------


async def test_plan_reassess_happy_path_persists(monkeypatch):
    """：generate_reassessment 正常返回 → 任务 succeeded + 重评记录落库（含 summary）。"""
    owner = uuid.uuid4()
    job = _job(owner)
    plan = _plan(uuid.uuid4())
    report = _report(owner, report_id=plan.report_id)
    session = _session_until_load(job, plan, report)
    monkeypatch.setattr(plan_reassess_executor, "AsyncSessionLocal", lambda: session)
    gen = AsyncMock(return_value=_valid_result())
    monkeypatch.setattr(plan_reassess_executor, "generate_reassessment", gen)

    await plan_reassess_executor.PlanReassessExecutor().execute(str(job.id), {"plan_id": str(plan.id)})

    assert job.status == "succeeded"
    gen.assert_awaited_once()
    assert job.result == {"plan_id": str(plan.id), "summary": "差距缩小 1 项，短期阶段校验通过"}
    assert len(session.added) == 1 # 重评记录仅成功时落库
    assert session.added[0].summary == "差距缩小 1 项，短期阶段校验通过"
    assert session.added[0].result == _valid_result()


# ---------- 标准 1：ImportError 失败接缝 ----------


async def test_plan_reassess_import_error_marks_failed_no_record(monkeypatch):
    """失败接缝：注入 ImportError → 任务 failed，不落库、不输出假结果。"""
    owner = uuid.uuid4()
    job = _job(owner)
    plan = _plan(uuid.uuid4())
    report = _report(owner, report_id=plan.report_id)
    session = _session_until_failed(job, plan, report)
    monkeypatch.setattr(plan_reassess_executor, "AsyncSessionLocal", lambda: session)

    def _raise_import_error():
        raise ImportError("mock: 重评组件缺失")

    monkeypatch.setattr(plan_reassess_executor, "_load_reassessment", _raise_import_error)

    await plan_reassess_executor.PlanReassessExecutor().execute(str(job.id), {"plan_id": str(plan.id)})

    assert job.status == "failed"
    assert "组件不可用" in job.error_message
    assert session.added == [] # 不落库
    assert "差距缩小" not in (job.error_message or "")


# ---------- 标准 1：result 边界（不再静默落库默认 summary） ----------


async def test_plan_reassess_result_none_marks_failed_no_record(monkeypatch):
    """：result=None → 显式失败，不再静默落库「重新评估完成」。"""
    owner = uuid.uuid4()
    job = _job(owner)
    plan = _plan(uuid.uuid4())
    report = _report(owner, report_id=plan.report_id)
    session = _session_until_failed(job, plan, report)
    monkeypatch.setattr(plan_reassess_executor, "AsyncSessionLocal", lambda: session)
    gen = AsyncMock(return_value=None)
    monkeypatch.setattr(plan_reassess_executor, "generate_reassessment", gen)

    await plan_reassess_executor.PlanReassessExecutor().execute(str(job.id), {"plan_id": str(plan.id)})

    assert job.status == "failed"
    assert "结果格式无效" in job.error_message
    assert session.added == []
    assert job.result is None # 未写成功结果


async def test_plan_reassess_result_non_dict_marks_failed_no_record(monkeypatch):
    """：result 非 dict → 显式失败，不落库。"""
    owner = uuid.uuid4()
    job = _job(owner)
    plan = _plan(uuid.uuid4())
    report = _report(owner, report_id=plan.report_id)
    session = _session_until_failed(job, plan, report)
    monkeypatch.setattr(plan_reassess_executor, "AsyncSessionLocal", lambda: session)
    gen = AsyncMock(return_value="not-a-dict")
    monkeypatch.setattr(plan_reassess_executor, "generate_reassessment", gen)

    await plan_reassess_executor.PlanReassessExecutor().execute(str(job.id), {"plan_id": str(plan.id)})

    assert job.status == "failed"
    assert "结果格式无效" in job.error_message
    assert session.added == []


async def test_plan_reassess_result_missing_summary_marks_failed_no_record(monkeypatch):
    """：result 为 dict 但缺 summary → 显式失败，不落库默认文案。"""
    owner = uuid.uuid4()
    job = _job(owner)
    plan = _plan(uuid.uuid4())
    report = _report(owner, report_id=plan.report_id)
    session = _session_until_failed(job, plan, report)
    monkeypatch.setattr(plan_reassess_executor, "AsyncSessionLocal", lambda: session)
    gen = AsyncMock(
        return_value={"gap_change": {}, "plan_adjustment": {}, "stage_checks": {}, "adjustment_explanation": {}}
    )
    monkeypatch.setattr(plan_reassess_executor, "generate_reassessment", gen)

    await plan_reassess_executor.PlanReassessExecutor().execute(str(job.id), {"plan_id": str(plan.id)})

    assert job.status == "failed"
    assert "缺少摘要" in job.error_message
    assert session.added == []
