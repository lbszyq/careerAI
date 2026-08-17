"""career_analysis_node（职业分析 Agent，）：画像 5 维评分 + 常模对比（B-002）+ 优劣势。

- 常模查询：按 毕业年份 × 城市等级（意向城市最高级）× 专业大类 命中 norm_benchmarks；
  表/样本不足 → 降级「样本不足」，不输出精确分位（C-009）。
- LLM 优先，规则评分兜底（confidence=低 并标注 generated_by=rule_template）。
- schema 校验：LLM 输出缺失/非法（overall_score/五维/strengths/weaknesses）
  → 抛 LLMFormatError 触发恰好 1 次纠正重试，仍失败走规则兜底；不静默 or 0 / or [] / clamp。
"""
import json
import logging

from app.ai.agents.deps import AgentDeps
from app.ai.fallback.scoring import score_profile
from app.ai.guard.guards import get_guard
from app.ai.llm.exceptions import LLMError, LLMFormatError
from app.ai.norm.benchmarks import ground_norm_to_code, lookup_norm_benchmark, map_major_category
from app.ai.norm.city_tiers import resolve_cities_tier
from app.ai.prompts import render_prompt
from app.ai.schemas import GraphState

logger = logging.getLogger("careerai.ai.agents.career_analysis")

_DIM_KEYS = {"technical", "project", "academic", "soft_skill", "industry_knowledge"}


async def career_analysis_node(state: GraphState, deps: AgentDeps) -> dict:
    profile = state.get("profile") or {}
    norm = state.get("norm_benchmark")

    if norm is None and deps.db is not None:
        norm = await lookup_norm_benchmark(
            deps.db,
            graduation_year=profile.get("graduation_year"),
            city_tier=resolve_cities_tier(state.get("preferred_cities")),
            major_category=map_major_category(profile.get("major")),
        )

    scores = None
    injected = False
    if deps.llm is not None and deps.llm.is_available:
        injected = get_guard().check_input(
            json.dumps(profile, ensure_ascii=False), context="career_profile"
        ).blocked
        if injected:
            logger.warning("career_analysis: profile 被 Guard 拦截，跳过 LLM 走规则兜底")

    if deps.llm is not None and deps.llm.is_available and not injected:
        try:
            scores = await _analyze_with_llm(profile, norm, deps)
        except LLMError as exc:
            logger.warning("career_analysis: LLM 失败转规则兜底: %s", exc)
    if scores is None:
        scores = score_profile(profile, norm if not isinstance(norm, dict) else None)
        errors = list(state.get("stage_errors") or [])
        if injected:
            errors.append("输入包含不安全内容，已拒绝 LLM 解析")
        elif scores.get("generated_by") == "rule_template":
            errors.append("职业分析使用规则模板（LLM 不可用或失败）")
        return {
            "scores": scores,
            "norm_benchmark": _norm_payload(profile, norm),
            "confidence": {"analysis": scores.get("confidence", "低")},
            "stage_errors": errors,
        }

    return {
        "scores": scores,
        "norm_benchmark": _norm_payload(profile, norm),
        "confidence": {"analysis": scores.get("confidence", "中")},
        "stage_errors": state.get("stage_errors") or [],
    }


async def _analyze_with_llm(profile: dict, norm, deps: AgentDeps) -> dict:
    norm_payload = _norm_payload(profile, norm)
    prompt = render_prompt("career_analysis.md", 
        profile=json.dumps(profile, ensure_ascii=False),
        norm_benchmark=json.dumps(norm_payload, ensure_ascii=False) if norm_payload else "null（样本不足或无常模数据）",
    )
    user_prompt = "请基于上述画像与常模数据输出评分 JSON。"
    data = await deps.llm.complete_json(
        system_prompt=prompt,
        user_prompt=user_prompt,
        node_name="career_analysis_node",
    )
    try:
        return _validate_scores(data, norm_payload)
    except LLMFormatError as exc:
        # schema 校验失败不静默降级——恰好 1 次额外调用（带纠正提示），
        # 最坏 2 次/节点（非 3 次）；仍失败 → LLMFormatError 上抛 → 节点转规则兜底（confidence=低）。
        logger.warning("career_analysis: 评分结构校验失败，纠正重试 1 次: %s", exc)
        corrected = (
            user_prompt
            + f"\n\n（重要：上一轮输出未通过结构校验：{exc}。"
            + "请重新输出符合要求的评分 JSON：overall_score 与五维均为 0-100 数字，五维缺一不可。）"
        )
        data = await deps.llm.complete_json(
            system_prompt=prompt,
            user_prompt=corrected,
            node_name="career_analysis_node:schema_retry",
        )
        return _validate_scores(data, norm_payload)


def _coerce_score(value, field: str) -> int:
    """0-100 整数分数校验：None/非数字/越界 → LLMFormatError，不静默 or 0/clamp。

    - 接受 int/float（截断为 int）与数字字符串（如 "78"/"78.5"）；
    - bool 属非数字（isinstance(True, int) 为 True，须先行排除）。
    """
    if value is None or isinstance(value, bool):
        raise LLMFormatError(f"{field} 缺失或非数字")
    if isinstance(value, str):
        stripped = value.strip()
        try:
            score = int(float(stripped))
        except (ValueError, OverflowError):
            raise LLMFormatError(f"{field} 非数字") from None
    elif isinstance(value, (int, float)):
        score = int(value)
    else:
        raise LLMFormatError(f"{field} 非数字")
    if not 0 <= score <= 100:
        raise LLMFormatError(f"{field} 超出 0-100")
    return score


def _validate_string_list(value, field: str) -> list:
    """字符串列表校验：缺失/非 list/含非字符串项 → LLMFormatError（不静默 or []）。"""
    if not isinstance(value, list):
        raise LLMFormatError(f"{field} 缺失或非数组")
    if any(not isinstance(item, str) for item in value):
        raise LLMFormatError(f"{field} 含非字符串项")
    return value


def _validate_scores(data, norm_payload) -> dict:
    """LLM 评分输出 schema 校验（/：缺失/非法显式失败，不静默填默认值）。

    - overall_score 与五维统一语义：必须为 0-100 数字，None/非数字/越界 → LLMFormatError
      （触发上层恰好 1 次纠正重试；原先五维 int(None) TypeError 崩溃、max(0,min(100)) 静默
      clamp、overall 缺失静默 0 分等行为全部消除）；
    - dimensions 必须为含全部 5 键的对象；strengths/weaknesses 必须为字符串数组。
    """
    if not isinstance(data, dict):
        raise LLMFormatError("输出不是 JSON 对象")
    overall = _coerce_score(data.get("overall_score"), "overall_score")
    raw_dims = data.get("dimensions")
    if not isinstance(raw_dims, dict):
        raise LLMFormatError("dimensions 缺失或非对象")
    missing = sorted(set(_DIM_KEYS) - set(raw_dims))
    if missing:
        raise LLMFormatError(f"dimensions 缺少维度: {', '.join(missing)}")
    dims = {k: _coerce_score(raw_dims.get(k), f"dimensions.{k}") for k in sorted(_DIM_KEYS)}
    strengths = _validate_string_list(data.get("strengths"), "strengths")
    weaknesses = _validate_string_list(data.get("weaknesses"), "weaknesses")
    # （反幻觉底线，接地 seam）：常模事实字段强制以 code 层 norm_payload 为准——
    # LLM norm 的事实字段（band/sample_size/cohort/contains_employed/note/confidence/p25/p50/p75）
    # 全部被 code 值覆盖；code payload 无的键（<30 时无 p25/p50/p75）剔除；confidence_reasons
    # 按 code 事实重建（不保真保留 LLM 写的「样本量为 120」等伪造数字）；norm_payload 为 None
    # → 丢弃 LLM norm（最终 portrait.norm 为 None，不伪造 norm 对象）。QA-BUG-001
    # 归一化补全仍由 normalize_norm_payload 承接（disclaimer 固定文案 + reasons 确定性组装）。
    raw_norm = ground_norm_to_code(data.get("norm"), norm_payload)
    return {
        "overall_score": overall,
        "dimensions": dims,
        "norm": raw_norm,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "confidence": data.get("confidence") or "中",
        "generated_by": "llm",
    }


def _cohort(profile: dict, norm) -> str:
    return f"{norm.graduation_year}届 × {norm.city_tier} × {norm.major_category}"


def _norm_payload(profile: dict, norm) -> dict | None:
    """归一化常模载荷（诚实下线）。

    - None / dict → None：dict 形态 norm 载荷来源不可验证（可能为上游旁路注入的
      伪造 payload，R5 堵旁路），一律归一为 None——无真实常模 → 隐藏；
    - NormBenchmark 实例 → to_dict：样本<30 → None（隐藏语义），≥30 → 完整载荷。
    """
    if norm is None or isinstance(norm, dict):
        return None
    return norm.to_dict(cohort=_cohort(profile, norm))
