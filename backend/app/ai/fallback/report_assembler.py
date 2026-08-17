"""报告组装兜底（Planner 不可用时）：按 reports-contract 结构组装最终报告。

任何失败段由 notes 标注「该部分分析不完整」，并用可用数据填充（/）。
"""
from typing import Any

from app.ai.fallback.suggestion import build_suggestion
from app.ai.norm.benchmarks import normalize_norm_payload
from app.ai.rag.retriever import data_grade_name
from app.ai.schemas import GraphState


def assemble_stage1_report(state: GraphState) -> dict:
    """Stage 1 报告骨架：portrait（评分/常模/优劣势）+ directions。"""
    errors = list(state.get("stage_errors") or [])
    notes = [f"该部分分析不完整（{e}）" for e in errors]

    scores = state.get("scores") or {}
    if not scores:
        notes.append("该部分分析不完整（职业分析失败，无评分数据）")

    directions = state.get("market_results") or []
    if not directions:
        notes.append("该部分分析不完整（市场方向检索失败，无推荐数据）")

    report: dict[str, Any] = {
        "stage": "stage1",
        "portrait": {
            "overall_score": scores.get("overall_score"),
            "dimensions": scores.get("dimensions"),
            "norm": scores.get("norm"),
            "strengths": scores.get("strengths") or [],
            "weaknesses": scores.get("weaknesses") or [],
            "confidence": scores.get("confidence") or "低",
        },
        "directions": _sanitize_directions(directions),
        "gap_analysis": None,
        "plan": None,
        "suggestion": None, # v1.1：Stage 1 未选方向 → suggestion 恒为 null
        "notes": notes,
        "confidence": state.get("confidence") or {},
    }
    return report


def assemble_stage2_report(state: GraphState, target_job: str | None = None) -> dict:
    """Stage 2 报告骨架：gap_analysis + plan。"""
    errors = list(state.get("stage_errors") or [])
    notes = [f"该部分分析不完整（{e}）" for e in errors]

    gap_items = state.get("gap_items") or []
    plan = state.get("plan") or {}
    if not gap_items:
        notes.append("该部分分析不完整（差距分析失败，无差距数据）")
    if not plan:
        notes.append("该部分分析不完整（成长计划失败，无计划数据）")

    gap_analysis: dict[str, Any] = {
        "target_job": target_job or state.get("target_job"),
        "items": gap_items,
    }
    if gap_items:
        gap_analysis["confidence_reasons"] = _gap_confidence_reasons(gap_items, state)

    return {
        "stage": "stage2",
        "gap_analysis": gap_analysis,
        "plan": plan,
        "suggestion": build_suggestion(state), # v1.1：完整 Stage 2 才生成，否则 None
        "notes": notes,
        "confidence": state.get("confidence") or {},
    }


def _sanitize_directions(directions: list[dict]) -> list[dict]:
    out = []
    for d in sorted(directions, key=_match_score, reverse=True):
        out.append(
            {
                "job_title": d.get("job_title"),
                "match_score": d.get("match_score"),
                "salary": d.get("salary"),
                "salary_note": d.get("salary_note"),
                "trend": d.get("trend"),
                "heat": d.get("heat"),
                "data_source": d.get("data_source"),
                "education_requirement": d.get("education_requirement"),
                "education_match": d.get("education_match"),
                "competition_note": d.get("competition_note"),
                "certificates_bonus": d.get("certificates_bonus"),
                "recommend_reason": d.get("recommend_reason"),
                "data_grade": d.get("data_grade"), # v1.1：来源等级透传（Agent 不自判）
                "confidence_reasons": d.get("confidence_reasons"), # v1.1：置信度原因拆解
                "salary_comparison": d.get("salary_comparison"), # v1.3：薪资对比透传
            }
        )
    return _dedupe_directions(out)[:5]


def _gap_confidence_reasons(gap_items: list[dict], state: GraphState) -> dict:
    """差距分析置信度原因拆解（确定性组装，仅引用已有数据点）。

    - supporting：差距项均对照 JD 要求（数量）、executor 置信度（如有）。
    - concerns：方法学边界（技能列表可能遗漏隐性能力、JD 动态变化），非数据编造。
    """
    supporting: list[str] = [f"差距逐项对照目标岗位 JD 要求（{len(gap_items)} 项均有依据）"]
    executor_confidence = (state.get("confidence") or {}).get("executor")
    if executor_confidence:
        supporting.append(f"分析置信度为{executor_confidence}，依据画像技能清单与岗位要求生成")
    concerns = [
        "匹配判断基于简历技能列表，未列出的隐性技能/实习经历可能未被计入",
        "岗位要求随招聘市场动态变化，建议以最新 JD 为准",
    ]
    return {"supporting": supporting, "concerns": concerns}


def finalize_report(report: dict, state: GraphState, stage: str) -> dict:
    """报告归一化（v1.1 +）：suggestion + gap_analysis.confidence_reasons +
    norm/directions v1.1 字段归一化补全。

    - norm：LLM 路径常模块归一化（disclaimer 固定文案 + confidence_reasons 确定性补全，QA-BUG-001）。
    - directions：系统派生值优先（state.market_results 同岗位 data_grade/confidence_reasons 覆盖
      LLM，禁止 LLM 自判）+ 缺失补全 + job_title 去重（QA-BUG-002/004）。
    - stage1：suggestion 恒为 None（Stage 1 未选方向）。
    - stage2：gap 有 items 时补 confidence_reasons（缺失才补，避免覆盖上游输出）；
      suggestion 由规则生成（完整报告才非 None，禁止凭空建议）。
    """
    report = dict(report or {})
    portrait = report.get("portrait")
    if isinstance(portrait, dict) and isinstance(portrait.get("norm"), dict):
        portrait["norm"] = normalize_norm_payload(portrait["norm"])
    if isinstance(report.get("directions"), list):
        report["directions"] = _normalize_directions(report["directions"], state)
    if stage == "stage1":
        report.setdefault("suggestion", None)
        return report
    gap = report.get("gap_analysis")
    if isinstance(gap, dict) and gap.get("items") and not gap.get("confidence_reasons"):
        gap["confidence_reasons"] = _gap_confidence_reasons(gap.get("items"), state)
    report["suggestion"] = build_suggestion(state)
    return report


# ---------------------------------------------------------------------------
# v1.1 方向归一化（QA-BUG-002/004）：confidence_reasons 补全 + data_grade
# 系统派生优先 + job_title 去重（LLM 输出路径兜底，市场层已注入时保真透传）。
# ---------------------------------------------------------------------------
def _match_score(d: dict) -> float:
    try:
        return float(d.get("match_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _grade_rank(grade) -> int:
    return {"A": 3, "B": 2, "C": 1}.get(grade, 0)


def _direction_better(candidate: dict, current: dict) -> bool:
    """同 job_title 择优：match_score 高者优先；相同取 data_grade A>B>C>None；仍相同保留先出现者。"""
    c_score = _match_score(candidate)
    p_score = _match_score(current)
    if c_score != p_score:
        return c_score > p_score
    return _grade_rank(candidate.get("data_grade")) > _grade_rank(current.get("data_grade"))


def _dedupe_directions(directions: list[dict]) -> list[dict]:
    """按 job_title 去重（QA-BUG-004）：同岗位保留最优来源（match_score 最高，其次 data_grade）。"""
    best: dict[str, dict] = {}
    order: list[str] = []
    for d in directions or []:
        if not isinstance(d, dict):
            continue
        title = str(d.get("job_title") or "").strip()
        if not title:
            continue
        if title in best:
            if _direction_better(d, best[title]):
                best[title] = d
        else:
            best[title] = d
            order.append(title)
    return [best[t] for t in order]


def _valid_confidence_reasons(reasons) -> bool:
    return (
        isinstance(reasons, dict)
        and isinstance(reasons.get("supporting"), list)
        and bool(reasons.get("supporting"))
        and isinstance(reasons.get("concerns"), list)
    )


def _direction_confidence_reasons(d: dict) -> dict:
    """方向置信度原因确定性组装（仅引用方向已有数据点，禁止编造）。"""
    supporting: list[str] = []
    grade = d.get("data_grade")
    if grade in ("A", "B", "C"):
        supporting.append(f"市场数据来源为{data_grade_name(grade)}（{grade} 级）")
    else:
        supporting.append("市场数据来源已标注（基于公开数据）")
    match_score = d.get("match_score")
    if isinstance(match_score, (int, float)):
        supporting.append(f"方向匹配度 {int(match_score)}，与画像技能/专业方向重合度高")
    concerns: list[str] = []
    salary_note = str(d.get("salary_note") or "")
    if salary_note and "数据较少" not in salary_note and "暂无" not in salary_note:
        concerns.append("薪资为市场近似值，可能含在职样本或口径差异")
    if grade is None:
        concerns.append("市场数据不足，匹配判断基于画像与通用知识")
    return {"supporting": supporting, "concerns": concerns}


def _normalize_directions(directions: list[dict], state: GraphState) -> list[dict]:
    """directions 归一化（QA-BUG-002/004，LLM 输出路径）。

    - data_grade：系统派生值优先——state.market_results 同岗位的 data_grade 为准（LLM 不自判）；
      无系统来源时一律 null（LLM 自判值不作数）。
    - confidence_reasons：系统来源存在则以其为准；否则缺失时按方向已有数据点确定性组装。
    - 去重：同 job_title 保留 match_score 最高/来源最优者。
    """
    system: dict[str, dict] = {}
    for d in state.get("market_results") or []:
        if isinstance(d, dict):
            title = str(d.get("job_title") or "").strip()
            if title:
                system[title] = d
    out: list[dict] = []
    for d in directions:
        if not isinstance(d, dict):
            continue
        nd = dict(d)
        src = system.get(str(nd.get("job_title") or "").strip())
        if src is not None:
            nd["data_grade"] = src.get("data_grade") if src.get("data_grade") in ("A", "B", "C") else None
            nd["confidence_reasons"] = src.get("confidence_reasons") or _direction_confidence_reasons(nd)
            # v1.3：salary_comparison 为确定性系统值，LLM 不得改写（数字来自 market_results）
            nd["salary_comparison"] = src.get("salary_comparison")
        else:
            # 无系统来源 → LLM 不得自判 data_grade（一律 null，等 V1.1 数据管道补 source_type），
            # confidence_reasons 按方向已有数据点确定性补全。
            nd["data_grade"] = None
            if not _valid_confidence_reasons(nd.get("confidence_reasons")):
                nd["confidence_reasons"] = _direction_confidence_reasons(nd)
            # v1.3：无系统来源 → 薪资对比置空（不保留 LLM 自判值，反幻觉）
            nd["salary_comparison"] = None
        out.append(nd)
    return _dedupe_directions(out)
