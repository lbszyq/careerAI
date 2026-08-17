"""图执行辅助：整图 watchdog（：整图 ≤180s，超时抛错由执行器 mark_failed）。"""
import asyncio
import logging

from app.core.config import get_settings
from app.ai.schemas import GraphState

logger = logging.getLogger("careerai.ai.runner")


async def run_graph(graph, initial_state: GraphState, *, timeout: float | None = None) -> dict:
    """以 watchdog 时间约束执行图（默认 AI_WATCHDOG_SECONDS=180s）。"""
    timeout = timeout if timeout is not None else get_settings().AI_WATCHDOG_SECONDS
    try:
        result = await asyncio.wait_for(graph.ainvoke(initial_state), timeout=timeout)
    except asyncio.TimeoutError as exc:
        logger.error("run_graph: 整图超时（>%ss）", timeout)
        raise TimeoutError("分析超时（整图 watchdog）") from exc
    return result
