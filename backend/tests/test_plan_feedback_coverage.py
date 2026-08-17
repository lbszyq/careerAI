"""成果覆盖参与进度与阶段：计划详情/进度口径 + 重评阶段校验 + 回退测试。"""
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.services.feedback_service as feedback_service_module
from app.ai.reassessment import _build_stage_checks, _normalize_inputs
from app.schemas.feedback import AchievementOut
from app.services import plan_service as plan_service_module
from app.services.plan_service import PlanService


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), username="tester")


def _plan() -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        report_id=uuid.uuid4(),
        gap_analysis_id=None,
        target_job=None,
        stages={},
        created_at=now,
        updated_at=now,
        progress=0,
    )


def _task(task_id: uuid.UUID | None = None, status: str = "todo", stage: str = "short", name: str = "任务") -> SimpleNamespace:
    return SimpleNamespace(
        id=task_id or uuid.uuid4(),
        name=name,
        resource=None,
        duration=None,
        stage=stage,
        status=status,
        sort_order=1,
        acceptance_criteria=None,
    )


def _achievement(task_id: uuid.UUID) -> AchievementOut:
    now = datetime.now(UTC)
    return AchievementOut(
        id=uuid.uuid4(),
        plan_id=uuid.uuid4(),
        name="成果",
        url="https://example.com",
        description=None,
        stage="short",
        task_id=task_id,
        created_at=now,
        updated_at=now,
    )


def _svc(plan, tasks) -> PlanService:
    svc = PlanService(AsyncMock())
    svc.plan_repo = SimpleNamespace(
        get_owned=AsyncMock(return_value=plan),
        get_tasks=AsyncMock(return_value=tasks),
        get_gap_target_job=AsyncMock(return_value=None),
    )
    svc._report_task_acceptance = AsyncMock(return_value={})
    return svc


def _patch_feedback(monkeypatch, echo) -> None:
    class _FakeFeedbackService:
        def __init__(self, session):
            self.session = session

        async def build_plan_echo(self, user, plan):
            return echo

    monkeypatch.setattr(feedback_service_module, "FeedbackService", _FakeFeedbackService)


def _patch_achievement_repo(monkeypatch, achievements) -> None:
    class _FakeAchievementRepository:
        def __init__(self, session):
            pass

        async def list_by_plan(self, plan_id):
            return achievements

    monkeypatch.setattr(plan_service_module, "AchievementRepository", _FakeAchievementRepository)


# ---------- 标准 1：计划详情 covered_by_achievement + done ∪ covered 进度 ----------


async def test_get_plan_marks_covered_and_progress_done_union_covered(monkeypatch):
    plan = _plan()
    t1 = _task(status="done", name="t1")
    t2 = _task(status="doing", name="t2")
    t3 = _task(status="done", name="t3")
    t4 = _task(status="todo", name="t4")
    t5 = _task(status="todo", name="t5")
    tasks = [t1, t2, t3, t4, t5]
    achievements = [_achievement(t2.id), _achievement(t3.id), _achievement(t3.id)] # t3 多个成果只计一次
    echo = {
        "achievements": achievements,
        "reassess_eligible": True,
        "reassess_eligible_reason": None,
        "latest_reassess": None,
        "completion_checks": {},
    }
    _patch_feedback(monkeypatch, echo)
    svc = _svc(plan, tasks)

    out = await svc.get_plan(_user(), plan.id)

    assert out.progress == 60 # |done={t1,t3} ∪ covered={t2,t3}| = 3 / 5
    flags = {str(t.id): t.covered_by_achievement for t in out.tasks}
    assert flags[str(t1.id)] is False
    assert flags[str(t2.id)] is True
    assert flags[str(t3.id)] is True
    assert flags[str(t4.id)] is False
    assert flags[str(t5.id)] is False


async def test_get_plan_without_achievements_preserves_original_progress(monkeypatch):
    plan = _plan()
    tasks = [_task(status="done", name="t1"), _task(status="todo", name="t2"), _task(status="todo", name="t3")]
    echo = {
        "achievements": [],
        "reassess_eligible": False,
        "reassess_eligible_reason": "请先上传成果或标记任务进度",
        "latest_reassess": None,
        "completion_checks": {},
    }
    _patch_feedback(monkeypatch, echo)
    svc = _svc(plan, tasks)

    out = await svc.get_plan(_user(), plan.id)

    assert out.progress == 33 # 仅 done 计数，与原逻辑一致
    assert all(not t.covered_by_achievement for t in out.tasks)


# ---------- 标准 1/4：进度端点同口径 + 删除/解除关联回退 ----------


async def test_get_progress_uses_done_union_covered_and_rolls_back(monkeypatch):
    plan = _plan()
    t1 = _task(status="done", name="t1")
    t2 = _task(status="doing", name="t2")
    t3 = _task(status="todo", name="t3")
    t4 = _task(status="todo", name="t4")
    t5 = _task(status="todo", name="t5")
    tasks = [t1, t2, t3, t4, t5]
    achievements = [_achievement(t2.id)]
    _patch_achievement_repo(monkeypatch, achievements)
    svc = _svc(plan, tasks)

    out = await svc.get_progress(_user(), plan.id)

    assert out.progress == 40 # |done={t1} ∪ covered={t2}| = 2 / 5
    assert out.done_tasks == 1
    assert out.covered_tasks == 1
    assert out.effective_done_tasks == 2
    assert out.stages["short"] == {"total": 5, "done": 1, "covered": 1, "effective_done": 2}

    # 删除成果 / PATCH task_id=null 解除关联后，任务恢复未覆盖，进度回退
    achievements.clear()
    out2 = await svc.get_progress(_user(), plan.id)

    assert out2.progress == 20
    assert out2.covered_tasks == 0
    assert out2.effective_done_tasks == 1
    assert out2.stages["short"]["effective_done"] == 1


# ---------- 标准 2/3：多成果/单成果重指派/空任务/解除关联 ----------


async def test_get_progress_multiple_achievements_same_task_count_once(monkeypatch):
    plan = _plan()
    t1 = _task(status="todo", name="t1")
    t2 = _task(status="todo", name="t2")
    tasks = [t1, t2]
    achievements = [_achievement(t1.id), _achievement(t1.id)] # 一个任务多个成果，覆盖只计一次
    _patch_achievement_repo(monkeypatch, achievements)
    svc = _svc(plan, tasks)

    out = await svc.get_progress(_user(), plan.id)

    assert out.progress == 50 # |done∪covered| = {t1} / 2
    assert out.covered_tasks == 1
    assert out.effective_done_tasks == 1
    assert out.stages["short"]["covered"] == 1


async def test_get_progress_delete_one_of_multiple_achievements_keeps_cover_until_last_removed(monkeypatch):
    plan = _plan()
    t1 = _task(status="todo", name="t1")
    tasks = [t1]
    achievements = [_achievement(t1.id), _achievement(t1.id)]
    _patch_achievement_repo(monkeypatch, achievements)
    svc = _svc(plan, tasks)

    assert (await svc.get_progress(_user(), plan.id)).progress == 100

    # 删除其中 1 条成果：任务仍被另一条成果覆盖，不回退
    achievements.pop()
    out2 = await svc.get_progress(_user(), plan.id)
    assert out2.progress == 100
    assert out2.covered_tasks == 1

    # 删除最后 1 条成果：覆盖回退
    achievements.pop()
    out3 = await svc.get_progress(_user(), plan.id)
    assert out3.progress == 0
    assert out3.covered_tasks == 0
    assert out3.effective_done_tasks == 0


async def test_single_achievement_reassignment_moves_coverage_not_accumulates(monkeypatch):
    """契约：一个成果最多关联一个任务（task_id 单值）。重指派后旧任务回退、新任务覆盖，不累积成多任务。"""
    plan = _plan()
    t1 = _task(status="todo", stage="short", name="t1")
    t2 = _task(status="todo", stage="mid", name="t2")
    tasks = [t1, t2]
    ach = _achievement(t1.id)
    _patch_achievement_repo(monkeypatch, [ach])
    svc = _svc(plan, tasks)

    out = await svc.get_progress(_user(), plan.id)
    assert out.stages["short"]["covered"] == 1
    assert out.stages["mid"]["covered"] == 0

    # PATCH task_id=t2 后：t1 不再被覆盖，t2 被覆盖，整体 covered_tasks 仍为 1
    ach.task_id = t2.id
    out2 = await svc.get_progress(_user(), plan.id)

    assert out2.stages["short"]["covered"] == 0
    assert out2.stages["mid"]["covered"] == 1
    assert out2.covered_tasks == 1
    assert out2.effective_done_tasks == 1


async def test_get_progress_task_id_null_rolls_back(monkeypatch):
    plan = _plan()
    t1 = _task(status="todo", name="t1")
    tasks = [t1]
    ach = _achievement(t1.id)
    _patch_achievement_repo(monkeypatch, [ach])
    svc = _svc(plan, tasks)

    assert (await svc.get_progress(_user(), plan.id)).progress == 100

    # PATCH task_id=null 解除关联：恢复未覆盖
    ach.task_id = None
    out = await svc.get_progress(_user(), plan.id)

    assert out.progress == 0
    assert out.covered_tasks == 0
    assert out.stages["short"]["effective_done"] == 0


async def test_get_progress_empty_tasks_returns_zero(monkeypatch):
    plan = _plan()
    _patch_achievement_repo(monkeypatch, [_achievement(uuid.uuid4())]) # 成果无匹配任务
    svc = _svc(plan, [])

    out = await svc.get_progress(_user(), plan.id)

    assert out.progress == 0
    assert out.total_tasks == 0
    assert out.covered_tasks == 0
    assert out.effective_done_tasks == 0
    assert out.stages["short"] == {"total": 0, "done": 0, "covered": 0, "effective_done": 0}


# ---------- 标准 2/3/4：重评阶段校验覆盖语义与回退 ----------


def test_reassessment_stage_check_covered_task_equivalent_done():
    _gap_items, tasks_by_stage, achievements_by_stage, _pool, _tasks_by_id, _achievements = _normalize_inputs(
        {},
        [{"id": "t1", "name": "任务1", "stage": "short", "status": "todo"}],
        [{"id": "a1", "name": "成果", "url": "https://example.com", "description": None, "stage": "short", "task_id": "t1"}],
    )

    checks = _build_stage_checks(tasks_by_stage, achievements_by_stage)

    assert checks["short"]["result"] == "pass"
    assert "未完成任务" not in checks["short"]["reason"]


def test_reassessment_stage_check_multiple_achievements_count_once():
    _gap_items, tasks_by_stage, achievements_by_stage, _pool, _tasks_by_id, _achievements = _normalize_inputs(
        {},
        [{"id": "t1", "name": "任务1", "stage": "short", "status": "doing"}],
        [
            {"id": "a1", "name": "成果1", "url": "https://example.com", "description": None, "stage": "short", "task_id": "t1"},
            {"id": "a2", "name": "成果2", "url": "https://example.com/2", "description": None, "stage": "short", "task_id": "t1"},
        ],
    )

    checks = _build_stage_checks(tasks_by_stage, achievements_by_stage)

    assert checks["short"]["result"] == "pass"


def test_reassessment_stage_check_mixed_done_and_covered_passes():
    _gap_items, tasks_by_stage, achievements_by_stage, _pool, _tasks_by_id, _achievements = _normalize_inputs(
        {},
        [
            {"id": "t1", "name": "任务1", "stage": "short", "status": "done"},
            {"id": "t2", "name": "任务2", "stage": "short", "status": "todo"},
        ],
        [{"id": "a1", "name": "成果", "url": "https://example.com", "description": None, "stage": "short", "task_id": "t2"}],
    )

    checks = _build_stage_checks(tasks_by_stage, achievements_by_stage)

    assert checks["short"]["result"] == "pass"
    assert "未完成任务" not in checks["short"]["reason"]


def test_reassessment_stage_check_uncovered_doing_still_fail():
    _gap_items, tasks_by_stage, achievements_by_stage, _pool, _tasks_by_id, _achievements = _normalize_inputs(
        {},
        [{"id": "t1", "name": "任务1", "stage": "short", "status": "doing"}],
        [{"id": "a1", "name": "成果", "url": "https://example.com", "description": None, "stage": "short", "task_id": "other"}],
    )

    checks = _build_stage_checks(tasks_by_stage, achievements_by_stage)

    assert checks["short"]["result"] == "fail"
    assert "未完成任务" in checks["short"]["reason"]


def test_reassessment_stage_check_uncovered_todo_still_fail():
    _gap_items, tasks_by_stage, achievements_by_stage, _pool, _tasks_by_id, _achievements = _normalize_inputs(
        {},
        [{"id": "t1", "name": "任务1", "stage": "short", "status": "todo"}],
        [{"id": "a1", "name": "成果", "url": "https://example.com", "description": None, "stage": "short", "task_id": "other"}],
    )

    checks = _build_stage_checks(tasks_by_stage, achievements_by_stage)

    assert checks["short"]["result"] == "fail"
    assert "未完成任务" in checks["short"]["reason"]


def test_reassessment_stage_check_rolls_back_after_achievement_removed():
    task = {"id": "t1", "name": "任务1", "stage": "short", "status": "todo"}
    achievement = {"id": "a1", "name": "成果", "url": "https://example.com", "description": None, "stage": "short", "task_id": "t1"}
    _gap_items, tasks_by_stage, achievements_by_stage, _pool, _tasks_by_id, _achievements = _normalize_inputs(
        {}, [task], [achievement]
    )
    checks = _build_stage_checks(tasks_by_stage, achievements_by_stage)
    assert checks["short"]["result"] == "pass"

    # 成果删除后同一任务不再被覆盖 → 阶段校验回退为未完成
    _gap_items, tasks_by_stage, achievements_by_stage, _pool, _tasks_by_id, _achievements = _normalize_inputs(
        {}, [task], []
    )
    checks2 = _build_stage_checks(tasks_by_stage, achievements_by_stage)

    assert checks2["short"]["result"] == "fail"
    assert "未完成任务" in checks2["short"]["reason"]
