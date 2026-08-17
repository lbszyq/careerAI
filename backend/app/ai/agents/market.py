"""market_research_node（市场 Agent，）：RAG 检索 + 方向候选（薪资/趋势/热度）或岗位要求。

- Stage 1：输出 3-5 方向候选（含来源标注）。
- Stage 2：target_job 非空 → 输出该岗位 1 条 + required_skills（执行 Agent 的 JD 要求来源）；
  - JD 技能分级输出——required_skills 每项带 required_level（core 必备 / nice-to-have 加分），
  权威分级供 executor 差距权重计算（core 权重 > nice-to-have）。
- 反幻觉：薪资/趋势/热度只来自 RAG；无数据标注「该领域暂时数据较少」。
"""
import json
import logging
import statistics
from collections import Counter

from sqlalchemy import text

from app.ai.agents.deps import AgentDeps
from app.ai.fallback.market_templates import directions_from_hits, directions_from_template
from app.ai.fallback.report_assembler import _dedupe_directions
from app.ai.guard.guards import get_guard
from app.ai.llm.exceptions import LLMError
from app.ai.norm.benchmarks import DEFAULT_MAJOR_CATEGORY, map_major_category, map_major_to_category
from app.ai.prompts import render_prompt
from app.ai.rag.retriever import (
    MarketHit,
    build_market_context,
    data_grade_name,
    search_market,
)
from app.db.base import AsyncSessionLocal
from app.ai.schemas import GraphState

logger = logging.getLogger("careerai.ai.agents.market")

# hits 去重后上限：≈ Stage1 岗位名 query 数(6) × Top-K(10)，避免兜底方向过多
_MAX_HITS = 60


async def market_research_node(state: GraphState, deps: AgentDeps) -> dict:
    profile = state.get("profile") or {}
    target_job = state.get("target_job")
    cities = state.get("preferred_cities") or []
    industries = state.get("preferred_industries") or []
    expected_salary = state.get("expected_salary") # 期望薪资（元/月，可空）

    hits: list[MarketHit] = []
    context = ""
    if deps.embedding is not None and deps.embedding.is_available():
        try:
            # 修复：LangGraph 并行节点（career_analysis ∥ market）共享同一
            # AsyncSession 会并发冲突（InvalidRequestError）导致 RAG 恒降级；
            # 检索为只读操作，改用独立会话消除竞争（架构 并行拓扑不变）。
            # 会话工厂默认为 AsyncSessionLocal（生产），测试可注入目标库工厂。
            rag_factory = deps.rag_session_factory or AsyncSessionLocal
            async with rag_factory() as rag_session:
                queries = await _build_queries(profile, cities, industries, target_job, rag_session)
                context = await build_market_context(rag_session, queries, provider=deps.embedding)
                # 遍历全部 queries（非仅前 2），使 hits 覆盖所有候选岗位名，
                # LLM 生成的每个方向都能匹配到命中记录注入 data_grade
                for query in queries:
                    hits.extend(await search_market(rag_session, query, provider=deps.embedding))
            seen: set[str] = set()
            hits = [h for h in hits if not (h.id in seen or seen.add(h.id))]
            hits = hits[:_MAX_HITS] # 去重后上限，避免兜底方向过多
        except Exception as exc: # noqa: BLE001 RAG 失败不阻断整图
            logger.warning("market: RAG 检索失败降级: %s", type(exc).__name__)

    injected = False
    if deps.llm is not None and deps.llm.is_available:
        injected = (
            get_guard().check_input(_profile_summary(profile), context="market_profile").blocked
            or (bool(target_job) and get_guard().check_input(target_job, context="market_target_job").blocked)
        )
        if injected:
            logger.warning("market: 间接注入字段被 Guard 拦截（profile/target_job），跳过 LLM 走规则兜底")

    if target_job:
        return await _stage2_requirements(
            state, profile, target_job, hits, context, deps, injected=injected,
            expected_salary=expected_salary,
        )
    return await _stage1_directions(
        state, profile, cities, industries, hits, context, deps, injected=injected,
        expected_salary=expected_salary,
    )


async def _stage1_directions(state, profile, cities, industries, hits, context, deps, injected: bool = False, expected_salary: float | None = None) -> dict:
    directions = None
    if deps.llm is not None and deps.llm.is_available and not injected:
        try:
            prompt = render_prompt("market.md", 
                profile_summary=_profile_summary(profile),
                preferred_cities="、".join(cities) or "未指定",
                preferred_industries="、".join(industries) or "未指定",
                rag_context=context or "（RAG 无结果）",
                target_job="",
            )
            data = await deps.llm.complete_json(
                system_prompt=prompt,
                user_prompt="请输出方向推荐 JSON。",
                node_name="market_research_node",
            )
            directions = list(data.get("directions") or [])
        except LLMError as exc:
            logger.warning("market: LLM 失败转规则兜底: %s", exc)

    if not directions:
        directions = directions_from_hits(hits, profile) if hits else directions_from_template(profile)
        errors = list(state.get("stage_errors") or [])
        if injected:
            errors.append("输入包含不安全内容，已拒绝 LLM 解析")
        elif not hits:
            errors.append("市场方向使用模板兜底（RAG 无数据或不可用）")
        return {
            "market_results": _apply_recommendation_constraints(directions, profile, hits=hits, expected_salary=expected_salary),
            "confidence": {"market": "低"},
            "stage_errors": errors,
        }

    return {
        "market_results": _apply_recommendation_constraints(directions, profile, hits=hits, expected_salary=expected_salary),
        "confidence": {"market": "中" if context else "低"},
        "stage_errors": state.get("stage_errors") or [],
    }


async def _stage2_requirements(state, profile, target_job, hits, context, deps, injected: bool = False, expected_salary: float | None = None) -> dict:
    required_skills: list[dict] | None = None
    direction: dict | None = None
    if deps.llm is not None and deps.llm.is_available and not injected:
        try:
            prompt = render_prompt("market.md", 
                profile_summary=_profile_summary(profile),
                preferred_cities="、".join(state.get("preferred_cities") or []) or "未指定",
                preferred_industries="、".join(state.get("preferred_industries") or []) or "未指定",
                rag_context=context or "（RAG 无结果）",
                target_job=target_job,
            )
            data = await deps.llm.complete_json(
                system_prompt=prompt,
                user_prompt=f"目标岗位：{target_job}\n请输出该岗位要求 JSON。",
                node_name="market_research_node",
            )
            dirs = list(data.get("directions") or [])
            direction = dirs[0] if dirs else None
            # JD 技能分级归一（{"name", "required_level"}；字符串兼容视为 core）
            required_skills = _normalize_required_skills(data.get("required_skills"))
        except LLMError as exc:
            logger.warning("market: Stage2 LLM 失败转规则: %s", exc)

    if required_skills is None:
        # RAG 命中技能无分级依据 → 统一 core（不臆造加分项；分级缺失不降权）
        required_skills = _normalize_required_skills(_skills_from_hits(hits, target_job))
        if direction is not None:
            direction = _inject_direction_data_grade(direction, hits)
        jd_summary = _jd_summary_from_hits(hits, target_job)
        errors = list(state.get("stage_errors") or [])
        if injected:
            errors.append("输入包含不安全内容，已拒绝 LLM 解析")
        elif not hits:
            errors.append("目标岗位要求使用通用兜底（RAG 无数据）")
        return {
            "market_results": _apply_recommendation_constraints([direction] if direction else [], profile, hits=hits, expected_salary=expected_salary),
            "target_job_requirements": required_skills,
            "target_job_jd_summary": jd_summary,
            "confidence": {"market": "低"},
            "stage_errors": errors,
        }

    if direction is not None:
        direction = _inject_direction_data_grade(direction, hits)
    jd_summary = _jd_summary_from_direction(direction, target_job, required_skills, hits)
    return {
        "market_results": _apply_recommendation_constraints([direction] if direction else [], profile, hits=hits, expected_salary=expected_salary),
        "target_job_requirements": required_skills,
        "target_job_jd_summary": jd_summary,
        "confidence": {"market": "中" if context else "低"},
        "stage_errors": state.get("stage_errors") or [],
    }


async def _build_queries(
    profile: dict,
    cities: list[str],
    industries: list[str],
    target_job: str | None,
    session,
) -> list[str]:
    """构造检索查询（market 节点检索查询）。

    ：Stage1（无 target_job）改为「完整岗位名 + 岗位要求 技能」维度——从数据库 distinct
    job_title 按专业大类筛选（对齐库内完整岗位名，而非 _MAJOR_MAP 反查关键词），每个岗位名单独
    一条 query，并加「岗位要求 技能」后缀对齐入库文本形态（bge-m3 对完整岗位名+后缀相似度 >0.7，
    而关键词拼长 query 语义被稀释、泛词恒命中 0）；Stage2（有 target_job）保留原 query 不变。
    """
    queries: list[str] = []
    job = target_job or ""
    if job:
        # Stage2：保留现有 query 不变
        queries.append(f"{job} 岗位要求 技能")
        skills = (profile.get("skills") or [])[:5]
        if skills:
            queries.append(f"{job} {' '.join(skills)} 岗位 薪资 技能要求")
        if industries:
            queries.append(f"{' '.join(industries)} 行业 {' '.join(skills[:3]) if skills else ''} 岗位 薪资")
        if cities:
            queries.append(f"{' '.join(cities[:3])} 应届生 岗位 薪资 趋势")
        return [q for q in queries if q.strip()] or [f"{job} 岗位要求 技能"]

    # Stage1（无 target_job）：完整岗位名 + 后缀（每个岗位名一条 query）
    job_titles = await _job_titles_for_major(session, profile)
    if job_titles:
        queries = [f"{title} 岗位要求 技能" for title in job_titles]
    else:
        # 反查不到岗位名（专业缺失/映射不到大类/表未就绪）：退回原泛词 query 兜底
        skills = (profile.get("skills") or [])[:5]
        if skills:
            queries.append(f"{' '.join(skills)} 岗位 薪资")
        if industries:
            queries.append(f"{' '.join(industries)} 行业 {' '.join(skills[:3]) if skills else ''} 岗位 薪资")
        if cities:
            queries.append(f"{' '.join(cities[:3])} 应届生 岗位 薪资 趋势")
    return [q for q in queries if q.strip()] or ["应届毕业生 热门岗位 薪资 趋势"]


async def _job_titles_for_major(session, profile: dict, *, limit: int = 6) -> list[str]:
    """Stage1 岗位名 query 源（补修）：数据库 distinct job_title 按专业大类筛选。

    对齐库内「完整岗位名」（官方统计口径 + 招聘 JD 口径，如「后端开发工程师」「软件测试工程师」），
    而非 _MAJOR_MAP 反查关键词——关键词拼长 query 语义被稀释、且泛词与库内完整岗位名口径不同。
    """
    major = str(profile.get("major") or "").strip()
    if not major:
        return []
    category = map_major_to_category(major)
    if category == DEFAULT_MAJOR_CATEGORY:
        return []
    try:
        rows = await session.execute(
            text("SELECT DISTINCT job_title FROM market_data WHERE embedding IS NOT NULL")
        )
    except Exception: # noqa: BLE001 表/列未就绪降级
        logger.warning("market: 查询 distinct job_title 失败降级")
        return []
    titles = [str(r[0]) for r in rows if map_major_category(str(r[0])) == category]
    return sorted(titles)[:limit]


_REQUIRED_LEVELS = ("core", "nice-to-have")


def _normalize_required_skills(raw: list | None) -> list[dict]:
    """：JD 技能分级归一——required_skills 项 → {"name", "required_level"}。

    - LLM 输出 dict（{"name"/"skill", "required_level"}）或字符串（无分级 → core）均兼容；
    - 非法/缺失 required_level → core（安全默认，避免加分技能被降权）；按 name 小写去重保序。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("skill") or "").strip()
            level = str(item.get("required_level") or "").strip().lower()
        else:
            name = str(item or "").strip()
            level = "core"
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "required_level": level if level in _REQUIRED_LEVELS else "core"})
    return out


def _skills_from_hits(hits: list[MarketHit], target_job: str) -> list[str]:
    skills: list[str] = []
    for hit in hits:
        if target_job and target_job not in hit.job_title and target_job not in (hit.job_title or ""):
            continue
        for skill in hit.required_skills or []:
            if skill not in skills:
                skills.append(skill)
        if len(skills) >= 8:
            break
    if not skills:
        return [f"{target_job}核心技能（未检索到岗位要求，按通用要求兜底）"]
    return skills


_AGGREGATE_SKILLS_LIMIT = 8


def _jd_pool_for(hits: list[MarketHit], target_job: str) -> list[MarketHit]:
    """目标岗位命中池（与现状一致）：job_title 含 target_job 的命中优先，否则全部命中。"""
    matched = [h for h in hits if target_job and target_job in (h.job_title or "")]
    return matched or hits


def _split_by_source(pool: list[MarketHit]) -> tuple[list[MarketHit], list[MarketHit], list[MarketHit]]:
    """按 source_type 分流：official_stat / job_post / 其它（ai_infer、None 等）。"""
    official = [h for h in pool if h.source_type == "official_stat"]
    posts = [h for h in pool if h.source_type == "job_post"]
    others = [h for h in pool if h.source_type not in ("official_stat", "job_post")]
    return official, posts, others


def _best_official(official: list[MarketHit], target_job: str) -> MarketHit | None:
    """多条 official_stat 时：job_title 精确匹配 target_job 优先，否则相似度最高（official[0]）。"""
    if not official:
        return None
    exact = [h for h in official if (h.job_title or "").strip() == (target_job or "").strip()]
    return exact[0] if exact else official[0]


def _salary_from_hit(hit: MarketHit) -> dict | None:
    """单条命中薪资分位（任一非空才输出 dict，否则 None）。"""
    if any(v is not None for v in (hit.salary_p25, hit.salary_p50, hit.salary_p75)):
        return {"p25": hit.salary_p25, "p50": hit.salary_p50, "p75": hit.salary_p75}
    return None


def _aggregate_salary(posts: list[MarketHit]) -> dict | None:
    """多套 job_post 薪资合并（写死）：p25=min、p75=max、p50=中位数（过滤 None）。"""
    p25s = [h.salary_p25 for h in posts if h.salary_p25 is not None]
    p50s = [h.salary_p50 for h in posts if h.salary_p50 is not None]
    p75s = [h.salary_p75 for h in posts if h.salary_p75 is not None]
    if not p25s and not p50s and not p75s:
        return None
    return {
        "p25": min(p25s) if p25s else None,
        "p50": statistics.median(p50s) if p50s else None,
        "p75": max(p75s) if p75s else None,
    }


def _aggregate_skills(posts: list[MarketHit], limit: int = _AGGREGATE_SKILLS_LIMIT) -> list[dict]:
    """多套 job_post 技能频次聚合：频次降序 + 同频次名字字典序；项结构 {"name","required_level","count"}。

    - 保留 name 键（grounding._entry_text 只认 name/skill）；无分级依据 → core；
    - count 为出现频次（额外字段，不影响 grounding）；按名字小写去重（对齐 _normalize_required_skills）。
    """
    count: dict[str, int] = {}
    canonical: dict[str, str] = {}
    for hit in posts:
        for raw in hit.required_skills or []:
            name = str(raw or "").strip()
            if not name:
                continue
            key = name.lower()
            if key not in canonical:
                canonical[key] = name
                count[key] = 0
            count[key] += 1
    ordered = sorted(canonical, key=lambda k: (-count[k], canonical[k].lower()))
    return [
        {"name": canonical[k], "required_level": "core", "count": count[k]}
        for k in ordered[:limit]
    ]


def _mode_education(posts: list[MarketHit]) -> str | None:
    """多套 job_post 学历众数；平局取相似度最高命中（posts 已按相似度降序，首现即最高）。"""
    values = [
        str(h.education_requirement).strip()
        for h in posts
        if str(h.education_requirement or "").strip()
    ]
    if not values:
        return None
    counts = Counter(values)
    max_count = max(counts.values())
    tied = [v for v in values if counts[v] == max_count]
    return tied[0]


def _union_responsibilities(posts: list[MarketHit]) -> list[str]:
    """多套 job_post 职责并集去重（保持相似度序，字符串数组）。"""
    out: list[str] = []
    seen: set[str] = set()
    for hit in posts:
        for raw in hit.responsibilities or []:
            item = str(raw or "").strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _aggregate_summary_note(posts_count: int, official_count: int) -> str:
    """聚合溯源说明（中性文案，不含技能文本，避免污染 grounding 依据池映射）。"""
    if official_count and not posts_count:
        return "摘要来自官方统计分位（该来源无技能/学历/职责明细，不编造）"
    if posts_count > 1:
        return (
            f"聚合 {posts_count} 套公开招聘 JD"
            "（薪资区间合并、技能按频次、学历取众数、职责并集），来源可溯源"
        )
    return "摘要来自 RAG 命中结构化字段（含学历/职责，缺失时不编造）"


def _aggregate_jd_summary(pool: list[MarketHit], target_job: str) -> dict:
    """按 source_type 分流聚合 JD 摘要：official_stat 单条分位、job_post 多套聚合。

    - 薪资：official 命中 → 最优 official 单条分位；仅 job_post → p25=min/p75=max/p50=中位数；
    - 技能/学历/职责：仅来自 job_post 聚合（official_stat 天然无明细）；
    - 代表命中：job_title/city/industry/trend/heat/data_source/data_grade 取薪资权威来源命中；
    - data_grade 为薪资权威等级；skills_data_grade 为技能溯源等级（job_post=B）。
    """
    official, posts, _ = _split_by_source(pool)
    if official:
        rep = _best_official(official, target_job)
        salary = _salary_from_hit(rep)
    elif posts:
        rep = posts[0]
        salary = _aggregate_salary(posts)
    else:
        rep = pool[0]
        salary = _salary_from_hit(rep)
    return {
        "job_title": rep.job_title,
        "city": rep.city,
        "industry": rep.industry,
        "education_requirement": _mode_education(posts),
        "responsibilities": _union_responsibilities(posts),
        "salary": salary,
        "trend": rep.trend,
        "heat": rep.heat,
        "required_skills": _aggregate_skills(posts),
        "data_source": rep.salary_note,
        "data_grade": rep.data_grade,
        "skills_data_grade": posts[0].data_grade if posts else None,
        "summary_note": _aggregate_summary_note(len(posts), len(official)),
    }


def _jd_summary_from_hits(hits: list[MarketHit], target_job: str) -> dict:
    """从 RAG 命中提取 JD 要求摘要（执行 Agent 输入，/ /）。

    ：按 source_type 分流聚合——official_stat 取单条分位（本身即统计分位），
    job_post 聚合多套 JD（薪资区间合并、技能频次、学历众数、职责并集），使差距分析看到
    「岗位主流要求」而非「某一家公司」。聚合结果可溯源（仅来自命中真实 JD，无合成）。
    """
    pool = _jd_pool_for(hits, target_job)
    if not pool:
        return {
            "job_title": target_job,
            "city": None,
            "industry": None,
            "education_requirement": None,
            "responsibilities": [],
            "salary": None,
            "trend": None,
            "heat": None,
            "required_skills": [],
            "data_source": None,
            "data_grade": None,
            "skills_data_grade": None,
            "summary_note": "未检索到该岗位市场数据，JD 要求摘要缺失",
        }
    return _aggregate_jd_summary(pool, target_job)


def _jd_summary_from_direction(
    direction: dict | None,
    target_job: str,
    required_skills: list[dict],
    hits: list[MarketHit] | None = None,
) -> dict:
    """Stage2 LLM 成功路径：JD 摘要以市场 Agent 输出为准，学历/职责以命中记录聚合补充。

    - 学历：LLM 输出优先；缺失时回落到 job_post 命中聚合众数（平局取相似度最高）；
    - 职责：LLM 不产职责，取 job_post 命中职责并集（无命中 → []），禁止编造；
    - 薪资/技能/趋势/热度仍以 LLM 输出为准（LLM 已基于全量 RAG 上下文综合）。
    """
    if not direction:
        return _jd_summary_from_hits(hits or [], target_job)
    _, posts, _ = _split_by_source(_jd_pool_for(hits or [], target_job))
    education = direction.get("education_requirement") or _mode_education(posts)
    responsibilities = _union_responsibilities(posts)
    salary = direction.get("salary")
    return {
        "job_title": direction.get("job_title") or target_job,
        "city": None,
        "industry": None,
        "education_requirement": education,
        "responsibilities": responsibilities,
        "salary": salary if isinstance(salary, dict) else None,
        "trend": direction.get("trend"),
        "heat": direction.get("heat"),
        "required_skills": (required_skills or [])[:8],
        "data_source": direction.get("data_source"),
        "data_grade": direction.get("data_grade"),
        "summary_note": "摘要来自市场 Agent Stage2 输出；学历/职责以命中记录补充，缺失时不编造",
    }


def _fallback_recommend_reason(direction: dict, profile: dict) -> str:
    """recommend_reason 兜底（LLM/模板漏字段时补齐）：基于画像专业/技能，禁止编造市场数据。"""
    major = profile.get("major") or ""
    skills = profile.get("skills") or []
    if major:
        return f"与你的「{major}」专业方向匹配，建议结合岗位要求进一步了解"
    if skills:
        return f"与你的技能画像（{skills[0]} 等）匹配度较高，建议结合岗位要求进一步了解"
    return "与你的画像匹配度较高，建议结合岗位要求进一步了解"


_EDUCATION_MATCH_VALUES = {"匹配", "不匹配", "未知"}

_COMPETITION_UNKNOWN_NOTE = (
    "暂无量化竞争数据（数据缺失），建议结合招聘平台实时岗位数与自身准备情况综合判断"
)

# ---------------------------------------------------------------------------
# 期望薪资 vs 岗位薪资分位对比（确定性计算，反幻觉底线）。
# 数字/level 全部由 code 层判定，note 为 code 模板，LLM 不得参与生成。
# ---------------------------------------------------------------------------
_SALARY_COMPARISON_NO_DATA_NOTE = "暂无该岗位薪资数据"


def _to_salary_number(value) -> float | None:
    """薪资分位数值容错：None/非数值 → None（分位缺失不编造）。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _expected_salary_number(value) -> float | None:
    """期望薪资数值容错：缺失/≤0/非数值 → None（前端隐藏，修订）。"""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _fmt_salary(value: float | None) -> str:
    """薪资展示格式化（单位元/月）：整千元 →「Nk」，非整千元保留原整数。"""
    if value is None:
        return "—"
    num = float(value)
    if num.is_integer():
        iv = int(num)
        if iv % 1000 == 0 and iv != 0:
            return f"{iv // 1000}k"
        return str(iv)
    return f"{num:g}"


def _salary_level(exp: float, p25: float | None, p50: float | None, p75: float | None) -> str:
    """半开区间 level 判定（等号归属冻结，P0）。

    从上界往下判定：
    - expected ≥ p75 → above_p75
    - expected < p25 → below_p25
    - expected < p50 → p25_p50（此时 expected ≥ p25 或 p25 缺失）
    - expected < p75 → p50_p75（此时 expected ≥ p50 或 p50 缺失）
    - 上界缺失（p75=None 且 expected ≥ p50）→ above_p75（无上界，保守按高位）
    """
    if p75 is not None and exp >= p75:
        return "above_p75"
    if p25 is not None and exp < p25:
        return "below_p25"
    if p50 is not None and exp < p50:
        return "p25_p50"
    if p75 is not None and exp < p75:
        return "p50_p75"
    return "above_p75"


def _salary_comparison_note(
    exp: float, p25: float | None, p50: float | None, p75: float | None, level: str
) -> str:
    """薪资对比 note（code 模板，数字确定性，LLM 不得改写）。"""
    e = _fmt_salary(exp)
    if level == "below_p25":
        return f"你的期望薪资 {e}/月 低于该岗位薪资区间 25 分位（{_fmt_salary(p25)}/月）。"
    if level == "p25_p50":
        return f"你的期望薪资 {e}/月 处于该岗位薪资区间 25-50 分位段（{_fmt_salary(p25)}-{_fmt_salary(p50)}/月）。"
    if level == "p50_p75":
        return f"你的期望薪资 {e}/月 处于该岗位薪资区间 50-75 分位段（{_fmt_salary(p50)}-{_fmt_salary(p75)}/月）。"
    return f"你的期望薪资 {e}/月 达到该岗位薪资区间 75 分位（{_fmt_salary(p75)}/月）及以上。"


def _build_salary_comparison(expected_salary: float | None, salary: dict | None) -> dict | None:
    """期望薪资 vs 岗位薪资分位对比（确定性计算）。

    - expected_salary 缺失/≤0/非数值 → None（前端隐藏，修订）。
    - salary 分位（p25/p50/p75）全部缺失 → no_data（结构冻结）。
    - level 半开区间：below_p25（expected<p25）／p25_p50（[p25,p50)）／
      p50_p75（[p50,p75)，expected==p50 落此段）／above_p75（≥p75）。
    """
    exp = _expected_salary_number(expected_salary)
    if exp is None:
        return None

    s = salary if isinstance(salary, dict) else {}
    p25 = _to_salary_number(s.get("p25"))
    p50 = _to_salary_number(s.get("p50"))
    p75 = _to_salary_number(s.get("p75"))

    if p25 is None and p50 is None and p75 is None:
        return {
            "expected_salary": exp,
            "p25": None,
            "p50": None,
            "p75": None,
            "level": "no_data",
            "note": _SALARY_COMPARISON_NO_DATA_NOTE,
        }

    level = _salary_level(exp, p25, p50, p75)
    return {
        "expected_salary": exp,
        "p25": p25,
        "p50": p50,
        "p75": p75,
        "level": level,
        "note": _salary_comparison_note(exp, p25, p50, p75, level),
    }


def _apply_recommendation_constraints(
    directions: list[dict], profile: dict, hits: list[MarketHit] | None = None, expected_salary: float | None = None
) -> list[dict]:
    """Q4 推荐约束：补齐学历/竞争/证书字段；学历明显不匹配的候选在数量允许时剔除。

    - 兜底默认值：LLM/模板漏字段时补齐，保证方向结构稳定（契约字段为 JSONB，可扩展）。
    - 学历过滤：education_match="不匹配" 的候选在剩余候选 ≥3 时剔除（契约 3-5 条下限），
      避免给用户推荐学历门槛明显不符的岗位；不足 3 条时保留并保持"不匹配"标注。
    - v1.1：data_grade 由 RAG 命中的 source_type 派生（无命中 → None，Agent 不自判）；
      confidence_reasons 基于方向已有数据点（match_score/data_grade/季度）确定性组装，禁止编造。
    - v1.3：salary_comparison 由确定性纯函数计算（level 半开区间 + code note 模板），
      期望薪资缺失/≤0 → null；有期望无分位 → no_data。
    """
    out: list[dict] = []
    for d in directions or []:
        if not isinstance(d, dict):
            continue
        d = dict(d)
        d.setdefault("education_requirement", None)
        if d.get("education_match") not in _EDUCATION_MATCH_VALUES:
            d["education_match"] = "未知"
        d.setdefault("competition_note", _COMPETITION_UNKNOWN_NOTE)
        d.setdefault("certificates_bonus", None)
        d.setdefault("recommend_reason", _fallback_recommend_reason(d, profile))
        d = _inject_direction_data_grade(d, hits)
        # 薪资对比确定性计算（数字来自 direction.salary，LLM 不得改写），并入方向 dict
        d["salary_comparison"] = _build_salary_comparison(expected_salary, d.get("salary"))
        out.append(d)

    # QA-BUG-004：同岗位不同来源按 job_title 去重（保留 match_score 最高/来源最优者），
    # 避免「数据分析师 match 85/80」重复展示；去重后再做学历过滤与数量截断。
    out = _dedupe_directions(out)
    kept = [d for d in out if d.get("education_match") != "不匹配"]
    if kept and len(kept) >= 3:
        return kept[:5]
    return out[:5]


def _match_hit(direction: dict, hits: list[MarketHit]) -> MarketHit | None:
    """按岗位名匹配 RAG 命中（job_title 双向包含，方向与命中一致时命中）。"""
    job_title = str(direction.get("job_title") or "")
    if not job_title:
        return None
    for hit in hits or []:
        if job_title in (hit.job_title or "") or (hit.job_title or "") in job_title:
            return hit
    return None


def _inject_direction_data_grade(direction: dict, hits: list[MarketHit] | None) -> dict:
    """v1.1：方向注入 data_grade + confidence_reasons（确定性组装，禁止 Agent 自判/编造）。

    - data_grade：命中记录的 source_type 映射派生（A/B/C）；无命中/无 source_type → None。
    - confidence_reasons：仅引用 direction 与命中记录已有数据点（匹配分/等级/季度/薪资说明）。
    """
    d = dict(direction)
    hit = _match_hit(d, hits or [])
    grade = hit.data_grade if hit is not None else None
    d["data_grade"] = grade

    supporting: list[str] = []
    concerns: list[str] = []
    if grade:
        supporting.append(f"市场数据来源为{data_grade_name(grade)}（{grade} 级）")
    else:
        supporting.append("市场数据来源已标注（基于公开数据）")
    match_score = d.get("match_score")
    if isinstance(match_score, (int, float)):
        supporting.append(f"方向匹配度 {int(match_score)}，与画像技能/专业方向重合度高")
    salary_note = str(d.get("salary_note") or "")
    if salary_note and "数据较少" not in salary_note and "暂无" not in salary_note:
        concerns.append("薪资为市场近似值，可能含在职样本或口径差异")
    if hit is not None and hit.data_quarter:
        concerns.append(f"数据季度为 {hit.data_quarter}，存在时效偏差")
    if grade is None:
        concerns.append("市场数据不足，匹配判断基于画像与通用知识")
    d["confidence_reasons"] = {"supporting": supporting, "concerns": concerns}
    return d


def _profile_summary(profile: dict) -> str:
    return json.dumps(
        {
            "major": profile.get("major"),
            "education": profile.get("education"),
            "graduation_year": profile.get("graduation_year"),
            "skills": (profile.get("skills") or [])[:8],
            "internships": (profile.get("internships") or [])[:2],
            "projects": (profile.get("projects") or [])[:2],
        },
        ensure_ascii=False,
    )
