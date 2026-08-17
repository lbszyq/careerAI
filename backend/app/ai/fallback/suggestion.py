"""AI 策略建议（suggestion）规则生成器（reports-contract v1.1 /）。

- 仅 Stage 2 完整报告（画像/方向/差距齐备）生成；任一数据缺失 → None。
- 每条 reasons 必须引用报告内已生成数据（方向匹配度/画像评分/差距清单），禁止凭空建议；
  Planner 只总结报告内已有数据，不新增事实（PRD v1.6-final Agent 约束）。
- 规则生成保证确定性：文案全部由已有数据点推导，无 LLM 参与。
- （T）：build_suggestion_from_parts 接受显式数据（gap_items 等），
  供事实接地审计层基于「审计后」差距数据重建建议（不再引用被删的无据差距技能）。
"""
from app.ai.schemas import GraphState


def _top_dim(dimensions: dict) -> tuple[str, int] | None:
    """五维评分最高维度（存在并列取首个）。"""
    if not dimensions:
        return None
    key = max(dimensions, key=lambda k: dimensions[k])
    return key, int(dimensions[key])


def _gap_skills(gap_items: list[dict], limit: int = 3) -> list[str]:
    """差距清单中「不具备/部分具备」的技能（前 limit 项）。"""
    out: list[str] = []
    for g in gap_items or []:
        level = g.get("level")
        skill = str(g.get("skill") or "").strip()
        if skill and level in ("不具备", "部分具备") and skill not in out:
            out.append(skill)
        if len(out) >= limit:
            break
    return out


def build_suggestion_from_parts(
    scores: dict,
    directions: list[dict],
    gap_items: list[dict],
    target_job: str | None = None,
) -> dict | None:
    """确定性组装 suggestion（画像/方向/差距任一缺失 → None，禁止凭空建议）。

    - scores：画像评分（dimensions/overall_score 至少一个非空）
    - directions：方向候选（非空，方向匹配度 reason 数据源）
    - gap_items：差距清单（非空，差距 reason 数据源；：应传审计后保留项）
    - target_job：目标岗位（缺省取 directions[0].job_title）
    """
    if not scores.get("dimensions") and scores.get("overall_score") is None:
        return None
    directions = [d for d in (directions or []) if isinstance(d, dict)]
    if not directions:
        return None # 无方向数据 → 无方向匹配度依据
    gap_items = gap_items or []
    if not gap_items:
        return None # 无差距数据 → 无差距依据

    dimensions = scores.get("dimensions") or {}
    target_job = target_job or (directions[0].get("job_title") if directions else "目标岗位")
    match_score = directions[0].get("match_score")

    dim = _top_dim(dimensions)
    gap_skills = _gap_skills(gap_items)
    gap_count = len([g for g in gap_items if g.get("level") in ("不具备", "部分具备")])

    # summary：一句话结论（≤50 字）
    if gap_skills:
        summary = f"优先巩固{('、'.join(gap_skills[:2]))}等核心技能，围绕{target_job}完成项目落地后投递"
    else:
        summary = f"围绕{target_job}方向完善项目与简历，按计划推进并投递目标岗位"
    if len(summary) > 50:
        summary = summary[:50]

    short_term = (
        f"1 个月内：完成{'、'.join(gap_skills[:2]) or '目标岗位核心技能'}专项提升"
        f"（{gap_count} 项关键差距）+ 搭建 1 个{target_job}端到端项目"
    )
    mid_long_term = (
        f"1-3 个月：补齐{'、'.join(gap_skills[2:4]) or '工程化与项目经验'}并深化项目产出；"
        f"3 个月以上：投递{target_job}岗位并沉淀 2 个可展示项目"
    )

    reasons: list[str] = []
    if directions and isinstance(match_score, (int, float)):
        reasons.append(f"基于方向匹配度：{target_job}方向匹配 {int(match_score)} 分")
    if dim is not None:
        dim_name = {
            "technical": "技术能力", "project": "项目能力", "academic": "学业能力",
            "soft_skill": "综合素养", "industry_knowledge": "行业认知",
        }.get(dim[0], dim[0])
        reasons.append(f"基于画像评分：{dim_name} {dim[1]} 分（五维最高）")
    if gap_skills:
        reasons.append(
            f"基于差距分析：{gap_count} 项关键差距集中在{'、'.join(gap_skills[:3])}，短期可闭环"
        )
    if not reasons:
        return None # 无任何可引用数据点 → 不生成（禁止凭空建议）

    applicable_condition = (
        f"适用于以{target_job}为目标岗位的应届生；若计划转向其他方向，请参考对应方向建议"
    )

    return {
        "summary": summary,
        "short_term": short_term,
        "mid_long_term": mid_long_term,
        "reasons": reasons,
        "applicable_condition": applicable_condition,
    }


def build_suggestion(state: GraphState) -> dict | None:
    """Stage 2 完整报告 → suggestion；数据缺失/生成失败 → None（前端不展示建议卡）。"""
    return build_suggestion_from_parts(
        scores=state.get("scores") or {},
        directions=[d for d in (state.get("market_results") or []) if isinstance(d, dict)],
        gap_items=state.get("gap_items") or [],
        target_job=state.get("target_job"),
    )
