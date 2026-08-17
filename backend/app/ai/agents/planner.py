"""planner_node（Planner Agent，）：整合输出最终报告 JSON（reports-contract 结构）。

LLM 优先整合；失败/不可用时用兜底组装器（fallback/report_assembler），
并对失败段标注「该部分分析不完整」（）。
"""
import json
import logging

from app.ai.agents.deps import AgentDeps
from app.ai.fallback.report_assembler import (
    assemble_stage1_report,
    assemble_stage2_report,
    finalize_report,
)
from app.ai.grounding import audit_report_grounding
from app.ai.llm.exceptions import LLMError
from app.ai.prompts import render_prompt
from app.ai.schemas import GraphState

logger = logging.getLogger("careerai.ai.agents.planner")


async def planner_node(state: GraphState, deps: AgentDeps) -> dict:
    stage = state.get("stage") or ("stage2" if state.get("target_job") else "stage1")
    fallback_report = (
        assemble_stage1_report(state) if stage == "stage1" else assemble_stage2_report(state)
    )

    report = None
    if deps.llm is not None and deps.llm.is_available:
        try:
            prompt = render_prompt("planner.md", 
                stage=stage,
                scores=json.dumps(state.get("scores") or {}, ensure_ascii=False),
                market_results=json.dumps(state.get("market_results") or [], ensure_ascii=False),
                gap_items=json.dumps(state.get("gap_items") or [], ensure_ascii=False),
                plan=json.dumps(state.get("plan") or {}, ensure_ascii=False),
                stage_errors=json.dumps(state.get("stage_errors") or [], ensure_ascii=False),
                fallback_report=json.dumps(fallback_report, ensure_ascii=False),
            )
            data = await deps.llm.complete_json(
                system_prompt=prompt,
                user_prompt="请整合上游输出，生成最终报告 JSON。",
                node_name="planner_node",
            )
            if data.get("stage") in ("stage1", "stage2"):
                report = finalize_report(data, state, stage) # v1.1：suggestion/confidence_reasons 归一化
        except LLMError as exc:
            logger.warning("planner: LLM 失败使用兜底组装: %s", exc)

    if report is None:
        report = fallback_report
        errors = list(state.get("stage_errors") or [])
        if not errors:
            errors.append("报告使用规则组装（LLM 不可用或失败）")
        report["notes"] = report.get("notes") or []
        report["notes"].extend([f"该部分分析不完整（{e}）" for e in errors if f"（{e}）" not in " ".join(report["notes"])])

    # 事实接地硬审计（链路末尾）——每条「建议/差距/证据」claim 必须可映射到
    # 画像字段或 market_data/career_directions 记录，无据 claim 删除而非仅降置信度（CR-004 闭环）。
    report = audit_report_grounding(report, state)
    return {"report": report, "stage": stage}
