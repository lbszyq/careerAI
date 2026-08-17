"""LangGraph 图构建（architecture.md /）。

- stage1_graph：START → router → (career_analysis ∥ market) → planner → END
- stage2_graph：START → market → executor → planner → END
- 节点级容错：任一节点抛异常不终止整图，异常写入 stage_errors，Planner 标注兜底（）。
- 进度回调：节点边界按 进度映射上报（执行器传入 deps.on_progress）。
"""
import logging
import time

from langgraph.graph import END, START, StateGraph

from app.ai.agents.career_analysis import career_analysis_node
from app.ai.agents.deps import AgentDeps
from app.ai.agents.executor_agent import executor_node
from app.ai.agents.market import market_research_node
from app.ai.agents.planner import planner_node
from app.ai.agents.router import router_node
from app.ai.schemas import GraphState
from app.observability.tracer import (
    finish_span,
    get_trace_id,
    reset_trace_context,
    set_trace_context,
    start_agent_span,
)

logger = logging.getLogger("careerai.ai.graphs")

_STAGE1_PROGRESS = {
    "router_node": (10, "解析画像"),
    "career_analysis_node": (40, "职业画像分析"),
    "market_research_node": (60, "市场数据检索"),
    "planner_node": (90, "生成报告"),
}
_STAGE2_PROGRESS = {
    "market_research_node": (20, "目标岗位要求"),
    "executor_node": (60, "差距分析与计划"),
    "planner_node": (90, "生成报告"),
}


def _wrap(deps: AgentDeps, fn, name: str, progress: dict[str, tuple[int, str]]):
    """绑定 deps + 节点级容错 + 进度上报 + agent（图节点）span。

    agent span 的 parent = 当前上下文 parent span（通常为 task root span）；
    节点失败时 agent span 标 failed + 记录错误摘要（截断/脱敏由 tracer 处理），
    但节点异常仍按 写入 stage_errors、不终止整图（节点容错与任务终态解耦）。
    """

    async def _wrapped(state: GraphState) -> dict:
        if deps.on_progress is not None and name in progress:
            percent, stage_text = progress[name]
            try:
                await deps.on_progress(percent, stage_text)
            except Exception: # noqa: BLE001 进度上报失败不影响节点
                logger.warning("graphs: 进度上报失败（node=%s）", name)

        # trace 上下文：显式（deps.trace_id / deps.parent_span_id）优先，缺省回退 contextvars
        trace_id = deps.trace_id or get_trace_id()
        agent_span = await start_agent_span(
            name, trace_id=trace_id, parent_span_id=deps.parent_span_id
        )
        agent_span_id = str(agent_span.id) if agent_span is not None else None
        tokens = set_trace_context(trace_id, agent_span_id)
        t0 = time.monotonic()
        try:
            result = await fn(state, deps)
        except Exception as exc: # noqa: BLE001 节点失败不终止整图（）
            logger.exception("graphs: 节点失败 %s（写入 stage_errors，继续执行）", name)
            await finish_span(
                agent_span_id,
                status="failed",
                duration_ms=_wrap_elapsed_ms(t0),
                error_message=str(exc),
            )
            return {
                "stage_errors": list(state.get("stage_errors") or []) + [f"{name}: {type(exc).__name__}"],
            }
        except BaseException: # noqa: BLE001 取消/超时（CancelledError 等 BaseException）：标记 failed 后继续抛出，不留孤儿 running span
            await finish_span(
                agent_span_id,
                status="failed",
                duration_ms=_wrap_elapsed_ms(t0),
                error_message="节点执行被取消（整图超时/任务取消）",
            )
            raise
        else:
            await finish_span(agent_span_id, status="succeeded", duration_ms=_wrap_elapsed_ms(t0))
            return result
        finally:
            reset_trace_context(tokens)

    return _wrapped


def _wrap_elapsed_ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def build_stage1_graph(deps: AgentDeps):
    graph = StateGraph(GraphState)
    for name, fn in (
        ("router_node", router_node),
        ("career_analysis_node", career_analysis_node),
        ("market_research_node", market_research_node),
        ("planner_node", planner_node),
    ):
        graph.add_node(name, _wrap(deps, fn, name, _STAGE1_PROGRESS))
    graph.add_edge(START, "router_node")
    graph.add_edge("router_node", "career_analysis_node")
    graph.add_edge("router_node", "market_research_node")
    graph.add_edge("career_analysis_node", "planner_node")
    graph.add_edge("market_research_node", "planner_node")
    graph.add_edge("planner_node", END)
    return graph.compile()


def build_stage2_graph(deps: AgentDeps):
    graph = StateGraph(GraphState)
    for name, fn in (
        ("market_research_node", market_research_node),
        ("executor_node", executor_node),
        ("planner_node", planner_node),
    ):
        graph.add_node(name, _wrap(deps, fn, name, _STAGE2_PROGRESS))
    graph.add_edge(START, "market_research_node")
    graph.add_edge("market_research_node", "executor_node")
    graph.add_edge("executor_node", "planner_node")
    graph.add_edge("planner_node", END)
    return graph.compile()


_PLAN_REGEN_PROGRESS = {
    "market_research_node": (20, "目标岗位要求"),
    "executor_node": (60, "差距分析与计划"),
    "planner_node": (90, "生成计划"),
}


def build_plan_regenerate_graph(deps: AgentDeps):
    """plan_regenerate：市场重检索 + executor 生成新计划 + Planner 组装（「重新生成」）。

    ：与 Stage2 图一致补齐 executor 节点（market → executor → planner）——
    此前缺 executor 导致 plan 无生成源，planner 兜底 plan 为空、update_plan 用空 plan 覆盖删库。
    gap_analyses 表与 report.result.gap_analysis 保留旧值（update_plan 仅写 plan/suggestion，）。
    """
    graph = StateGraph(GraphState)
    for name, fn in (
        ("market_research_node", market_research_node),
        ("executor_node", executor_node),
        ("planner_node", planner_node),
    ):
        graph.add_node(name, _wrap(deps, fn, name, _PLAN_REGEN_PROGRESS))
    graph.add_edge(START, "market_research_node")
    graph.add_edge("market_research_node", "executor_node")
    graph.add_edge("executor_node", "planner_node")
    graph.add_edge("planner_node", END)
    return graph.compile()
