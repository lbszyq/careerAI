"""executor_node（执行 Agent，）：差距分析（三级+权重，追溯 JD 要求）+ 三阶段成长计划。

（报告质量修复）：差距分析与成长计划**仅由 LLM 生成**（去掉规则兜底）。
- LLM 输出不完整（gap_items / plan.tasks 为空）→ 重试 1 次；仍不完整 / LLM 不可用 /
  调用失败 → executor 节点失败：plan=None + stage_errors 记录「LLM 生成成长计划失败」
  （planner 组装「报告成功但计划缺失」，前端显示成长计划生成失败，而非整单失败 / 死模板兜底）。
- JD 技能分级（required_level core/nice-to-have，权威=市场 Agent）+ 技能蕴含推理
  （复用 IMPLICATION_MAP）+ 分级权重（core > nice-to-have），全部确定性后处理。
"""
import json
import logging

from app.ai.agents.deps import AgentDeps
from app.ai.fallback.plan_capability import stage_capability_fields
from app.ai.fallback.resume_parser import (
    IMPLICATION_LEVEL_FULL,
    IMPLICATION_LEVEL_PARTIAL,
    IMPLICATION_MAP,
)
from app.ai.guard.guards import get_guard
from app.ai.llm.exceptions import LLMError
from app.ai.prompts import render_prompt
from app.ai.schemas import GraphState

logger = logging.getLogger("careerai.ai.agents.executor")

_STAGE_LABELS = {
    "short": "短期（1 个月内）",
    "mid": "中期（1-3 个月）",
    "long": "长期（3 个月以上）",
}

# 求职准备类任务关键词：用于 long 阶段结构必含的确定性补齐判定
_JOB_PREP_KEYWORDS = ("简历", "面试", "投递", "求职")

# LLM 输出不完整时重试次数（含首次共 _LLM_ATTEMPTS 次，即「重试 1 次」）
_LLM_ATTEMPTS = 2

# JD 技能分级枚举（权威=市场 Agent；缺失默认 core，避免加分技能被降权）
_REQUIRED_LEVELS = ("core", "nice-to-have")


def _default_stage(idx: int, total: int) -> str:
    """无 stage 标注时按任务顺序落入三阶段（Q8 结构稳定）。"""
    if total <= 0:
        return "short"
    ratio = idx / total
    if ratio < 1 / 3:
        return "short"
    if ratio < 2 / 3:
        return "mid"
    return "long"


def _gap_skill_for_task(task: dict, gap_items: list[dict]) -> str:
    """从差距清单中找任务对应的技能（用于兜底验证口径文案）。"""
    name = task.get("name") or ""
    for g in gap_items or []:
        skill = str(g.get("skill") or "")
        if skill and skill in name:
            return skill
    return "目标技能"


def _normalize_plan_tasks(
    plan: dict | None,
    gap_items: list[dict],
    target_job: str = "",
    jd_summary: dict | None = None,
) -> dict:
    """Q8 计划具体化：任务必须含 name/resource/duration/stage/acceptance_criteria。

    - 无名称或无具体资源的任务视为泛化/空任务，直接剔除（禁止"多学习"类口号进计划）；
    - 缺 acceptance_criteria 时按差距技能补兜底验证口径，保证每项任务可验证；
    - v1.1：阶段级能力化字段（goal/why/verify/resume_value/stage_completion）
      由 stage_capability_fields 确定性补齐（LLM 未输出时兜底），并同步重算 tasks_count。
    """
    plan = dict(plan or {})
    raw_tasks = plan.get("tasks") or []
    tasks: list[dict] = []
    for idx, t in enumerate(raw_tasks):
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        resource = str(t.get("resource") or "").strip()
        if not name or not resource:
            logger.warning("executor: 剔除空泛任务（无名称/资源）: %r", t)
            continue
        task = dict(t)
        task["stage"] = task.get("stage") or _default_stage(idx, len(raw_tasks))
        task["duration"] = task.get("duration") or "2 周"
        task["sort_order"] = int(task.get("sort_order") or (idx + 1))
        if not str(task.get("acceptance_criteria") or "").strip():
            skill = _gap_skill_for_task(task, gap_items)
            task["acceptance_criteria"] = (
                f"能独立完成「{skill}」相关的一个可验证成果（练习/小项目/笔记并实操演示）"
            )
        tasks.append(task)

    # long 阶段确定性补齐求职准备任务（LLM 可能忽略 Prompt 约束，结构必含兜底）
    tasks = _ensure_long_stage_job_prep(tasks)

    plan["tasks"] = tasks
    counts = {"short": 0, "mid": 0, "long": 0}
    for t in tasks:
        counts[t.get("stage", "short")] = counts.get(t.get("stage", "short"), 0) + 1
    # v1.1：阶段级能力化字段（goal/why/verify/resume_value/stage_completion）确定性补齐；
    # label/tasks_count 以实际任务清单为准，能力化字段由 JD/差距数据推导（不新增事实）。
    plan["stages"] = {
        stage: {
            **stage_capability_fields(stage, tasks, target_job, gap_items),
            "tasks_count": counts[stage],
        }
        for stage in _STAGE_LABELS
    }
    return plan


def _ensure_long_stage_job_prep(tasks: list[dict]) -> list[dict]:
    """：long 阶段若缺求职准备任务（关键词：简历/面试/投递/求职），确定性追加。

    Prompt 约束（executor.md 规则 5.2）是「尽力而为」，真实 LLM 可能不遵守；求职准备属
    结构必含，与 stage_capability_fields 的确定性补齐同思路，在此结构化兜底（不依赖 Prompt）。
    """
    long_tasks = [t for t in tasks if t.get("stage") == "long"]
    has_job_prep = any(
        any(kw in str(t.get("name") or "") for kw in _JOB_PREP_KEYWORDS)
        for t in long_tasks
    )
    if has_job_prep:
        return tasks
    return tasks + [
        {
            "name": "求职准备：优化简历 + 模拟面试 + 岗位投递",
            "resource": "牛客网面经 / 简历优化模板 / 目标企业 JD 拆解 / 招聘平台投递",
            "duration": "1 个月",
            "stage": "long",
            "sort_order": len(tasks) + 1,
            "acceptance_criteria": "完成 3 场模拟面试并复盘，投递 10 家目标岗位，简历按 STAR 改写完成",
        }
    ]


def _inject_gap_data_grade(gap_items: list[dict], jd_summary: dict | None) -> list[dict]:
    """v1.1：gap item 透传 data_grade（来源=市场 Agent JD 摘要，禁止自判；无 → 不注入）。

    ：gap 项是技能维度，溯源对象为技能来源——优先 skills_data_grade（job_post=B），
    缺失时回落 data_grade（薪资权威来源等级；LLM 路径仅 data_grade）。
    """
    grade = (jd_summary or {}).get("skills_data_grade") or (jd_summary or {}).get("data_grade")
    if not grade:
        return list(gap_items or [])
    out: list[dict] = []
    for g in gap_items or []:
        item = dict(g)
        item["data_grade"] = grade # 系统派生值为准（覆盖 LLM 残留，禁止自判）
        out.append(item)
    return out


def _inject_gap_required_level(gap_items: list[dict], requirements: list) -> list[dict]:
    """：gap item 透传 required_level（权威=市场 Agent JD 要求分级，禁止 LLM 自判）。

    - requirements 项支持 dict（{"name"/"skill", "required_level"}）与 str（无分级 → core）；
    - 未匹配到权威分级的项：保留 LLM 输出（合法值），否则 core（安全默认，避免加分技能被降权）。
    """
    level_by_skill: dict[str, str] = {}
    for req in requirements or []:
        if isinstance(req, dict):
            name = str(req.get("name") or req.get("skill") or "").strip()
            level = str(req.get("required_level") or "").strip().lower()
        else:
            name = str(req or "").strip()
            level = "core"
        if name and level in _REQUIRED_LEVELS:
            level_by_skill[name.lower()] = level
    out: list[dict] = []
    for g in gap_items or []:
        item = dict(g)
        skill = str(item.get("skill") or "").strip().lower()
        llm_level = str(item.get("required_level") or "").strip().lower()
        item["required_level"] = level_by_skill.get(
            skill,
            llm_level if llm_level in _REQUIRED_LEVELS else "core",
        )
        out.append(item)
    return out


def _normalize_skill_sources(profile_skills: list, profile_skills_sources) -> list[str]:
    """（防御）：skills_sources 归一为与有效技能索引对齐的 provenance 数组。

    - 缺失（None/空）、非法枚举（非 literal/inferred）、长度不匹配（不足按缺省补）→
      默认 literal（保守默认：不因数据瑕疵误标 inferred，不崩溃）；
    - 仅统计有效技能（str 非空），与 _apply_skill_implications 的 user_skills 口径一致。
    """
    skills = [str(s or "").strip() for s in (profile_skills or []) if str(s or "").strip()]
    sources = list(profile_skills_sources or [])
    return [
        (sources[i] if i < len(sources) and sources[i] in ("literal", "inferred") else "literal")
        for i in range(len(skills))
    ]


def _apply_skill_implications(
    gap_items: list[dict], profile_skills: list, profile_skills_sources=None
) -> list[dict]:
    """//：技能蕴含推理（复用 IMPLICATION_MAP 蕴含等级）+「已具备」接地反幻觉
    + provenance 标记（技能来源，供差距分析降权/标注）。

    - 蕴含等级：框架/工具→语言（fastapi→python 等）=「已具备」硬依赖——gap 判
      「不具备/部分具备」→ 升级为「已具备」（修复「会 FastAPI 判 Python 部分具备」保守误判）；
      框架→框架/相关技术（langgraph→langchain 等）=「部分具备」——「不具备」→「部分具备」，
      且 LLM 幻觉判「已具备」→ 压回「部分具备」（可快速上手 ≠ 已掌握，反幻觉镜像）；
    - 状态转换矩阵（定案）：不具备→已具备（有框架→语言蕴含依据）、已具备→保持已具备
      （有依据，防被降级分支误伤）、无依据已具备→降级（回归，反幻觉）；
    - 反幻觉降级：无字面匹配且无蕴含依据时 LLM 判「已具备」→ 降级为「部分具备」
      （子串相关）或「不具备」，禁止凭空判已具备；
    - provenance：gap item 标记技能判定来源——
      literal=用户技能字面具备；inferred=由 IMPLICATION_MAP 蕴含推出（附 inferred_kind=
      已具备/部分具备）；none=无依据（反幻觉降级）。蕴含触发只从 literal 用户技能发起
      （inferred 技能不连环蕴含，防推断放大）；FULL 蕴含 inferred 不降权（硬依赖），
      PARTIAL 蕴含 inferred 由 _apply_required_level_weights 同档内打折。
    """
    skills = [str(s or "").strip() for s in (profile_skills or []) if str(s or "").strip()]
    sources = _normalize_skill_sources(skills, profile_skills_sources)
    literal_skills = {
        s.lower() for s, src in zip(skills, sources) if src == "literal"
    }
    # 蕴含技能 → (触发技能, 蕴含等级)；首个触发者为准（setdefault，多触发源时取先到者）
    implied_by_user: dict[str, tuple[str, str]] = {}
    for skill in literal_skills:
        for implied, impl_level in IMPLICATION_MAP.get(skill, ()):
            implied_by_user.setdefault(implied, (skill, impl_level))
    out: list[dict] = []
    for g in gap_items or []:
        if not isinstance(g, dict):
            # 结构防御：非 dict 项安全透传（不崩溃、不误升级）
            out.append(g)
            continue
        item = dict(g)
        skill = str(item.get("skill") or "").strip().lower()
        level = str(item.get("level") or "")
        info = implied_by_user.get(skill)
        if skill in literal_skills:
            item["provenance"] = "literal"
        elif info:
            trigger, impl_level = info
            item["provenance"] = "inferred"
            item["inferred_kind"] = impl_level
            if impl_level == IMPLICATION_LEVEL_FULL:
                # 框架→语言硬依赖：不具备/部分具备 → 已具备（修复保守误判）；已具备保持（有依据防误伤）
                if level in ("不具备", "部分具备"):
                    item["level"] = IMPLICATION_LEVEL_FULL
                    item["evidence"] = (
                        f"用户技能「{trigger}」蕴含「{item.get('skill')}」"
                        "（框架/工具依赖语言，硬前置），视为已具备"
                    )
            else:
                # 框架→框架/相关技术：不具备 → 部分具备；LLM 幻觉已具备 → 压回部分具备
                if level == "不具备":
                    item["level"] = IMPLICATION_LEVEL_PARTIAL
                    item["evidence"] = (
                        f"用户技能「{trigger}」蕴含「{item.get('skill')}」相关能力，视为部分具备"
                    )
                elif level == IMPLICATION_LEVEL_FULL:
                    item["level"] = IMPLICATION_LEVEL_PARTIAL
                    item["evidence"] = (
                        f"用户技能「{trigger}」与「{item.get('skill')}」相关（可快速上手），"
                        "上限为部分具备，不得判已具备"
                    )
        elif level == IMPLICATION_LEVEL_FULL and skill not in literal_skills:
            # 反幻觉降级：判已具备必须有依据（用户技能字面匹配 或 蕴含依据）
            item["provenance"] = "none"
            related = next((s for s in literal_skills if s and (skill in s or s in skill)), "")
            if related:
                item["level"] = IMPLICATION_LEVEL_PARTIAL
                item["evidence"] = f"用户技能「{related}」与「{item.get('skill')}」相关，视为部分具备"
            else:
                item["level"] = "不具备"
                item["evidence"] = f"用户技能列表不含「{item.get('skill')}」"
        else:
            item["provenance"] = "none"
        out.append(item)
    return out


def _apply_required_level_weights(gap_items: list[dict]) -> list[dict]:
    """/：分级权重硬约束——core 权重 > nice-to-have 权重 + PARTIAL inferred 打折。

    - required_level 权威=市场 Agent 分级（_inject_gap_required_level 已注入，缺失视为 core）；
    - 档位基准权重 core:2 / nice-to-have:1，按项归一化合计≈1——任何 core 项权重 > 任何
      nice-to-have 项权重（分级决定权重，LLM 权重不直接采用，避免主观数值破坏分级契约）；
    - 打折：**部分具备（PARTIAL）蕴含的 inferred 技能**（provenance=inferred 且
      inferred_kind=部分具备）同档内权重打 5 折——推断技能不与字面技能一视同仁；
      FULL 蕴含 inferred（fastapi→python 等，inferred_kind=已具备）维持「已具备」不降权；
    - 跨档不反转：打折仅在同档内生效，任何 core 权重仍 > 任何 nice-to-have 权重（碰撞防御
      维持 硬约束）；
    - 全部同档时档内均分（等价原平均，无分级差异时保持稳定）。
    """
    items = [dict(g) for g in gap_items or []]
    if not items:
        return items
    cores = [g for g in items if str(g.get("required_level") or "core") != "nice-to-have"]
    nices = [g for g in items if str(g.get("required_level") or "core") == "nice-to-have"]
    core_ids = {id(g) for g in cores}

    def _is_partial_inferred(g: dict) -> bool:
        """：PARTIAL 蕴含的 inferred 技能（打折对象；FULL 蕴含 inferred 不降权）。"""
        return (
            g.get("provenance") == "inferred"
            and g.get("inferred_kind") == IMPLICATION_LEVEL_PARTIAL
        )

    weight: dict[int, float] = {}
    for g in items:
        w = 2.0 if id(g) in core_ids else 1.0
        if _is_partial_inferred(g):
            w *= 0.5 # 同档内打折（推断技能权重 < 字面技能）
        weight[id(g)] = w
    total = sum(weight.values()) or 1.0
    for g in items:
        g["weight"] = round(weight[id(g)] / total, 2)
    # round 到 2 位后的极端碰撞防御（项数极多时 core/nice 边界值可能相等；硬约束）
    if cores and nices:
        min_core = min(g["weight"] for g in cores)
        max_nice = max(g["weight"] for g in nices)
        if min_core <= max_nice:
            worst = next(g for g in nices if g["weight"] == max_nice)
            worst["weight"] = round(min_core - 0.01, 2) if min_core > 0.01 else 0.0
    return items


async def executor_node(state: GraphState, deps: AgentDeps) -> dict:
    """：差距分析与成长计划仅 LLM 生成（去掉规则兜底，确保用户走 LLM 路径）。

    - LLM 输出不完整（gap_items / plan.tasks 为空）→ 重试 1 次（共 2 次）；
    - 重试仍不完整 / LLM 不可用 / LLM 调用失败 → executor 节点失败：plan=None +
      stage_errors 记录「LLM 生成成长计划失败」（planner 组装「报告成功但计划缺失」，
      前端显示成长计划生成失败，而非整单失败；不产出「学基础语法」死模板）；
    - LLM 成功路径：差距分级（required_level 权威注入）+ 技能蕴含推理 + 分级权重
      （core > nice-to-have）确定性后处理，不依赖 LLM 自觉。
    """
    profile = state.get("profile") or {}
    target_job = state.get("target_job") or "目标岗位"
    requirements = state.get("target_job_requirements") or []
    jd_summary = state.get("target_job_jd_summary") or {}
    errors = list(state.get("stage_errors") or [])

    result = None
    last_gap_items: list[dict] = []
    failure_reason = ""

    llm_ready = deps.llm is not None and deps.llm.is_available
    if llm_ready:
        injected = (
            get_guard().check_input(json.dumps(profile, ensure_ascii=False), context="executor_profile").blocked
            or get_guard().check_input(target_job, context="executor_target_job").blocked
        )
        if injected:
            failure_reason = "输入包含不安全内容，已拒绝 LLM 解析"
        else:
            for attempt in range(1, _LLM_ATTEMPTS + 1):
                try:
                    prompt = render_prompt("executor.md",
                        profile=json.dumps(profile, ensure_ascii=False),
                        target_job=target_job,
                        job_requirements=json.dumps(requirements, ensure_ascii=False),
                    )
                    user_prompt = "请基于画像与岗位要求输出差距清单与成长计划 JSON。"
                    if jd_summary:
                        user_prompt += (
                            "\nJD 要求摘要（学历/薪资/趋势/技能，来自市场 Agent，可引用到 jd_source）："
                            + json.dumps(jd_summary, ensure_ascii=False)
                        )
                    data = await deps.llm.complete_json(
                        system_prompt=prompt,
                        user_prompt=user_prompt,
                        node_name="executor_node",
                    )
                    gap_items = _inject_gap_data_grade(data.get("gap_items") or [], jd_summary)
                    gap_items = _inject_gap_required_level(gap_items, requirements)
                    # skills_sources（literal/inferred）随画像透传，蕴含推理只从
                    # literal 技能触发，PARTIAL inferred 在权重阶段打折
                    gap_items = _apply_skill_implications(
                        gap_items, profile.get("skills") or [], profile.get("skills_sources")
                    )
                    gap_items = _apply_required_level_weights(gap_items)
                    if gap_items:
                        last_gap_items = gap_items
                    plan = data.get("plan") or {}
                    if gap_items and plan.get("tasks"):
                        result = {"gap_items": gap_items, "plan": plan}
                        break
                    failure_reason = "LLM 输出不完整（gap_items 或 plan.tasks 为空）"
                    logger.warning(
                        "executor: 第 %d/%d 次 LLM 输出不完整，重试: %s",
                        attempt, _LLM_ATTEMPTS, failure_reason,
                    )
                except LLMError as exc:
                    failure_reason = f"LLM 调用失败: {exc}"
                    logger.warning(
                        "executor: 第 %d/%d 次 LLM 调用失败: %s", attempt, _LLM_ATTEMPTS, exc,
                    )
    else:
        failure_reason = "LLM 不可用（未配置 API Key 或服务不可用）"

    if result is None:
        errors.append(
            f"LLM 生成成长计划失败（{failure_reason}）" if failure_reason else "LLM 生成成长计划失败"
        )
        return {
            "gap_items": last_gap_items,
            "plan": None,
            "confidence": {"executor": "低"},
            "stage_errors": errors,
        }

    return {
        "gap_items": result["gap_items"],
        "plan": _normalize_plan_tasks(result["plan"], result["gap_items"], target_job, jd_summary),
        "confidence": {"executor": "中"},
        "stage_errors": errors,
    }
