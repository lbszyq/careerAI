"""：期望薪资 vs 岗位薪资分位对比（确定性计算）纯函数单测。

- 标准 1（正向）：_build_salary_comparison 半开区间边界（等号归属冻结）5 态覆盖。
- 标准 3（边界）：expected_salary 缺失/≤0 → None；有期望无分位 → no_data；空 salary 不崩溃。
- 方向组装点：_apply_recommendation_constraints 并入 salary_comparison（数字来自 direction.salary）。
"""
from app.ai.agents.market import (
    _apply_recommendation_constraints,
    _build_salary_comparison,
)


def _cmp(expected, salary):
    return _build_salary_comparison(expected, salary)


FULL = {"p25": 8000, "p50": 12000, "p75": 18000}


# ---------------------------------------------------------------------------
# 标准 1：半开区间边界 + 等号归属冻结（4 个 level + no_data 共 5 态）
# ---------------------------------------------------------------------------
def test_below_p25():
    assert _cmp(7000, FULL)["level"] == "below_p25"


def test_p25_boundary_goes_p25_p50():
    """等号归属冻结（P0）：expected == p25 → p25_p50。"""
    assert _cmp(8000, FULL)["level"] == "p25_p50"


def test_mid_p25_p50():
    assert _cmp(10000, FULL)["level"] == "p25_p50"


def test_p50_boundary_goes_p50_p75():
    """等号归属冻结（P0）：expected == p50 → p50_p75。"""
    assert _cmp(12000, FULL)["level"] == "p50_p75"


def test_mid_p50_p75():
    assert _cmp(15000, FULL)["level"] == "p50_p75"


def test_p75_boundary_goes_above_p75():
    """等号归属冻结（P0）：expected == p75 → above_p75。"""
    assert _cmp(18000, FULL)["level"] == "above_p75"


def test_above_p75():
    assert _cmp(25000, FULL)["level"] == "above_p75"


def test_no_data_when_salary_empty_dict():
    """标准 3：有期望但分位全缺失 → no_data（结构冻结）。"""
    c = _cmp(12000, {})
    assert c["level"] == "no_data"
    assert c["expected_salary"] == 12000
    assert c["p25"] is None and c["p50"] is None and c["p75"] is None
    assert c["note"] == "暂无该岗位薪资数据"


def test_no_data_when_salary_none():
    c = _cmp(12000, None)
    assert c["level"] == "no_data"
    assert c["note"] == "暂无该岗位薪资数据"


def test_no_data_when_salary_all_none_values():
    c = _cmp(12000, {"p25": None, "p50": None, "p75": None})
    assert c["level"] == "no_data"


# ---------------------------------------------------------------------------
# 标准 3：expected_salary 缺失/≤0 → None（前端隐藏）
# ---------------------------------------------------------------------------
def test_expected_missing_returns_none():
    assert _cmp(None, FULL) is None


def test_expected_zero_returns_none():
    assert _cmp(0, FULL) is None


def test_expected_negative_returns_none():
    assert _cmp(-100, FULL) is None


def test_expected_non_numeric_returns_none():
    assert _cmp("not-a-number", FULL) is None


# ---------------------------------------------------------------------------
# note 为 code 模板（数字确定性；标准 6）
# ---------------------------------------------------------------------------
def test_note_is_code_template_with_deterministic_numbers():
    c = _cmp(12000, FULL)
    assert c["level"] == "p50_p75"
    assert c["expected_salary"] == 12000
    assert "12k" in c["note"] and "50-75" in c["note"]
    # p25/p50/p75 原样透传（数字来自 salary，不被改写）
    assert c["p25"] == 8000 and c["p50"] == 12000 and c["p75"] == 18000


# ---------------------------------------------------------------------------
# 方向组装点：_apply_recommendation_constraints 并入 salary_comparison
# ---------------------------------------------------------------------------
def test_apply_recommendation_constraints_injects_salary_comparison():
    directions = [{"job_title": "后端工程师", "match_score": 85, "salary": FULL}]
    out = _apply_recommendation_constraints(directions, {}, expected_salary=12000)
    assert out[0]["salary_comparison"]["level"] == "p50_p75"


def test_apply_recommendation_constraints_null_when_expected_missing():
    directions = [{"job_title": "后端工程师", "match_score": 85, "salary": FULL}]
    out = _apply_recommendation_constraints(directions, {}, expected_salary=None)
    assert out[0].get("salary_comparison") is None


def test_apply_recommendation_constraints_no_data_when_salary_none():
    directions = [{"job_title": "后端工程师", "match_score": 85, "salary": None}]
    out = _apply_recommendation_constraints(directions, {}, expected_salary=12000)
    assert out[0]["salary_comparison"]["level"] == "no_data"
