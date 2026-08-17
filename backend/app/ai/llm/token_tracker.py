"""Token 与成本追踪（architecture.md ：成本可量化、可验证）。"""
import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger("careerai.ai.cost")


@dataclass
class _CallRecord:
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    latency_ms: int
    created_at: float = field(default_factory=time.time)


class TokenTracker:
    """进程内 Token/成本计数器（线程安全）。

    单次调用成本 = 输入 tokens × 输入单价 + 输出 tokens × 输出单价（¥/百万）。
    本地版本 用内存计数器 + 结构化日志；后续可换 Redis/DB 持久化（P1）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[_CallRecord] = []
        self._total_calls = 0
        self._total_input = 0
        self._total_output = 0
        self._total_cost = 0.0

    def record(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        price_per_million_input: float,
        price_per_million_output: float,
        latency_ms: int,
    ) -> float:
        cost = (prompt_tokens / 1_000_000) * price_per_million_input + (
            completion_tokens / 1_000_000
        ) * price_per_million_output
        with self._lock:
            self._records.append(
                _CallRecord(model, prompt_tokens, completion_tokens, cost, latency_ms)
            )
            self._total_calls += 1
            self._total_input += prompt_tokens
            self._total_output += completion_tokens
            self._total_cost += cost
        logger.info(
            "llm_call model=%s in=%d out=%d cost=%.4f latency=%dms",
            model,
            prompt_tokens,
            completion_tokens,
            cost,
            latency_ms,
        )
        return cost

    def snapshot(self) -> dict:
        """返回成本快照（DoD：单次调用平均成本 + 月度预估）。"""
        with self._lock:
            total_calls = self._total_calls
            total_cost = self._total_cost
            total_input = self._total_input
            total_output = self._total_output
        avg_cost = (total_cost / total_calls) if total_calls else 0.0
        # 月度预估：假设 DAU 100 × 日均 1 次报告 × 30 天（口径）
        monthly_estimate = avg_cost * 100 * 1 * 30
        return {
            "total_calls": total_calls,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_yuan": round(total_cost, 4),
            "avg_cost_per_call_yuan": round(avg_cost, 6),
            "monthly_estimate_yuan": round(monthly_estimate, 2),
        }

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._total_calls = 0
            self._total_input = 0
            self._total_output = 0
            self._total_cost = 0.0


# 全局单例（worker/API 进程内共享）
_token_tracker = TokenTracker()


def get_token_tracker() -> TokenTracker:
    return _token_tracker
