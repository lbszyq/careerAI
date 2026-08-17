"""成长计划阶段级能力化字段生成（plans-contract v1.1 /）。

阶段级 goal（目标能力）/ why（为什么，对应 JD 要求）/ verify（项目验证，覆盖技术/工程/业务
三产出）/ resume_value（简历资产）/ stage_completion（阶段完成条件，内容定义、不做系统校验）。

- 全部 optional/nullable：LLM 未输出或兜底路径缺失时由本模块补齐，保证结构稳定；
- 文案全部由已生成数据（gap_items/target_job/任务清单）推导，禁止编造新事实；
- verify 必须显式覆盖技术/工程/业务三产出（PRD v1.6-final 硬约束）。
"""
_STAGE_LABELS = {
    "short": "短期（1 个月内）",
    "mid": "中期（1-3 个月）",
    "long": "长期（3 个月以上）",
}


def stage_capability_fields(
    stage: str, tasks: list[dict], target_job: str, gap_items: list[dict]
) -> dict:
    """生成阶段能力化字段（缺省时 LLM/兜底共用）。"""
    label = _STAGE_LABELS.get(stage, stage)
    skills = _stage_skills(stage, tasks, gap_items)
    skills_text = "、".join(skills[:3]) or "目标岗位核心技能"

    if stage == "short":
        return {
            "label": label,
            "goal": f"掌握{skills_text}基础，达到可独立完成{target_job}基础任务的水平",
            "why": f"目标岗位要求掌握{skills_text}等基础技能，需在本阶段优先补齐",
            "verify": (
                f"完成 1 个端到端{target_job}项目（技术产出：{skills_text}；"
                f"工程产出：项目可运行/已部署；业务产出：输出 1 份可解读的分析结论）"
            ),
            "resume_value": f"可写入简历：独立完成{target_job}项目，沉淀{skills_text}能力",
            "stage_completion": "完成判定：项目产出验证通过 / 部署成功 / GitHub 提交记录，满足后进入下一阶段",
        }
    if stage == "mid":
        return {
            "label": label,
            "goal": f"深化{skills_text}并补齐工程化能力（代码规范/版本管理/部署），产出可展示项目",
            "why": f"在基础之上深化{skills_text}并补齐工程化能力，支撑{target_job}综合项目交付",
            "verify": (
                f"完成 1 个可展示的{target_job}综合项目（技术产出：{skills_text} 工程化；"
                f"工程产出：测试通过并部署上线；业务产出：解决 1 个真实业务问题）"
            ),
            "resume_value": f"可写入简历：主导完成{target_job}综合项目，具备工程化交付能力",
            "stage_completion": "完成判定：项目部署上线 / 测试用例通过 / 产出复盘文档，满足后进入下一阶段",
        }
    return {
        "label": label,
        "goal": f"达到{target_job}岗位投递标准（技能 + 项目 + 求职准备）",
        "why": f"达到{target_job}岗位投递标准，需沉淀完整项目链路并补齐求职准备（简历/面试/投递）",
        "verify": (
            f"完成 2 个可展示项目并完成求职闭环（技术产出：{skills_text} 沉淀；"
            f"工程产出：作品集仓库可公开访问；业务产出：输出 2 份业务复盘与面试复盘）"
        ),
        "resume_value": f"可写入简历：具备{target_job}完整项目链路经验，作品集可公开访问",
        "stage_completion": "完成判定：作品集仓库可公开访问 / 完成多场模拟面试与岗位投递，进入求职阶段",
    }


def _stage_skills(stage: str, tasks: list[dict], gap_items: list[dict]) -> list[str]:
    """阶段技能：优先该阶段任务名命中的差距技能；无则取差距清单前几项。"""
    out: list[str] = []
    for t in tasks or []:
        if t.get("stage") != stage:
            continue
        name = str(t.get("name") or "")
        for g in gap_items or []:
            skill = str(g.get("skill") or "").strip()
            if skill and skill in name and skill not in out:
                out.append(skill)
    if not out:
        for g in gap_items or []:
            skill = str(g.get("skill") or "").strip()
            if skill and skill not in out:
                out.append(skill)
    return out[:3]
