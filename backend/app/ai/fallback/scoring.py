"""画像评分规则兜底：LLM 不可用时基于画像字段启发式评分。

五维与 reports-contract 对齐：technical / project / academic / soft_skill / industry_knowledge。
分数为启发式估算，confidence 固定「低」，报告中标注由规则模板生成。
"""
from app.ai.norm.benchmarks import NormBenchmark

_DIM_KEYS = ("technical", "project", "academic", "soft_skill", "industry_knowledge")
_WEIGHTS = {
    "technical": 0.25,
    "project": 0.20,
    "academic": 0.20,
    "soft_skill": 0.20,
    "industry_knowledge": 0.15,
}
_DEEP_SKILLS = {"python", "java", "c++", "sql", "机器学习", "深度学习", "pytorch", "tensorflow", "spark"}


def score_profile(profile: dict, norm: NormBenchmark | None = None) -> dict:
    """规则评分（0-100 五维 + 综合 + 常模对比 + 优劣势）。"""
    dims = {dim: _clamp(_raw_dim(profile, dim)) for dim in _DIM_KEYS}
    overall = round(sum(dims[dim] * _WEIGHTS[dim] for dim in _DIM_KEYS))

    skills = profile.get("skills") or []
    internships = profile.get("internships") or []
    projects = profile.get("projects") or []
    certificates = profile.get("certificates") or []
    gpa = profile.get("gpa")

    strengths: list[str] = []
    weaknesses: list[str] = []
    if skills:
        strengths.append(f"掌握技能：{'、'.join(skills[:4])}")
    if projects:
        strengths.append(f"有 {len(projects)} 段项目经历，具备实践基础")
    if internships:
        strengths.append(f"有 {len(internships)} 段实习经历，具备职场适应力")
    if gpa and gpa >= 3.5:
        strengths.append(f"学业表现良好（GPA {gpa}）")
    if not skills:
        weaknesses.append("技能清单缺失，竞争力评估依据不足")
    if not projects:
        weaknesses.append("缺少项目经历，实践能力待补充")
    if not internships:
        weaknesses.append("缺少实习经历")
    if not weaknesses:
        weaknesses.append("建议补充行业认知类证书/课程以提升综合竞争力")

    # （诚实下线同步）：to_dict 样本<30 → None（隐藏语义），
    # 规则兜底路径 scores.norm 自动置 None——无真实常模时不输出降级载荷。
    norm_dict = None
    if norm is not None:
        cohort = f"{norm.graduation_year}届 × {norm.city_tier} × {norm.major_category}"
        norm_dict = norm.to_dict(cohort=cohort)

    return {
        "overall_score": overall,
        "dimensions": dims,
        "norm": norm_dict,
        "strengths": strengths or ["画像信息有限，暂无法提炼优势"],
        "weaknesses": weaknesses,
        "confidence": "低",
        "generated_by": "rule_template",
    }


def _raw_dim(profile: dict, dim: str) -> int:
    skills = profile.get("skills") or []
    internships = profile.get("internships") or []
    projects = profile.get("projects") or []
    certificates = profile.get("certificates") or []
    gpa = profile.get("gpa")
    education = profile.get("education") or ""
    if dim == "technical":
        base = 40 + min(len(skills), 8) * 6
        if _DEEP_SKILLS & set(s.lower() for s in skills):
            base += 12
        return base
    if dim == "project":
        return 35 + min(len(projects), 5) * 12
    if dim == "academic":
        base = 45
        if gpa and gpa >= 3.5:
            base += 15
        elif gpa and gpa >= 3.0:
            base += 8
        if education in ("硕士", "博士"):
            base += 8
        return base
    if dim == "soft_skill":
        return 40 + min(len(internships), 5) * 10
    return 35 + min(len(certificates), 5) * 8


def _clamp(value: int) -> int:
    return max(0, min(100, value))
