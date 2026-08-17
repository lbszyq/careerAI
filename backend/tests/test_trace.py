"""任务级 Trace 与指标闭环测试（不依赖真实 DB，全部 mock）。

覆盖：trace_id 传播 / span 父子关系 / 失败定位 / token+成本汇总 / span 写失败隔离 /
并发两任务 span 不串线 / 孤儿 span 回写 / 超时取消 orphan 处理 / trace 端点所有权校验 /
metrics 按用户聚合与空数据 0 值。
"""
import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from helpers import make_token, make_user

import app.ai.runner as runner
import app.tasks.workers as workers
from app.ai.agents.deps import AgentDeps
from app.ai.graphs.stage1 import _wrap, build_stage1_graph
from app.ai.schemas import initial_state
from app.models.task_job import TaskJob
from app.models.trace_span import TraceSpan
from app.observability import tracer
from app.observability.tracer import (
    finish_span,
    get_trace_id,
    record_llm_span,
    record_rag_span,
    reset_trace_context,
    sanitize_error,
    set_trace_context,
    start_agent_span,
    start_task_span,
    write_span,
)
from app.repositories.task_job_repository import TaskJobRepository
from app.repositories.user_repository import UserRepository
from app.routers.metrics import compute_metrics_summary
from app.tasks.executors import ai_base
from app.tasks.executors.ai_base import safe_run_graph

# ---------- 测试辅助 ----------


class FakeSpanStore:
    """内存 span 存储：替换 tracer.AsyncSessionLocal，验证写入/父子关系/状态。"""

    def __init__(self):
        self.spans = []

    def factory(self):
        return _FakeSession(self)

    def get(self, span_id):
        for s in self.spans:
            if str(s.id) == str(span_id):
                return s
        return None


class _FakeSession:
    def __init__(self, store):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.store.spans.append(obj)

    async def commit(self):
        return None

    async def get(self, model, pk):
        return self.store.get(pk)


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _ScalarList:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _ExecuteResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _ScalarList(self._items)


class _SeqScalarSession:
    def __init__(self, values):
        self._values = list(values)
        self._i = 0

    async def execute(self, stmt):
        value = self._values[self._i]
        self._i += 1
        return _Scalar(value)


class _CancelLike(BaseException):
    """模拟 asyncio.CancelledError（同为 BaseException，非 Exception）的取消信号。"""


def _span(**kwargs) -> TraceSpan:
    defaults = dict(
        id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        span_type="task",
        name="span",
        status="succeeded",
        duration_ms=0,
        tokens=0,
        cost=0.0,
        hit_count=0,
        created_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return TraceSpan(**defaults)


# ---------- 1. 模型 / 迁移 schema ----------


def test_task_job_has_trace_id_column():
    col = TaskJob.__table__.columns.get("trace_id")
    assert col is not None, "task_jobs 缺 trace_id 列"
    assert col.nullable is True, "历史任务 trace_id 应为可空（NULL）"


def test_trace_span_has_contract_fields():
    cols = set(TraceSpan.__table__.columns.keys())
    required = {
        "id", "trace_id", "parent_span_id", "span_type", "name", "status",
        "error_message", "duration_ms", "tokens", "cost", "hit_count", "created_at",
    }
    assert required <= cols, f"trace_spans 缺契约字段：{required - cols}"


def test_trace_id_index_not_unique():
    for idx in TraceSpan.__table__.indexes:
        if idx.name == "ix_trace_spans_trace_id":
            assert idx.unique is False, "trace_id 索引不得 UNIQUE（一对多）"
            return
    pytest.fail("trace_spans 缺少 trace_id 索引")


# ---------- 2. tracer：span 写入 / 脱敏 / 隔离 ----------


async def test_write_span_creates_row_and_sanitizes_error(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    tid = str(uuid.uuid4())
    long_err = 'secret sk-abcdef1234567890 api_key=REALSECRET {"token":"TOKVAL"} ' + "x" * 600
    span = await write_span(
        trace_id=tid,
        parent_span_id=None,
        span_type="llm",
        name="n",
        status="failed",
        duration_ms=10,
        tokens=100,
        cost=0.5,
        error_message=long_err,
    )
    assert span is not None
    assert len(span.error_message) <= 500
    assert "sk-abcdef1234567890" not in span.error_message
    assert "REALSECRET" not in span.error_message
    assert "TOKVAL" not in span.error_message
    assert "sk-***" in span.error_message
    assert span.tokens == 100
    assert span.cost == 0.5
    assert str(span.trace_id) == tid


async def test_write_span_swallows_db_failure(monkeypatch):
    class Failing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, obj):
            raise RuntimeError("db down")

    monkeypatch.setattr(tracer, "AsyncSessionLocal", lambda: Failing())
    span = await write_span(
        trace_id=str(uuid.uuid4()), parent_span_id=None, span_type="task", name="x", status="running"
    )
    assert span is None # 吞异常，不抛出


async def test_finish_span_updates_status(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    span = await start_task_span("task:1", trace_id=str(uuid.uuid4()))
    await finish_span(str(span.id), status="succeeded", duration_ms=42)
    stored = store.get(span.id)
    assert stored.status == "succeeded"
    assert stored.duration_ms == 42


async def test_finish_span_idempotent_does_not_overwrite_terminal(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    span = await start_task_span("task:1", trace_id=str(uuid.uuid4()))
    await finish_span(str(span.id), status="failed", duration_ms=10)
    await finish_span(str(span.id), status="succeeded", duration_ms=20) # 已终态，不覆盖
    stored = store.get(span.id)
    assert stored.status == "failed"
    assert stored.duration_ms == 10


async def test_record_rag_span_writes_hit_count(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    tid = str(uuid.uuid4())
    tokens = set_trace_context(tid, None)
    try:
        await record_rag_span(name="search_market", status="succeeded", duration_ms=12, hit_count=5)
    finally:
        reset_trace_context(tokens)
    rag = next(s for s in store.spans if s.span_type == "rag")
    assert rag.hit_count == 5
    assert str(rag.trace_id) == tid


def test_sanitize_error_truncates_and_redacts():
    out = sanitize_error(
        'api_key=SECRET token=TOK123 Bearer abcdef {"password":"P@ss"} ' + "x" * 1000
    )
    assert len(out) <= 500
    assert "SECRET" not in out
    assert "TOK123" not in out
    assert "P@ss" not in out
    assert "Bearer ***" in out


def test_sanitize_error_none():
    assert sanitize_error(None) is None


async def test_trace_context_concurrent_isolation():
    async def worker(tid):
        tokens = set_trace_context(tid)
        try:
            await asyncio.sleep(0)
            return get_trace_id()
        finally:
            reset_trace_context(tokens)

    r1, r2 = await asyncio.gather(worker("trace-a"), worker("trace-b"))
    assert r1 == "trace-a"
    assert r2 == "trace-b"


async def test_concurrent_spans_do_not_mix(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)

    async def run_trace(tid):
        tokens = set_trace_context(tid, None)
        try:
            await start_agent_span("agent")
            await record_llm_span(name="llm", status="succeeded", duration_ms=1, tokens=10, cost=0.01)
        finally:
            reset_trace_context(tokens)

    tid1, tid2 = str(uuid.uuid4()), str(uuid.uuid4())
    await asyncio.gather(run_trace(tid1), run_trace(tid2))
    for s in store.spans:
        assert str(s.trace_id) in (tid1, tid2), "并发 span trace_id 串线"
    t1 = [s for s in store.spans if str(s.trace_id) == tid1]
    t2 = [s for s in store.spans if str(s.trace_id) == tid2]
    assert len(t1) == 2 and len(t2) == 2


# ---------- 3. worker：task root span 统一写入 + 回写 ----------


async def test_worker_writes_task_span_succeeded(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    monkeypatch.setattr(workers, "_job_status", AsyncMock(return_value="succeeded"))
    tid = str(uuid.uuid4())

    class OkExecutor:
        async def execute(self, job_id, params):
            return None

    await workers._run_with_trace(OkExecutor(), "job-id", {}, tid)
    task_span = next(s for s in store.spans if s.span_type == "task")
    assert str(task_span.trace_id) == tid
    assert task_span.status == "succeeded"
    assert task_span.parent_span_id is None


async def test_worker_marks_task_span_failed_on_executor_error(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)

    class BoomExecutor:
        async def execute(self, job_id, params):
            raise RuntimeError("boom")

    tid = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        await workers._run_with_trace(BoomExecutor(), "job-id", {}, tid)
    task_span = next(s for s in store.spans if s.span_type == "task")
    assert task_span.status == "failed"
    assert "boom" in task_span.error_message


async def test_worker_marks_task_span_failed_when_job_status_failed(monkeypatch):
    """executor 内部 mark_failed 后正常返回（safe_run_graph 返回 None）：终态以 task_jobs.status 为准。"""
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    monkeypatch.setattr(workers, "_job_status", AsyncMock(return_value="failed"))

    class SilentFailExecutor:
        async def execute(self, job_id, params):
            return None # 内部已 mark_failed，但不抛异常

    await workers._run_with_trace(SilentFailExecutor(), "job-id", {}, str(uuid.uuid4()))
    task_span = next(s for s in store.spans if s.span_type == "task")
    assert task_span.status == "failed"


async def test_worker_span_write_failure_isolated(monkeypatch):
    """span 写入失败不影响任务成功路径。"""

    class Failing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, obj):
            raise RuntimeError("db down")

    monkeypatch.setattr(tracer, "AsyncSessionLocal", lambda: Failing())
    monkeypatch.setattr(workers, "_job_status", AsyncMock(return_value="succeeded"))

    class OkExecutor:
        async def execute(self, job_id, params):
            return None

    # 不抛异常 = 任务成功
    await workers._run_with_trace(OkExecutor(), "job-id", {}, str(uuid.uuid4()))


async def test_ensure_trace_id_writes_back_on_missing(monkeypatch):
    """trace_id 缺失（历史 NULL）时生成并回写 task_jobs.trace_id，避免孤儿 span。"""
    job = SimpleNamespace(trace_id=None)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, model, pk):
            return job

        async def commit(self):
            return None

    import app.db.base as db

    monkeypatch.setattr(db, "AsyncSessionLocal", lambda: FakeSession())
    job_id = str(uuid.uuid4())
    tid = await workers._ensure_trace_id(job_id, None)
    assert tid is not None
    assert job.trace_id is not None
    assert str(job.trace_id) == tid


async def test_ensure_trace_id_returns_provided():
    tid = str(uuid.uuid4())
    assert await workers._ensure_trace_id("job-id", tid) == tid


async def test_full_chain_task_agent_llm_parent(monkeypatch):
    """端到端：worker 写 task root span → _wrap 写 agent span → llm span，parent 链可回溯 root。"""
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    monkeypatch.setattr(workers, "_job_status", AsyncMock(return_value="succeeded"))
    tid = str(uuid.uuid4())

    async def node_fn(state, deps):
        await record_llm_span(name="llm", status="succeeded", duration_ms=5, tokens=7, cost=0.01)
        return {"done": True}

    wrapped = _wrap(AgentDeps(), node_fn, "my_node", {})

    class FakeExecutor:
        async def execute(self, job_id, params):
            await wrapped({})

    await workers._run_with_trace(FakeExecutor(), "job", {}, tid)
    spans = store.spans
    task = next(s for s in spans if s.span_type == "task")
    agent = next(s for s in spans if s.span_type == "agent")
    llm = next(s for s in spans if s.span_type == "llm")
    assert str(task.trace_id) == str(agent.trace_id) == str(llm.trace_id) == tid
    assert agent.parent_span_id == task.id
    assert llm.parent_span_id == agent.id


# ---------- 4. safe_run_graph / _wrap：agent span + 失败定位 + 取消 ----------


async def test_safe_run_graph_marks_failed_on_graph_error(monkeypatch):
    monkeypatch.setattr(runner, "run_graph", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(ai_base.AIExecutor, "_mark_failed", AsyncMock())
    result = await safe_run_graph(AsyncMock(), "job-id", object(), {})
    assert result is None
    ai_base.AIExecutor._mark_failed.assert_awaited_once()


async def test_wrap_node_success_writes_agent_span(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    deps = AgentDeps()

    async def ok_node(state, deps):
        return {"result": 1}

    wrapped = _wrap(deps, ok_node, "ok_node", {})
    tid = str(uuid.uuid4())
    tokens = set_trace_context(tid, None)
    try:
        result = await wrapped({"stage_errors": []})
    finally:
        reset_trace_context(tokens)
    assert result == {"result": 1}
    agent = next(s for s in store.spans if s.span_type == "agent")
    assert agent.status == "succeeded"
    assert agent.name == "ok_node"
    assert str(agent.trace_id) == tid


async def test_wrap_uses_explicit_deps_trace_context(monkeypatch):
    """AgentDeps.trace_id/parent_span_id 被真正使用（显式覆盖 contextvars）。"""
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    deps = AgentDeps(trace_id=str(uuid.uuid4()), parent_span_id=str(uuid.uuid4()))

    async def ok_node(state, deps):
        return {"result": 1}

    wrapped = _wrap(deps, ok_node, "ok_node", {})
    result = await wrapped({"stage_errors": []}) # 不设 contextvar，走 deps 显式值
    assert result == {"result": 1}
    agent = next(s for s in store.spans if s.span_type == "agent")
    assert str(agent.trace_id) == deps.trace_id
    assert agent.parent_span_id == uuid.UUID(deps.parent_span_id)


async def test_wrap_node_failure_writes_failed_agent_span(monkeypatch):
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    deps = AgentDeps()

    async def boom(state, deps):
        raise ValueError("boom error")

    wrapped = _wrap(deps, boom, "boom_node", {})
    tokens = set_trace_context(str(uuid.uuid4()), None)
    try:
        result = await wrapped({"stage_errors": []})
    finally:
        reset_trace_context(tokens)
    # 节点失败不向外抛（节点容错解耦）
    assert "boom_node" in result["stage_errors"][0]
    agent = next(s for s in store.spans if s.span_type == "agent")
    assert agent.status == "failed"
    assert "boom error" in agent.error_message


async def test_wrap_node_cancelled_marks_agent_span_failed(monkeypatch):
    """超时取消（BaseException）时 agent span 标 failed，不留孤儿 running span。"""
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    deps = AgentDeps()

    async def cancelled(state, deps):
        raise _CancelLike()

    wrapped = _wrap(deps, cancelled, "c_node", {})
    tokens = set_trace_context(str(uuid.uuid4()), None)
    try:
        with pytest.raises(_CancelLike):
            await wrapped({"stage_errors": []})
    finally:
        reset_trace_context(tokens)
    agent = next(s for s in store.spans if s.span_type == "agent")
    assert agent.status == "failed"
    assert "取消" in agent.error_message


async def test_stage1_graph_parallel_nodes_parent(monkeypatch):
    """真实 build_stage1_graph：并行节点（career_analysis ∥ market）agent span 均归属 task root span。"""
    store = FakeSpanStore()
    monkeypatch.setattr(tracer, "AsyncSessionLocal", store.factory)
    # 全 fallback（llm/embedding/db 均 None），图不触外部依赖
    deps = AgentDeps(llm=None, embedding=None, db=None)
    graph = build_stage1_graph(deps)
    tid = str(uuid.uuid4())
    task_span = await start_task_span("task:job", trace_id=tid)
    tokens = set_trace_context(tid, str(task_span.id))
    try:
        state = initial_state(
            profile={
                "name": "测试", "major": "计算机", "education": "本科",
                "graduation_year": 2026, "skills": ["python"],
            },
            preferred_cities=["北京"], preferred_industries=["互联网"],
            stage="stage1",
        )
        await graph.ainvoke(state)
    finally:
        reset_trace_context(tokens)
    agent_spans = [s for s in store.spans if s.span_type == "agent"]
    names = {s.name for s in agent_spans}
    assert {"router_node", "career_analysis_node", "market_research_node", "planner_node"} <= names
    for s in agent_spans:
        assert str(s.trace_id) == tid
        assert s.parent_span_id == task_span.id, f"{s.name} parent 未归属 task root span"


# ---------- 5. trace 端点：所有权校验 / 空列表 / 返回 span ----------


def test_trace_not_found_returns_4001(client, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(TaskJobRepository, "get_by_id", AsyncMock(return_value=None))
    resp = client.get(
        f"/api/v1/tasks/{uuid.uuid4()}/trace", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 4001


def test_trace_not_owned_returns_1002(client, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    job = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), trace_id=uuid.uuid4())
    monkeypatch.setattr(TaskJobRepository, "get_by_id", AsyncMock(return_value=job))
    resp = client.get(
        f"/api/v1/tasks/{job.id}/trace", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 1002


def test_trace_empty_when_trace_id_null(client, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    job = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, trace_id=None)
    monkeypatch.setattr(TaskJobRepository, "get_by_id", AsyncMock(return_value=job))
    resp = client.get(
        f"/api/v1/tasks/{job.id}/trace", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_trace_returns_spans(client, fake_db, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    trace_id = uuid.uuid4()
    job = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, trace_id=trace_id)
    monkeypatch.setattr(TaskJobRepository, "get_by_id", AsyncMock(return_value=job))
    span = _span(trace_id=trace_id, span_type="llm", name="market_research_node", tokens=120, cost=0.03)
    fake_db.execute = AsyncMock(return_value=_ExecuteResult([span]))
    resp = client.get(
        f"/api/v1/tasks/{job.id}/trace", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["span_type"] == "llm"
    assert data[0]["trace_id"] == str(trace_id)
    assert data[0]["tokens"] == 120


# ---------- 6. create → worker：同一 trace_id 端到端 ----------


async def test_create_and_dispatch_passes_same_trace_id(monkeypatch):
    from app.services import task_service as ts_module
    from app.services.task_service import TaskService

    job = SimpleNamespace(id=uuid.uuid4(), trace_id=None, celery_task_id=None)
    repo = MagicMock()
    repo.create = AsyncMock(return_value=job)
    session = AsyncMock()
    session.commit = AsyncMock()
    service = TaskService(session)
    service.job_repo = repo

    fake_result = MagicMock()
    fake_result.id = "celery-123"
    fake_run = MagicMock()
    fake_run.delay = MagicMock(return_value=fake_result)
    monkeypatch.setattr(ts_module, "run_task_job", fake_run)

    user = make_user()
    returned = await service.create_and_dispatch(user, "report_stage1", {"profile_id": "x"})

    assert returned.trace_id is not None
    delay_args = fake_run.delay.call_args[0]
    assert delay_args[0] == str(job.id) # job_id
    assert delay_args[3] == str(returned.trace_id) # 同一 trace_id 显式传入 worker


# ---------- 7. metrics：按用户聚合 / 空数据 0 值 ----------


async def test_compute_metrics_empty_returns_zeros():
    sess = _SeqScalarSession([0, 0, 0.0, 0, 0.0])
    data = await compute_metrics_summary(sess, uuid.uuid4())
    assert data == {
        "task_completion_rate": 0.0,
        "avg_duration_ms": 0.0,
        "total_tokens": 0,
        "total_cost": 0.0,
    }


async def test_compute_metrics_aggregates():
    sess = _SeqScalarSession([10, 8, 1500.0, 12000, 0.45])
    data = await compute_metrics_summary(sess, uuid.uuid4())
    assert data["task_completion_rate"] == 0.8
    assert data["avg_duration_ms"] == 1500.0
    assert data["total_tokens"] == 12000
    assert data["total_cost"] == 0.45


def test_metrics_endpoint_empty_returns_zeros(client, fake_db, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    fake_db.execute = AsyncMock(
        side_effect=[_Scalar(0), _Scalar(0), _Scalar(0.0), _Scalar(0), _Scalar(0.0)]
    )
    resp = client.get("/api/v1/metrics/summary", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "task_completion_rate": 0.0,
        "avg_duration_ms": 0.0,
        "total_tokens": 0,
        "total_cost": 0.0,
    }


def test_metrics_endpoint_aggregates(client, fake_db, monkeypatch):
    user = make_user()
    token = make_token(user.id)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    fake_db.execute = AsyncMock(
        side_effect=[_Scalar(4), _Scalar(3), _Scalar(200.0), _Scalar(500), _Scalar(0.25)]
    )
    resp = client.get("/api/v1/metrics/summary", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task_completion_rate"] == 0.75
    assert data["avg_duration_ms"] == 200.0
    assert data["total_tokens"] == 500
    assert data["total_cost"] == 0.25
