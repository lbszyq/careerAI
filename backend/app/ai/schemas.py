"""AI 图共享状态与节点输出结构（对齐 architecture.md GraphState 关键字段）。

LangGraph StateGraph 的 state_schema 使用本模块 TypedDict。
字段与 保持一致：profile / profile_complete / norm_benchmark / market_results /
scores / gap_items / plan / stage_errors / confidence。

并行合并语义（career_analysis ∥ market）：
- stage_errors / confidence 由多个并行节点写入，必须用 reducer（operator.add / operator.or_）
  合并，否则 LangGraph 的 LastValue channel 会因多值写入抛 InvalidUpdateError。
"""
import operator
from typing import Annotated, Any, TypedDict


class GraphState(TypedDict, total=False):
    # 输入
    user_id: str | None
    profile_id: str | None
    report_id: str | None
    direction_id: str | None
    preferred_cities: list[str] | None
    preferred_industries: list[str] | None
    expected_salary: float | None # 期望薪资（元/月，画像「求职偏好-期望薪资」，可空）
    profile_raw: str | None # 简历原文（resume_parse 输入）
    resume_file_path: str | None # 简历临时文件路径（解析后即删，C-008）
    stage: str | None # stage1 / stage2（planner 分支判断）

    # 节点产物（）
    profile: dict | None # 结构化画像
    profile_complete: bool | None # C-002 最低信息门槛
    norm_benchmark: dict | None # 常模命中单元（B-002）；None=样本不足/无表
    market_results: list | None # 3-5 方向候选（Stage1）或岗位要求（Stage2 由 target_job 区分）
    target_job: str | None # Stage2 目标岗位（direction.job_title）
    target_job_requirements: list | None # Stage2 岗位技能要求（JD 要求 [{name, required_level}]，executor 输入）
    target_job_jd_summary: dict | None # Stage2 JD 要求摘要（学历/薪资/趋势/技能，executor 输入）
    scores: dict | None # 综合评分 + 五维 + 常模对比 + 优劣势（reports-contract portrait）
    gap_items: list | None # 差距清单（技能/权重/等级，追溯 JD 要求）
    plan: dict | None # 三阶段成长计划（任务/资源/耗时）
    report: dict | None # Planner 最终报告（reports-contract 结构）

    # 兜底标注 / 置信度（，并行合并）
    stage_errors: Annotated[list[str], operator.add] # 失败节点写入，Planner 标注「该部分分析不完整」
    confidence: Annotated[dict, operator.or_] # 各段置信度（analysis/market/executor 分段合并）


def initial_state(**kwargs: Any) -> GraphState:
    """构造初始 GraphState（stage_errors/confidence 提供默认值）。"""
    state: GraphState = {"stage_errors": [], "confidence": {}}
    state.update({k: v for k, v in kwargs.items() if v is not None})
    return state
