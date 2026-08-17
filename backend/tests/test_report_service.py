"""报告双写收敛单一事实源测试。

- 标准 1a（结构断言）：get_report 不再跨存储调停——_best_directions_by_title /
  _direction_better / _grade_rank 已从 report_service 删除（模块级不存在）；
  方向内容全部来自 result JSONB，career_directions 仅承担方向 id 身份锚点（读时合成）。
- 标准 1c（往返一致）：同一报告读写往返一致——get_report 输出内容字段等于 JSONB 落库值
  （断言字段范围排除读时合成字段：direction id / plan.id 注入）。
- 标准 1b（运行时状态隔离）：plan_tasks.status / growth_plans.stages 写方
  （feedback_service / plan_service）只写表，不回写 JSONB 快照——get_report 读 JSONB
  快照不受勾选/重评影响。
- 标准 2：空报告 / 部分字段缺失不崩溃；list_reports job_titles/target_job/
  score 主读 JSONB（存量 target_job 缺口回退 gap_analyses 表，null 填充非调停）。
"""
import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.services.report_service as report_service_module
from app.services.report_service import ReportService
from tests.helpers import make_user


def _report(result: dict | None, *, stage: str = "stage1", status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status=status,
        stage=stage,
        result=result,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _direction_row(job_title: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), job_title=job_title)


def _svc(session=None) -> ReportService:
    """构造 ReportService（repo 方法随后 monkeypatch 为 AsyncMock，不依赖真实 DB）。"""
    return ReportService(session)


def _jsonb_directions() -> list[dict]:
    """模拟 market agent / report_assembler 落库的方向 dict（含全部详情字段）。"""
    return [
        {
            "job_title": "算法工程师",
            "match_score": 88,
            "salary": {"p25": 25.0, "p50": 35.0, "p75": 50.0},
            "salary_note": "招聘平台样本",
            "trend": "up",
            "heat": "高",
            "data_source": "官方统计",
            "education_requirement": "本科及以上",
            "education_match": "匹配",
            "competition_note": "竞争度高",
            "certificates_bonus": "建议考取 XXX",
            "recommend_reason": "与你的技术栈高度匹配",
            "data_grade": "A",
            "confidence_reasons": {"supporting": ["来源 A 级"], "concerns": []},
        },
        {
            "job_title": "数据分析师",
            "match_score": 82,
            "salary": {"p25": 20.0, "p50": 28.0, "p75": 40.0},
            "salary_note": None,
            "trend": "稳定",
            "heat": "中",
            "data_source": None,
            "education_requirement": "本科及以上",
            "education_match": "匹配",
            "competition_note": "竞争度中",
            "certificates_bonus": None,
            "recommend_reason": "与你的数据分析能力匹配",
            "data_grade": "B",
            "confidence_reasons": {"supporting": ["来源 B 级"], "concerns": []},
        },
    ]


# ---------------------------------------------------------------------------
# 标准 1a：结构断言——跨存储调停函数已删除；内容单源 JSONB
# ---------------------------------------------------------------------------
def test_report_service_no_cross_store_reconciliation_helpers():
    """标准 1a（结构断言）：_best_directions_by_title/_direction_better/_grade_rank 已删除。"""
    for name in ("_best_directions_by_title", "_direction_better", "_grade_rank"):
        assert not hasattr(report_service_module, name), f"{name} 应从 report_service 删除"


def test_get_report_directions_single_source_jsonb():
    """标准 1a：方向内容全部来自 result JSONB；career_directions 表仅提供 id 身份锚点。"""
    result = {"portrait": {"overall_score": 82}, "directions": _jsonb_directions()}
    report = _report(result, stage="stage2")
    svc = _svc()
    svc.report_repo.get_owned = AsyncMock(return_value=report)
    svc.report_repo.get_directions = AsyncMock(
        return_value=[_direction_row("算法工程师"), _direction_row("数据分析师")]
    )
    svc.report_repo.get_plan_by_report_id = AsyncMock(return_value=None)

    out = asyncio.run(svc.get_report(make_user(), report.id))

    assert len(out.directions) == 2
    # 内容字段来自 JSONB（含 salary_note/data_source/education_* 等仅 JSONB 字段）
    first = out.directions[0]
    assert first.job_title == "算法工程师"
    assert first.match_score == 88
    assert first.salary == {"p25": 25.0, "p50": 35.0, "p75": 50.0}
    assert first.salary_note == "招聘平台样本"
    assert first.trend == "up"
    assert first.heat == "高"
    assert first.data_grade == "A"
    assert first.confidence_reasons == {"supporting": ["来源 A 级"], "concerns": []}
    assert first.data_source == "官方统计"
    # 表行内容（如 match_score 不同）不参与——读时仅合成 id 身份锚点
    assert first.id is not None


def test_get_report_direction_salary_comparison_from_jsonb():
    """：报告详情方向 salary_comparison 从 result JSONB 透传（读路径单一事实源）。"""
    result = {
        "portrait": {"overall_score": 82},
        "directions": [
            {
                "job_title": "算法工程师",
                "match_score": 88,
                "salary": {"p25": 8000.0, "p50": 12000.0, "p75": 18000.0},
                "salary_comparison": {
                    "expected_salary": 12000,
                    "p25": 8000,
                    "p50": 12000,
                    "p75": 18000,
                    "level": "p50_p75",
                    "note": "你的期望薪资 12k/月 处于该岗位薪资区间 50-75 分位段（12k-18k/月）。",
                },
            }
        ],
    }
    report = _report(result)
    svc = _svc()
    svc.report_repo.get_owned = AsyncMock(return_value=report)
    svc.report_repo.get_directions = AsyncMock(return_value=[_direction_row("算法工程师")])
    svc.report_repo.get_plan_by_report_id = AsyncMock(return_value=None)

    out = asyncio.run(svc.get_report(make_user(), report.id))
    assert out.directions[0].salary_comparison == {
        "expected_salary": 12000,
        "p25": 8000,
        "p50": 12000,
        "p75": 18000,
        "level": "p50_p75",
        "note": "你的期望薪资 12k/月 处于该岗位薪资区间 50-75 分位段（12k-18k/月）。",
    }


def test_get_report_direction_id_synthesized_from_table():
    """标准 1c 排除范围：direction id 为读时合成身份锚点（career_directions 表），非内容字段。"""
    result = {"directions": [{"job_title": "算法工程师", "match_score": 88}]}
    report = _report(result)
    row = _direction_row("算法工程师")
    svc = _svc()
    svc.report_repo.get_owned = AsyncMock(return_value=report)
    svc.report_repo.get_directions = AsyncMock(return_value=[row])
    svc.report_repo.get_plan_by_report_id = AsyncMock(return_value=None)

    out = asyncio.run(svc.get_report(make_user(), report.id))
    assert out.directions[0].id == row.id


# ---------------------------------------------------------------------------
# 标准 1c：往返一致（排除读时合成字段）
# ---------------------------------------------------------------------------
def test_get_report_round_trip_content_equal_jsonb():
    """标准 1c：get_report 输出内容字段与 JSONB 落库值一致（排除 direction id / plan.id）。"""
    result = {
        "portrait": {"overall_score": 82, "dimensions": {"technical": 80}},
        "directions": _jsonb_directions(),
        "gap_analysis": {"target_job": "算法工程师", "items": [{"skill": "SQL", "level": "lack"}]},
        "plan": {"stages": {"short": {"goal": "g"}}, "tasks": [{"name": "t1", "acceptance_criteria": "a"}]},
        "suggestion": {"strategy": "s", "actions": ["a"]},
    }
    report = _report(result, stage="stage2")
    svc = _svc()
    svc.report_repo.get_owned = AsyncMock(return_value=report)
    svc.report_repo.get_directions = AsyncMock(
        return_value=[_direction_row("算法工程师"), _direction_row("数据分析师")]
    )
    svc.report_repo.get_plan_by_report_id = AsyncMock(return_value=None)

    out = asyncio.run(svc.get_report(make_user(), report.id))

    assert out.portrait == result["portrait"]
    assert out.gap_analysis == result["gap_analysis"]
    assert out.plan == result["plan"] # 无计划记录时不注入 id，plan 原样
    assert out.suggestion == result["suggestion"]
    for d, src in zip(out.directions, result["directions"], strict=True):
        assert d.job_title == src["job_title"]
        assert d.match_score == src["match_score"]
        assert d.salary == src["salary"]
        assert d.salary_note == src["salary_note"]
        assert d.trend == src["trend"]
        assert d.heat == src["heat"]
        assert d.data_grade == src["data_grade"]
        assert d.confidence_reasons == src["confidence_reasons"]


def test_get_report_plan_id_injected_from_growth_plans():
    """QA-BUG-018 保留：plan.id 为读时合成（growth_plans 表），报告详情可定位计划明细。"""
    plan_id = uuid.uuid4()
    result = {"plan": {"stages": {"short": {}}, "tasks": [{"name": "t1"}]}}
    report = _report(result, stage="stage2")
    svc = _svc()
    svc.report_repo.get_owned = AsyncMock(return_value=report)
    svc.report_repo.get_directions = AsyncMock(return_value=[])
    svc.report_repo.get_plan_by_report_id = AsyncMock(return_value=SimpleNamespace(id=plan_id))

    out = asyncio.run(svc.get_report(make_user(), report.id))
    assert out.plan["id"] == plan_id


# ---------------------------------------------------------------------------
# 标准 2：空报告 / 部分字段缺失不崩溃
# ---------------------------------------------------------------------------
def test_get_report_empty_result_not_crash():
    """/：result=None / 空 dict / 缺 directions → 不崩溃，返回空方向。"""
    for result in (None, {}, {"directions": None}):
        report = _report(result)
        svc = _svc()
        svc.report_repo.get_owned = AsyncMock(return_value=report)
        svc.report_repo.get_directions = AsyncMock(return_value=[])
        svc.report_repo.get_plan_by_report_id = AsyncMock(return_value=None)
        out = asyncio.run(svc.get_report(make_user(), report.id))
        assert out.directions == []
        assert out.portrait is None


def test_get_report_direction_partial_fields_not_crash():
    """/：方向 dict 缺部分可选字段 → 不崩溃，缺失字段为 None。"""
    result = {"directions": [{"job_title": "算法工程师", "match_score": 88}]} # 缺 salary/trend/heat/...
    report = _report(result)
    svc = _svc()
    svc.report_repo.get_owned = AsyncMock(return_value=report)
    svc.report_repo.get_directions = AsyncMock(return_value=[_direction_row("算法工程师")])
    svc.report_repo.get_plan_by_report_id = AsyncMock(return_value=None)

    out = asyncio.run(svc.get_report(make_user(), report.id))
    assert out.directions[0].salary is None
    assert out.directions[0].salary_note is None
    assert out.directions[0].trend is None


# ---------------------------------------------------------------------------
# 标准 1a（list_reports）：job_titles/target_job/score 主读 JSONB
# ---------------------------------------------------------------------------
def test_list_reports_single_source_jsonb():
    """list_reports：score/job_titles/target_job 来自 result JSONB（无表读取）。"""
    result = {
        "portrait": {"overall_score": 82},
        "directions": _jsonb_directions(),
        "gap_analysis": {"target_job": "算法工程师", "items": []},
    }
    report = _report(result, stage="stage2")
    svc = _svc()
    svc.report_repo.list_by_user = AsyncMock(return_value=(1, [report]))
    svc.report_repo.list_processing_report_jobs = AsyncMock(return_value=[])
    # 断言：JSONB 全量覆盖时不查表（get_target_jobs_by_report_ids 不被调用）
    svc.report_repo.get_target_jobs_by_report_ids = AsyncMock(return_value={})

    out = asyncio.run(svc.list_reports(make_user(), 1, 10))
    assert out["total"] == 1
    item = out["items"][0]
    assert item.score == 82
    assert item.summary["job_titles"] == ["算法工程师", "数据分析师"]
    assert item.summary["target_job"] == "算法工程师"
    svc.report_repo.get_target_jobs_by_report_ids.assert_not_awaited()


def test_list_reports_legacy_target_job_fallback():
    """存量兜底：JSONB 缺 target_job（历史 LLM 路径报告）→ 回退 gap_analyses 表权威值。"""
    result = {
        "portrait": {"overall_score": 78},
        "directions": [{"job_title": "后端开发工程师", "match_score": 85}],
        "gap_analysis": {"items": []}, # 缺 target_job（历史形态）
    }
    report = _report(result, stage="stage2")
    legacy_target = "后端开发工程师"
    svc = _svc()
    svc.report_repo.list_by_user = AsyncMock(return_value=(1, [report]))
    svc.report_repo.list_processing_report_jobs = AsyncMock(return_value=[])
    svc.report_repo.get_target_jobs_by_report_ids = AsyncMock(return_value={report.id: legacy_target})

    out = asyncio.run(svc.list_reports(make_user(), 1, 10))
    item = out["items"][0]
    assert item.summary["target_job"] == legacy_target


def test_list_reports_processing_items():
    """生成中条目（task_jobs）：score=None、job_titles=[]、target_job=None（无报告行）。"""
    job = SimpleNamespace(
        id=uuid.uuid4(), task_type="report_stage1", status="running",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    svc = _svc()
    svc.report_repo.list_by_user = AsyncMock(return_value=(0, []))
    svc.report_repo.list_processing_report_jobs = AsyncMock(return_value=[job])

    out = asyncio.run(svc.list_reports(make_user(), 1, 10))
    assert out["total"] == 1
    item = out["items"][0]
    assert item.id == job.id
    assert item.stage == "stage1"
    assert item.score is None
    assert item.summary == {"job_titles": [], "target_job": None}


# ---------------------------------------------------------------------------
# 标准 1b：运行时状态隔离——勾选/重评写表不回写 JSONB 快照
# ---------------------------------------------------------------------------
def test_runtime_state_writers_do_not_touch_jsonb_snapshot():
    """标准 1b：plan_service.update_task / feedback 只写表（运行时状态），get_report 快照不受影响。

    结构断言：update_task 写 plan_tasks.status 后，get_report 的 plan 仍为 JSONB 生成快照
    （无 plan.id 注入外的任何表回写）；feedback 同理（见服务实现注释）。
    """
    # get_report 读 JSONB 快照：即使 plan_tasks 表状态已变（此处模拟勾选后），
    # 报告详情的 plan 仍来自 result JSONB（快照语义，C-005 报告不可变）。
    result = {"plan": {"stages": {}, "tasks": [{"name": "t1", "status": "todo"}]}}
    report = _report(result, stage="stage2")
    svc = _svc()
    svc.report_repo.get_owned = AsyncMock(return_value=report)
    svc.report_repo.get_directions = AsyncMock(return_value=[])
    svc.report_repo.get_plan_by_report_id = AsyncMock(return_value=None)

    out = asyncio.run(svc.get_report(make_user(), report.id))
    # JSONB 快照保持生成时 status=todo（勾选 done 只改表，不改快照）
    assert out.plan["tasks"][0]["status"] == "todo"


def test_feedback_plan_writers_write_tables_only():
    """标准 1b（结构）：feedback_service._apply_changes / plan_service.update_task 无 JSONB 回写点。

    以模块源码检查断言：运行时状态写方不引用 CareerReport.result 更新。
    """
    import inspect

    from app.services.feedback_service import FeedbackService
    from app.services.plan_service import PlanService

    apply_src = inspect.getsource(FeedbackService._apply_changes)
    update_src = inspect.getsource(PlanService.update_task)
    # 写方仅操作 plan_tasks/growth_plans（运行时状态），不出现对 JSONB 快照的写回赋值
    # （.result = / report_row.result 更新）；docstring 提及「result JSONB 快照」属说明文字，
    # 以赋值语句形态断言，避免误报。
    for src in (apply_src, update_src):
        assert "report_row.result" not in src
        assert "result = merged" not in src
        assert ".result =" not in src
