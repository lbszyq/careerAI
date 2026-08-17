"""市场方向规则兜底：RAG 无结果 / LLM 不可用时输出方向候选。

- 有 RAG 命中：按画像技能与岗位技能重叠度排序取 Top 3-5，薪资/趋势/热度取自命中记录。
- RAG 无结果：通用行业模板（按专业大类映射），薪资标注「该领域暂时数据较少」。
"""
from app.ai.rag.retriever import MarketHit

# 专业大类 → 通用方向模板（无市场数据时的兜底，仅作骨架，禁止编造薪资）
_TEMPLATES: dict[str, list[dict]] = {
    "计算机类": [
        {"job_title": "后端开发工程师", "match_score": 70},
        {"job_title": "数据分析师", "match_score": 72},
        {"job_title": "前端开发工程师", "match_score": 65},
        {"job_title": "测试开发工程师", "match_score": 62},
        {"job_title": "运维工程师", "match_score": 60},
    ],
    "经济金融类": [
        {"job_title": "财务分析师", "match_score": 70},
        {"job_title": "风险管理专员", "match_score": 66},
        {"job_title": "银行对公客户经理", "match_score": 62},
        {"job_title": "证券分析师", "match_score": 64},
    ],
    "工商管理类": [
        {"job_title": "产品经理", "match_score": 70},
        {"job_title": "市场营销专员", "match_score": 66},
        {"job_title": "运营专员", "match_score": 64},
        {"job_title": "人力资源专员", "match_score": 60},
    ],
    "教育类": [
        {"job_title": "中小学教师", "match_score": 70},
        {"job_title": "在线教育教研", "match_score": 64},
    ],
    "机械类": [
        {"job_title": "机械设计工程师", "match_score": 70},
        {"job_title": "工艺工程师", "match_score": 62},
    ],
    "电气类": [
        {"job_title": "电气工程师", "match_score": 70},
        {"job_title": "嵌入式软件工程师", "match_score": 64},
    ],
    "土木类": [
        {"job_title": "结构工程师", "match_score": 70},
        {"job_title": "工程造价", "match_score": 62},
    ],
    "医学类": [
        {"job_title": "临床医师", "match_score": 70},
        {"job_title": "医药代表", "match_score": 60},
    ],
    "法学类": [
        {"job_title": "法务专员", "match_score": 70},
        {"job_title": "律师助理", "match_score": 62},
    ],
    "艺术设计类": [
        {"job_title": "UI/UX 设计师", "match_score": 70},
        {"job_title": "视觉设计师", "match_score": 64},
    ],
    "新闻传播类": [
        {"job_title": "新媒体运营", "match_score": 70},
        {"job_title": "内容策划", "match_score": 62},
    ],
}

_NO_DATA_SOURCE = "暂无市场数据（模板兜底）"
_NO_DATA_NOTE = "该领域暂时数据较少"


def directions_from_hits(
    hits: list[MarketHit], profile: dict, *, limit: int = 5
) -> list[dict]:
    """从 RAG 命中中挑选方向：按技能重叠度排序。"""
    user_skills = {s.lower() for s in (profile.get("skills") or [])}
    major = profile.get("major") or ""
    scored: list[dict] = []
    for hit in hits:
        required = [s.lower() for s in (hit.required_skills or [])]
        overlap = len(user_skills & set(required))
        total = len(required) or 1
        match_score = min(95, 55 + int(overlap / total * 40) + (5 if major and major in hit.industry else 0))
        scored.append(
            {
                "job_title": hit.job_title,
                "match_score": match_score,
                "salary": _salary_dict(hit),
                "salary_note": hit.salary_note,
                "trend": hit.trend or "未知",
                "heat": hit.heat or "中",
                "data_source": hit.data_source or _NO_DATA_SOURCE,
                # Q4：模板无 JD 学历门槛数据 → 置 null/未知，禁止编造；
                # 竞争说明基于已有热度/趋势，缺失时如实标注不确定性
                "education_requirement": None,
                "education_match": "未知",
                "competition_note": _competition_note(hit),
                "certificates_bonus": None,
                # v1.1：来源等级由入库 source_type 派生（Agent 不自判）；无 source_type → None
                "data_grade": hit.data_grade,
            }
        )
    scored.sort(key=lambda d: d["match_score"], reverse=True)
    return scored[:limit]


def directions_from_template(profile: dict, *, limit: int = 5) -> list[dict]:
    """通用行业模板兜底（无 RAG 数据）：薪资全空并标注数据较少。"""
    major = profile.get("major") or ""
    from app.ai.norm.benchmarks import map_major_category

    category = map_major_category(major)
    template = _TEMPLATES.get(category) or _TEMPLATES.get("其他", [])
    if category == "其他":
        template = [
            {"job_title": "管培生", "match_score": 60},
            {"job_title": "行政专员", "match_score": 55},
            {"job_title": "市场专员", "match_score": 58},
        ]
    out = []
    for item in template[:limit]:
        out.append(
            {
                "job_title": item["job_title"],
                "match_score": item["match_score"],
                "salary": None,
                "salary_note": _NO_DATA_NOTE,
                "trend": "未知",
                "heat": "中",
                "data_source": _NO_DATA_SOURCE,
                # Q4：模板兜底无学历门槛/证书数据 → 如实标注，不编造
                "education_requirement": None,
                "education_match": "未知",
                "competition_note": "暂无量化竞争数据（模板兜底），建议结合招聘平台岗位数综合判断",
                "certificates_bonus": None,
                "data_grade": None, # 模板兜底无来源等级（v1.1，禁止编造）
            }
        )
    return out


def _competition_note(hit: MarketHit) -> str:
    """基于 RAG 命中的热度/趋势生成竞争说明；数据缺失时标注不确定性（Q4/，禁止编造）。"""
    parts: list[str] = []
    if hit.heat:
        parts.append(f"热度{hit.heat}")
    if hit.trend:
        parts.append(f"趋势{hit.trend}")
    if parts:
        return f"基于市场数据（{'、'.join(parts)}）；竞争程度需结合招聘平台实时岗位数综合判断"
    return "暂无量化竞争数据（数据较少），建议结合招聘平台岗位数综合判断"


def _salary_dict(hit: MarketHit) -> dict | None:
    if hit.salary_p25 is None and hit.salary_p50 is None and hit.salary_p75 is None:
        return None
    return {
        "p25": hit.salary_p25,
        "p50": hit.salary_p50,
        "p75": hit.salary_p75,
    }
