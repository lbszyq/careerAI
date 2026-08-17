"""报告质量评估脚本：字段完整性 + 格式规则校验。

用法（在 ``backend`` 目录下）：
    python -m scripts.eval_report_quality [--data DIR] [--json] [--out FILE]

设计要点（面试证据链 / 无 key 无权重可跑）：
- 本评估为**确定性规则校验**，不调用 LLM → 天然满足「缺 DEEPSEEK_API_KEY / 缺模型权重
  也能跑」；输出固定标注「rule-based（mock 路径）」并在环境检查中提示 key 状态。
- 校验对象：``report_cases.json``（完整报告，reports-contract 结构）+ ``portrait_cases.json``
  （画像对象，report.portrait 同构，复用同一套画像规则）。
- 全局规则（结构契约）+ 每条 expected 断言（per-case 期望）双轨：
  全局规则保证「字段完整性/格式合规」下限，expected 允许针对单条用例收紧
  （如 directions 数量 3-5、plan.tasks ≥5、suggestion 形态等）。
- 边界 ：空报告/空评测集 → 输出降级判定（失败项 + 明确原因），不崩溃。
- 数据集中故意含反例（占位文案/超界评分/空报告等），通过率<100% 是规则引擎
  正在工作的证据，通过率下降即质量回退信号（门禁口径）。

本脚本对 ``app/ai/`` 现有逻辑零依赖（不 import 任何 AI/LLM 代码），仅引用评估模块。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.ai.evaluation import ( # noqa: E402
    EVALUATION_DATA_DIR,
    load_portrait_cases,
    load_report_cases,
    schema_description,
)
from app.ai.evaluation.schemas import ( # noqa: E402
    PortraitExpected,
    ReportExpected,
)

# 全局占位文案黑名单（大小写不敏感；per-case expected.must_not_contain 追加）
_PLACEHOLDER_PATTERNS = (
    "todo",
    "xxx",
    "待补充",
    "占位",
    "placeholder",
    "lorem ipsum",
    "tbd",
    "待定",
    "…",
)

_LEVELS = ("已具备", "部分具备", "不具备")
_STAGES = ("short", "mid", "long")
_DIM_KEYS = ("technical", "project", "academic", "soft_skill", "industry_knowledge")
_DIRECTION_FIELDS = (
    "job_title", "match_score", "salary", "salary_note", "trend", "heat",
    "data_source", "education_requirement", "education_match", "competition_note",
    "certificates_bonus", "recommend_reason", "data_grade", "confidence_reasons",
)

Violation = tuple[str, str] # (rule, message)


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_in_range(value: Any, low: float, high: float) -> bool:
    return _is_number(value) and low <= value <= high


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _placeholder_hits(value: Any, extra: list[str]) -> list[str]:
    """扫描字符串中的占位文案（递归字典/列表）。"""
    patterns = [p.lower() for p in _PLACEHOLDER_PATTERNS] + [p.lower() for p in extra if p]
    hits: list[str] = []
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            low = item.lower()
            if not item.strip():
                hits.append("空字符串")
                continue
            for pat in patterns:
                if pat and pat in low:
                    hits.append(f"含占位文案「{pat}」")
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return sorted(set(hits))


# ---------------------------------------------------------------------------
# 画像规则（report.portrait 同构，portrait_cases 与 report_cases 共用）
# ---------------------------------------------------------------------------
def check_portrait(portrait: Any, expected: PortraitExpected | None = None, extra_placeholder: list[str] | None = None) -> list[Violation]:
    expected = expected or PortraitExpected()
    extra = extra_placeholder or []
    out: list[Violation] = []
    if not isinstance(portrait, dict) or not portrait:
        out.append(("portrait.structure", "portrait 缺失或非对象（降级判定）"))
        return out

    for f in expected.must_have_fields:
        if f not in portrait:
            out.append(("portrait.field_missing", f"缺少字段 {f}"))

    score = portrait.get("overall_score")
    if score is None:
        out.append(("portrait.overall_score_missing", "缺少 overall_score"))
    elif not _is_in_range(score, expected.overall_score_min, expected.overall_score_max):
        out.append(("portrait.overall_score_range", f"overall_score={score} 超出 [{expected.overall_score_min},{expected.overall_score_max}]"))

    dims = portrait.get("dimensions")
    if not isinstance(dims, dict):
        out.append(("portrait.dimensions_structure", "dimensions 缺失或非对象"))
    else:
        for key in expected.dimensions_required:
            v = dims.get(key)
            if not _is_in_range(v, 0, 100):
                out.append(("portrait.dimensions_range", f"dimensions.{key}={v} 非法（需 0-100 数值）"))

    for f in ("strengths", "weaknesses"):
        v = portrait.get(f)
        if not isinstance(v, list) or not v:
            out.append(("portrait.strengths_weaknesses", f"{f} 缺失或为空列表"))
        else:
            for s in v:
                if not _non_empty_str(s):
                    out.append(("portrait.strengths_weaknesses", f"{f} 含空字符串项"))

    conf = portrait.get("confidence")
    if conf not in expected.confidence_allowed:
        out.append(("portrait.confidence", f"confidence={conf!r} 非法（允许 {expected.confidence_allowed}）"))

    if "norm" in portrait and portrait["norm"] is not None and not isinstance(portrait["norm"], dict):
        out.append(("portrait.norm_type", "norm 非对象或 null"))

    for hit in _placeholder_hits(portrait, extra):
        out.append(("portrait.placeholder", hit))
    return out


# ---------------------------------------------------------------------------
# 报告规则
# ---------------------------------------------------------------------------
def check_directions(dirs: Any, expected: ReportExpected) -> list[Violation]:
    out: list[Violation] = []
    if not isinstance(dirs, list):
        return [("report.directions_structure", "directions 缺失或非数组")]
    if expected.directions_min is not None and len(dirs) < expected.directions_min:
        out.append(("report.directions_count", f"directions 数量 {len(dirs)} < 期望下限 {expected.directions_min}"))
    if expected.directions_max is not None and len(dirs) > expected.directions_max:
        out.append(("report.directions_count", f"directions 数量 {len(dirs)} > 期望上限 {expected.directions_max}"))
    for i, d in enumerate(dirs):
        tag = f"directions[{i}]"
        if not isinstance(d, dict):
            out.append(("report.direction_structure", f"{tag} 非对象"))
            continue
        for f in _DIRECTION_FIELDS:
            if f not in d:
                out.append(("report.direction_field_missing", f"{tag} 缺少契约字段 {f}"))
        if not _non_empty_str(d.get("job_title")):
            out.append(("report.direction_job_title", f"{tag} job_title 缺失或为空"))
        ms = d.get("match_score")
        if not _is_in_range(ms, 0, 100):
            out.append(("report.direction_match_score", f"{tag} match_score={ms} 非法（需 0-100 数值）"))
        grade = d.get("data_grade")
        if grade is not None and grade not in ("A", "B", "C"):
            out.append(("report.direction_data_grade", f"{tag} data_grade={grade!r} 非法（允许 A/B/C/null）"))
        cr = d.get("confidence_reasons")
        if cr is not None and not (isinstance(cr, dict) and isinstance(cr.get("supporting"), list) and isinstance(cr.get("concerns"), list)):
            out.append(("report.direction_confidence_reasons", f"{tag} confidence_reasons 非法（需 {{supporting:[], concerns:[]}}）"))
    return out


def check_gap_analysis(gap: Any, expected: ReportExpected) -> list[Violation]:
    out: list[Violation] = []
    if not isinstance(gap, dict):
        return [("report.gap_structure", "gap_analysis 缺失或非对象（stage2 必须）")]
    if not _non_empty_str(gap.get("target_job")):
        out.append(("report.gap_target_job", "gap_analysis.target_job 缺失或为空"))
    items = gap.get("items")
    if not isinstance(items, list) or not items:
        out.append(("report.gap_items", "gap_analysis.items 缺失或为空列表"))
    else:
        if expected.gap_items_min is not None and len(items) < expected.gap_items_min:
            out.append(("report.gap_items_count", f"gap_analysis.items 数量 {len(items)} < 期望下限 {expected.gap_items_min}"))
        for i, item in enumerate(items):
            tag = f"gap_analysis.items[{i}]"
            if not isinstance(item, dict):
                out.append(("report.gap_item_structure", f"{tag} 非对象"))
                continue
            if not _non_empty_str(item.get("skill")):
                out.append(("report.gap_item_skill", f"{tag} skill 缺失或为空"))
            w = item.get("weight")
            if not _is_in_range(w, 0, 1):
                out.append(("report.gap_item_weight", f"{tag} weight={w} 非法（需 0-1 数值）"))
            if item.get("level") not in _LEVELS:
                out.append(("report.gap_item_level", f"{tag} level={item.get('level')!r} 非法（允许 {_LEVELS}）"))
            if not _non_empty_str(item.get("jd_source")):
                out.append(("report.gap_item_jd_source", f"{tag} jd_source 缺失或为空（无据即删口径）"))
            if not _non_empty_str(item.get("evidence")):
                out.append(("report.gap_item_evidence", f"{tag} evidence 缺失或为空"))
    cr = gap.get("confidence_reasons")
    if cr is not None and not (isinstance(cr, dict) and isinstance(cr.get("supporting"), list) and isinstance(cr.get("concerns"), list)):
        out.append(("report.gap_confidence_reasons", "gap_analysis.confidence_reasons 非法（需 {supporting:[], concerns:[]}）"))
    return out


def check_plan(plan: Any, expected: ReportExpected) -> list[Violation]:
    out: list[Violation] = []
    if not isinstance(plan, dict):
        return [("report.plan_structure", "plan 缺失或非对象（stage2 必须）")]
    stages = plan.get("stages")
    if not isinstance(stages, dict) or not stages:
        out.append(("report.plan_stages", "plan.stages 缺失或为空对象"))
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        out.append(("report.plan_tasks", "plan.tasks 缺失或为空列表"))
    else:
        if expected.plan_tasks_min is not None and len(tasks) < expected.plan_tasks_min:
            out.append(("report.plan_tasks_count", f"plan.tasks 数量 {len(tasks)} < 期望下限 {expected.plan_tasks_min}"))
        for i, task in enumerate(tasks):
            tag = f"plan.tasks[{i}]"
            if not isinstance(task, dict):
                out.append(("report.plan_task_structure", f"{tag} 非对象"))
                continue
            if not _non_empty_str(task.get("name")):
                out.append(("report.plan_task_name", f"{tag} name 缺失或为空"))
            if not _non_empty_str(task.get("duration")):
                out.append(("report.plan_task_duration", f"{tag} duration 缺失或为空"))
            if task.get("stage") is not None and task.get("stage") not in _STAGES:
                out.append(("report.plan_task_stage", f"{tag} stage={task.get('stage')!r} 非法（允许 {_STAGES}）"))
    return out


def check_suggestion(sugg: Any, expected: ReportExpected) -> list[Violation]:
    out: list[Violation] = []
    if expected.suggestion == "null":
        if sugg is not None:
            out.append(("report.suggestion_must_null", f"suggestion 应为 null（实际 {type(sugg).__name__}）"))
        return out
    if expected.suggestion == "dict":
        if not isinstance(sugg, dict) or not sugg:
            out.append(("report.suggestion_missing", "suggestion 应为非空对象（stage2 完整报告必须生成）"))
            return out
        for f in ("summary", "short_term", "mid_long_term", "reasons", "applicable_condition"):
            if f not in sugg:
                out.append(("report.suggestion_fields", f"suggestion 缺少字段 {f}"))
        if not isinstance(sugg.get("reasons"), list) or not sugg["reasons"]:
            out.append(("report.suggestion_reasons", "suggestion.reasons 缺失或为空（禁止凭空建议）"))
    return out


def _resolve_path(report: dict, path: str) -> Any:
    node: Any = report
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def check_report(report: Any, expected: ReportExpected) -> list[Violation]:
    out: list[Violation] = []
    if not isinstance(report, dict) or not report:
        return [("report.structure", "报告为空或非对象（降级判定）")]

    stage = report.get("stage")
    if stage not in ("stage1", "stage2"):
        out.append(("report.stage", f"stage={stage!r} 非法（允许 stage1/stage2）"))

    for f in ("stage", "notes", "confidence"):
        if f not in report:
            out.append(("report.field_missing", f"缺少顶层字段 {f}"))
    notes = report.get("notes")
    if not isinstance(notes, list):
        out.append(("report.notes_type", "notes 非数组"))
    else:
        for n in notes:
            if not _non_empty_str(n):
                out.append(("report.notes_type", "notes 含空/非字符串项"))
    conf = report.get("confidence")
    if conf is not None and not isinstance(conf, dict):
        out.append(("report.confidence_type", "confidence 非对象"))

    if stage == "stage1":
        out.extend(check_portrait(report.get("portrait"), extra_placeholder=expected.must_not_contain))
        out.extend(check_directions(report.get("directions"), expected))
        if report.get("suggestion") is not None:
            out.append(("report.suggestion_stage1", "stage1 suggestion 必须为 null"))
        if report.get("gap_analysis") not in (None,):
            out.append(("report.gap_stage1", "stage1 gap_analysis 应为 null"))
        if report.get("plan") not in (None,):
            out.append(("report.plan_stage1", "stage1 plan 应为 null"))
    elif stage == "stage2":
        out.extend(check_gap_analysis(report.get("gap_analysis"), expected))
        out.extend(check_plan(report.get("plan"), expected))
        out.extend(check_suggestion(report.get("suggestion"), expected))
        if report.get("portrait"):
            out.extend(check_portrait(report["portrait"], extra_placeholder=expected.must_not_contain))

    # per-case 期望：点分路径必须存在
    for path in expected.must_have_fields:
        if _resolve_path(report, path) is None:
            out.append(("report.expected_field_missing", f"期望字段不存在：{path}"))

    # 全局占位扫描
    for hit in _placeholder_hits(report, expected.must_not_contain):
        out.append(("report.placeholder", hit))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
@dataclass
class CaseVerdict:
    case_id: str
    category: str
    passed: bool
    violations: list[Violation] = field(default_factory=list)


def _evaluate_cases(data_dir: Path) -> tuple[list[CaseVerdict], dict[str, Any]]:
    verdicts: list[CaseVerdict] = []
    rule_counter: dict[str, int] = {}
    for case in load_portrait_cases(data_dir):
        violations = check_portrait(case.input, case.expected)
        verdicts.append(CaseVerdict(case.case_id, "portrait", not violations, violations))
        for rule, _ in violations:
            rule_counter[rule] = rule_counter.get(rule, 0) + 1
    for case in load_report_cases(data_dir):
        violations = check_report(case.report, case.expected)
        verdicts.append(CaseVerdict(case.case_id, "report", not violations, violations))
        for rule, _ in violations:
            rule_counter[rule] = rule_counter.get(rule, 0) + 1
    return verdicts, rule_counter


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="报告质量评估：字段完整性 + 格式规则校验")
    p.add_argument("--data", default=str(EVALUATION_DATA_DIR), help="评测数据目录（默认 evaluation_data）")
    p.add_argument("--json", action="store_true", help="仅输出 JSON")
    p.add_argument("--out", help="将 JSON 结果写入文件（同时保留人类可读输出）")
    p.add_argument("--schema", action="store_true", help="输出评测集 schema 说明并退出")
    return p.parse_args(argv)


def _render(verdicts: list[CaseVerdict], rule_counter: dict[str, int], by_cat: dict[str, tuple[int, int]]) -> str:
    total = len(verdicts) or 1
    passed = sum(1 for v in verdicts if v.passed)
    lines: list[str] = []
    lines.append("=" * 62)
    lines.append("报告质量评估（AI Evaluation ·）")
    lines.append("模式: rule-based（确定性规则校验，不调用 LLM → mock 路径）")
    lines.append("-" * 62)
    lines.append("类别汇总：")
    for cat, (p, n) in by_cat.items():
        lines.append(f" - {cat}: {p}/{n} 通过（{p / n:.1%}）")
    lines.append(f" 合计: {passed}/{len(verdicts)} 通过（{passed / total:.1%}）")
    lines.append("-" * 62)
    if rule_counter:
        lines.append("规则违规分布（Top 8）：")
        for rule, cnt in sorted(rule_counter.items(), key=lambda kv: -kv[1])[:8]:
            lines.append(f" - {rule}: {cnt}")
    lines.append("-" * 62)
    lines.append("逐条明细：")
    for v in verdicts:
        status = "PASS" if v.passed else "FAIL"
        detail = "" if v.passed else "；".join(f"{rule}: {msg}" for rule, msg in v.violations[:4])
        lines.append(f" [{status}] {v.category}/{v.case_id} {detail}")
    lines.append("=" * 62)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.schema:
        print(schema_description())
        return 0
    data_dir = Path(args.data)

    # 环境检查：key 缺失提示（本评估不依赖 LLM，仍按要求显式标注）
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    env_checks = {
        "deepseek_api_key": "缺失 → 本评估为规则校验（mock 路径），不调用 LLM" if not key else "已配置（本评估不使用 LLM）",
        "llm": "不调用（确定性规则校验，无需模型权重）",
    }

    try:
        verdicts, rule_counter = _evaluate_cases(data_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[eval_report_quality] 错误：{exc}", file=sys.stderr)
        return 2

    if not verdicts:
        print("[eval_report_quality] 警告：评测集为空（0 条），输出降级结果（通过率 N/A），不崩溃", file=sys.stderr)

    by_cat: dict[str, tuple[int, int]] = {}
    for v in verdicts:
        p, n = by_cat.get(v.category, (0, 0))
        by_cat[v.category] = (p + (1 if v.passed else 0), n + 1)

    total = len(verdicts) or 1
    passed = sum(1 for v in verdicts if v.passed)
    payload: dict[str, Any] = {
        "tool": "eval_report_quality",
        "schema_version": "1.0",
        "mode": "rule-based",
        "mock_mode": True,
        "env_checks": env_checks,
        "dataset": {"data_dir": str(data_dir)},
        "metrics": {
            "cases_total": len(verdicts),
            "cases_passed": passed,
            "pass_rate": round(passed / total, 4),
            "by_category": {cat: {"passed": p, "total": n, "pass_rate": round(p / n, 4)} for cat, (p, n) in by_cat.items()},
            "rule_violations": rule_counter,
        },
        "cases": [
            {"case_id": v.case_id, "category": v.category, "passed": v.passed,
             "violations": [{"rule": r, "message": m} for r, m in v.violations]}
            for v in verdicts
        ],
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render(verdicts, rule_counter, by_cat))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
