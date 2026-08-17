# -*- coding: utf-8 -*-
"""事实接地审计（/ CR-004「禁止凭空建议」机制化闭环）。

报告生成链路末尾硬审计：每条「建议/差距/证据」claim 必须可映射到
user_profiles（state.profile）/ market_data（RAG 命中、state.market_results、
state.target_job_jd_summary）/ career_directions（方向记录）——无据 claim **删除**
而非仅降置信度（调研落地点 2：上游 /apply Factual Grounding Audit「claim 必须可追溯，无据即删」）。

审计面（只收紧生成规则，契约字段结构 confidence_reasons/evidence/jd_source 不变）：
- gap_analysis.items[]：skill / jd_source / evidence 任一缺失、占位、或 jd_source 无法映射到
  JD 要求来源 → 整项删除（无据差距 claim 删除，不降置信度标注）
  - （关键词逃逸修复）：fallback 标注改服务端判定——依据池为空（RAG 无结果）时
    由代码打结构化标记 jd_source_kind=fallback；LLM 文本自报「未检索/兜底/暂无/通用要求」等
    关键词不再构成通过依据；依据池非空时 LLM 无论写什么都按依据池映射判定
- directions[]：job_title / match_score 缺失、或 job_title 不在 market_results 记录池
  （market_data/career_directions 数据源）→ 整条删除；salary / trend / heat 无市场来源标注
  （data_source 非空或 data_grade A/B/C）→ 置空并标注「该领域暂时数据较少」（无据市场 claim 删除）
- suggestion：reasons 每条必须引用报告内已有数据点（方向名/匹配分/画像维度分/差距技能）；
  无引用 → 删除该 reason；reasons 清空或报告内无方向/差距 → suggestion=None。
  引用一致性（T /）：suggestion 文本引用了报告内已被审计删除的无据差距技能时，
  **基于审计后保留的差距数据重建**建议层（而非整卡置 None）——无据差距删除后建议卡仍可展示，
  重建输出仅引用报告内保留数据；报告内差距/方向依据全部被删 → suggestion=None（禁止凭空建议）。

有据 claim 的 confidence_reasons / evidence / jd_source 原样保留（验证标准 3：不受影响）。
"""
import json
import logging
from typing import Any

from app.ai.fallback.suggestion import build_suggestion_from_parts
from app.ai.schemas import GraphState

logger = logging.getLogger("careerai.ai.grounding")

# 占位式「依据」黑名单（无信息量，视为无据）
_PLACEHOLDER_EVIDENCE = frozenset(
    {"无", "暂无", "无证据", "无依据", "无数据", "无说明", "-", "--", "n/a", "na", "none", "null", "unknown"}
)

_DATA_GRADES = ("A", "B", "C")
_NO_SALARY_NOTE = "该领域暂时数据较少"
# fallback 标注由服务端代码依据「依据池为空（RAG 无结果）」判定（jd_source_kind=fallback），
# 不再有「LLM 文本自报关键词即通过」的逃逸口。


def _non_placeholder_text(value: Any, min_len: int = 2) -> bool:
    """非空且非占位文案（长度阈值 + 占位黑名单）。"""
    text = str(value or "").strip()
    if len(text) < min_len:
        return False
    return text.lower() not in _PLACEHOLDER_EVIDENCE


def _valid_match_score(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _jd_pool(requirements: list | None, jd_summary: dict | None) -> list[str]:
    """JD 要求依据池（服务端事实）：requirements + jd_summary 提取的非空条目。

    依据池为空 = RAG 未检索到该岗位 JD 要求（架构 / 允许「通用要求」兜底的唯一前提，
    由服务端代码判定，不依赖 LLM 文本）。
    """

    def _entry_text(value) -> str:
        # JD 要求项支持 dict（{"name"/"skill", "required_level"}）与 str 两种形态
        if isinstance(value, dict):
            return str(value.get("name") or value.get("skill") or "")
        return str(value or "")

    pool: list[str] = []
    for req in requirements or []:
        entry = _entry_text(req)
        if entry.strip():
            pool.append(entry)
    summary = jd_summary or {}
    for key in ("job_title", "education_requirement", "summary_note"):
        value = summary.get(key)
        if str(value or "").strip():
            pool.append(str(value))
    for value in summary.get("required_skills") or []:
        entry = _entry_text(value)
        if entry.strip():
            pool.append(entry)
    return pool


def _jd_source_mapped(jd_source: str, requirements: list | None, jd_summary: dict | None, skill: str) -> bool:
    """jd_source 映射到 JD 要求来源（market_data 侧）：requirements/jd_summary 池双向子串包含。

    - 依据池为空（RAG 无数据）→ 恒 False：fallback 标注由 _jd_source_kind 依据服务端事实
      打结构化标记，**不再按 LLM 文本关键词放行**（/ 关键词逃逸修复）。
    - skill 名与 requirements 任一关联也算通过（skill 是差距对象，requirements 是 JD 技能清单）。
    """
    text = jd_source.lower()
    pool = _jd_pool(requirements, jd_summary)
    if not pool:
        return False
    for entry in pool:
        entry_l = str(entry).lower()
        if entry_l and (entry_l in text or text in entry_l):
            return True
    skill_l = str(skill or "").lower()
    for entry in pool:
        entry_l = str(entry).lower()
        if entry_l and skill_l and (entry_l in skill_l or skill_l in entry_l):
            return True
    return False


def _jd_source_kind(jd_source: str, requirements: list | None, jd_summary: dict | None, skill: str) -> str | None:
    """jd_source 来源类别（服务端判定）：

    - "fallback"：依据池真的为空（RAG 无结果）→ 服务端打结构化 fallback 标记，正常放行；
      判定只依据服务端事实，LLM 文本自报关键词不参与（反幻觉底线）。
    - "jd"：依据池非空且 jd_source 映射到池（检索到的真实 JD 要求）。
    - None：依据池非空但 jd_source 无法映射（LLM 写「未检索/兜底/暂无」等词但服务端实际有
      依据即落此分支）→ 不通过 grounding（疑似编造）。
    """
    if not _jd_pool(requirements, jd_summary):
        return "fallback"
    return "jd" if _jd_source_mapped(jd_source, requirements, jd_summary, skill) else None


def _gap_item_grounded(item: dict, state: GraphState) -> tuple[bool, str, str | None]:
    """差距 claim 接地判定：skill + jd_source（JD 要求溯源）+ evidence（用户侧依据）。

    返回 (是否通过, 未通过原因, jd_source_kind 服务端标注)：
    - jd_source_kind="fallback"：依据池为空（RAG 无结果）→ 服务端结构化 fallback 标注；
    - jd_source_kind="jd"：jd_source 映射到依据池；
    - 未通过时 kind=None。
    """
    skill = str(item.get("skill") or "").strip()
    jd_source = str(item.get("jd_source") or "").strip()
    evidence = str(item.get("evidence") or "").strip()
    if not skill:
        return False, "skill 缺失", None
    if not _non_placeholder_text(jd_source, min_len=4):
        return False, "jd_source 缺失/占位（无法追溯 JD 要求）", None
    if not _non_placeholder_text(evidence):
        return False, "evidence 缺失/占位（无用户侧依据）", None
    kind = _jd_source_kind(
        jd_source, state.get("target_job_requirements") or [], state.get("target_job_jd_summary") or {}, skill
    )
    if kind is None:
        return False, "jd_source 无法映射到 JD 要求来源（疑似编造）", None
    return True, "", kind


def _stamp_jd_source_kind(item: dict, kind: str | None) -> dict:
    """在 item 副本上打服务端 jd_source_kind 标注（不原地修改原 item）。

    LLM 若自报 jd_source_kind 一律被服务端判定覆盖（反幻觉底线：标注只能服务端判定）。
    """
    if not kind:
        return item
    out = dict(item)
    out["jd_source_kind"] = kind
    return out


def _audit_gap_items(gap_analysis: dict, state: GraphState) -> dict:
    """差距分析审计：无据差距 claim 整项删除（confidence_reasons 等结构原样保留）。

    ：通过项由服务端在副本上打 jd_source_kind 结构化标注（fallback/jd），
    LLM 文本自报关键词不再构成通过依据。
    """
    out = dict(gap_analysis)
    kept: list[dict] = []
    for item in gap_analysis.get("items") or []:
        if not isinstance(item, dict):
            continue
        grounded, reason, kind = _gap_item_grounded(item, state)
        if grounded:
            kept.append(_stamp_jd_source_kind(item, kind))
        else:
            logger.info("grounding: 删除无据差距 claim（%s）: %r", reason, item.get("skill"))
    out["items"] = kept
    return out


def _has_market_source(direction: dict) -> bool:
    """方向的市场来源标注：data_source 非空或 data_grade A/B/C（系统派生）。"""
    if str(direction.get("data_source") or "").strip():
        return True
    return direction.get("data_grade") in _DATA_GRADES


def _direction_in_market_pool(direction: dict, market_results: list | None) -> bool:
    """方向 job_title 必须映射到 market_results（market_data 记录池，落库为 career_directions 的数据源）。

    池为空（市场 Agent 完全失败）或 job_title 不在池中 → 无 market_data 记录依据 → 无据方向删除。
    市场 Agent 的 RAG 降级路径（通用模板/LLM 生成）同样输出到 market_results，池非空，不受影响。
    """
    title = str(direction.get("job_title") or "").strip().lower()
    pool = [
        str(d.get("job_title") or "").strip().lower()
        for d in (market_results or [])
        if isinstance(d, dict) and str(d.get("job_title") or "").strip()
    ]
    if not pool:
        return False
    return any(p and (p in title or title in p) for p in pool)


def _audit_directions(directions: list | None, state: GraphState) -> list[dict]:
    """方向审计：
    - job_title / match_score 缺失 → 整条删除（无岗位对象 / 无画像映射依据）
    - job_title 不在 market_results 记录池 → 整条删除（无 market_data 依据，三表基准）
    - salary / trend / heat 无市场来源标注 → 置空（删除无据市场 claim，不降置信度）
    """
    out: list[dict] = []
    for d in directions or []:
        if not isinstance(d, dict):
            continue
        job_title = str(d.get("job_title") or "").strip()
        if not job_title:
            logger.info("grounding: 删除无据方向（job_title 缺失）")
            continue
        if not _valid_match_score(d.get("match_score")):
            logger.info("grounding: 删除无据方向（match_score 缺失，无画像映射依据）: %s", job_title)
            continue
        nd = dict(d)
        if not _direction_in_market_pool(nd, state.get("market_results") or []):
            logger.info("grounding: 删除无据方向（market_results 无对应记录）: %s", job_title)
            continue
        if not _has_market_source(nd):
            if nd.get("salary") is not None:
                nd["salary"] = None
                nd["salary_note"] = _NO_SALARY_NOTE
            if nd.get("trend"):
                nd["trend"] = None
            if nd.get("heat"):
                nd["heat"] = None
        out.append(nd)
    return out


def _suggestion_anchors(report: dict) -> list[str]:
    """报告内可引用数据点：方向名/匹配分/画像维度分/差距技能（契约：reasons 引用报告内数据）。"""
    anchors: list[str] = []
    for d in report.get("directions") or []:
        if isinstance(d, dict):
            title = str(d.get("job_title") or "").strip()
            if title:
                anchors.append(title)
            score = d.get("match_score")
            if _valid_match_score(score):
                anchors.append(str(int(score)))
    dims = (report.get("portrait") or {}).get("dimensions") or {}
    for value in dims.values():
        if _valid_match_score(value):
            anchors.append(str(int(value)))
    gap = report.get("gap_analysis") or {}
    # Stage2 报告 result 无 directions 字段（前端从 career_directions 表读），
    # 方向依据以 gap_analysis.target_job 为准（suggestion 引用目标岗位）。
    target_job = str(gap.get("target_job") or "").strip()
    if target_job:
        anchors.append(target_job)
    for g in gap.get("items") or []:
        if isinstance(g, dict):
            skill = str(g.get("skill") or "").strip()
            if skill:
                anchors.append(skill)
    return anchors


def _reason_grounded(reason: Any, anchors: list[str]) -> bool:
    text = str(reason or "").strip()
    if not text:
        return False
    return any(anchor and anchor in text for anchor in anchors)


def _rebuild_suggestion(report: dict, state: GraphState) -> dict | None:
    """建议层重建（T）：基于审计后报告数据确定性重建 suggestion。

    - gap_items 取审计后 report.gap_analysis.items（核心：不再引用被审计删除的无据差距）
    - directions 取审计后 report.directions；Stage2 报告 result 无 directions 字段时
      以 state.market_results 兜底（方向依据以 gap_analysis.target_job 为准）
    - scores 取 state.scores（Stage2 执行器注入的 Stage1 画像；报告 portrait 为其副本，
      重建后仍由 _suggestion_anchors 校验「画像评分」reason 是否落在报告内数据点）
    """
    gap = report.get("gap_analysis") or {}
    directions = report.get("directions") or []
    if not directions:
        directions = [d for d in (state.get("market_results") or []) if isinstance(d, dict)]
    target_job = str(gap.get("target_job") or "").strip() or state.get("target_job") or ""
    return build_suggestion_from_parts(
        scores=state.get("scores") or {},
        directions=directions,
        gap_items=gap.get("items") or [],
        target_job=target_job or None,
    )


def _audit_suggestion(suggestion: Any, report: dict, state: GraphState) -> dict | None:
    """建议层审计：reasons 每条必须引用报告内数据点；无引用删除；依据清空 → None。

    - 引用一致性（+ T）：suggestion 文本引用报告内已被审计删除的无据差距技能时，
      不再整卡删除——基于审计后保留的差距数据重建（建议卡可展示）；仅当报告内差距/方向依据
      全部无据被删时才置 None（无据即删，禁止凭空建议重建）。
    """
    if not isinstance(suggestion, dict):
        return None
    gap = report.get("gap_analysis") or {}
    gap_items = gap.get("items") or []
    if not gap_items:
        return None # 报告内无差距数据 → suggestion 无引用依据
    directions = report.get("directions") or []
    if not directions and not str(gap.get("target_job") or "").strip():
        return None # 无方向依据（无 directions 且无目标岗位）→ suggestion 无引用依据
    report_skills = {str(g.get("skill") or "").strip() for g in gap_items if isinstance(g, dict)}
    state_skills = {str(g.get("skill") or "").strip() for g in (state.get("gap_items") or []) if isinstance(g, dict)}
    removed = state_skills - report_skills
    if removed:
        text = json.dumps(suggestion, ensure_ascii=False)
        if any(skill and skill in text for skill in removed):
            logger.info("grounding: suggestion 引用已删除的无据技能 → 基于审计后差距重建: %r", sorted(removed))
            rebuilt = _rebuild_suggestion(report, state)
            if rebuilt is None:
                return None # 审计后数据不足（差距/方向依据全被删）→ 无据即删
            anchors = _suggestion_anchors(report)
            reasons = [r for r in (rebuilt.get("reasons") or []) if _reason_grounded(r, anchors)]
            if not reasons:
                return None
            out = dict(rebuilt)
            out["reasons"] = reasons
            return out
    anchors = _suggestion_anchors(report)
    reasons = [r for r in (suggestion.get("reasons") or []) if _reason_grounded(r, anchors)]
    if not reasons:
        return None
    out = dict(suggestion)
    out["reasons"] = reasons
    return out


def audit_report_grounding(report: dict, state: GraphState) -> dict:
    """报告生成链路末尾硬审计：无据 claim 删除（返回新结构，不原地修改）。

    删除后输出结构与契约一致：gap_analysis.items 可为空数组、direction 字段置空、
    suggestion 可置 None——均为契约允许的可选/可空形态。
    """
    out = dict(report or {})
    gap = out.get("gap_analysis")
    if isinstance(gap, dict):
        out["gap_analysis"] = _audit_gap_items(gap, state)
    if isinstance(out.get("directions"), list):
        out["directions"] = _audit_directions(out["directions"], state)
    out["suggestion"] = _audit_suggestion(out.get("suggestion"), out, state)
    return out
