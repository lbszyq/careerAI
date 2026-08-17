"""：报告响应结构 + 双路径保留 salary_comparison 测试。

- 标准 2（主链路）：LLM 路径 _normalize_directions（overlay，系统值不被 LLM 改写）
  与 fallback 路径 _sanitize_directions（显式白名单透传）方向均保留 salary_comparison。
- ReportDirectionOut schema 含 salary_comparison 字段（报告响应结构）。
"""
from app.ai.fallback.report_assembler import _normalize_directions, _sanitize_directions
from app.schemas.reports import ReportDirectionOut

_COMPARISON = {
    "expected_salary": 12000,
    "p25": 8000,
    "p50": 12000,
    "p75": 18000,
    "level": "p50_p75",
    "note": "你的期望薪资 12k/月 处于该岗位薪资区间 50-75 分位段（12k-18k/月）。",
}


def _direction(**overrides) -> dict:
    d = {
        "job_title": "算法工程师",
        "match_score": 88,
        "salary": {"p25": 8000, "p50": 12000, "p75": 18000},
    }
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# fallback 路径：_sanitize_directions 显式白名单透传 salary_comparison
# ---------------------------------------------------------------------------
def test_sanitize_directions_preserves_salary_comparison():
    out = _sanitize_directions([_direction(salary_comparison=_COMPARISON)])
    assert out[0]["salary_comparison"] == _COMPARISON
    assert out[0]["salary_comparison"]["level"] == "p50_p75"


# ---------------------------------------------------------------------------
# LLM 路径：_normalize_directions overlay，数字来自 market_results 不被 LLM 改写
# ---------------------------------------------------------------------------
def test_normalize_directions_overlays_salary_comparison_from_market():
    """系统值优先：LLM 自带的 salary_comparison（幻觉/改写）被 market_results 确定性值覆盖。"""
    state = {"market_results": [_direction(salary_comparison=_COMPARISON)]}
    llm_direction = _direction(
        salary={"p25": 999, "p50": 999, "p75": 999},
        salary_comparison={"expected_salary": 1, "level": "below_p25", "note": "LLM 幻觉"},
    )
    out = _normalize_directions([llm_direction], state)
    assert out[0]["salary_comparison"] == _COMPARISON
    assert out[0]["salary_comparison"]["level"] == "p50_p75"


def test_normalize_directions_nullifies_llm_comparison_without_market_value():
    """无系统 salary_comparison → LLM 自判值被置空（反幻觉，不保留 LLM 自判）。"""
    state = {"market_results": [_direction()]} # 系统方向无 salary_comparison
    llm_direction = _direction(salary_comparison=_COMPARISON)
    out = _normalize_directions([llm_direction], state)
    assert out[0].get("salary_comparison") is None


# ---------------------------------------------------------------------------
# 报告响应结构：ReportDirectionOut 含 salary_comparison 字段
# ---------------------------------------------------------------------------
def test_report_direction_out_has_salary_comparison_field():
    assert "salary_comparison" in ReportDirectionOut.model_fields
