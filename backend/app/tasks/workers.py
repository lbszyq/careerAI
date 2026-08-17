"""Celery worker 任务入口：从注册表调度执行器。"""
import asyncio
import logging
import os
import time
import uuid

from app.tasks.celery_app import celery_app

logger = logging.getLogger("careerai.tasks")

# tasks-contract：error_message 为用户友好文案（QA-BUG-003 兜底写入）
_WORKER_FAILED_MESSAGE = "任务执行失败，请稍后重试"


@celery_app.task(name="app.tasks.run_task_job", bind=True, max_retries=0)
def run_task_job(self, job_id: str, task_type: str, params: dict | None = None, trace_id: str | None = None) -> str:
    """任务入口：按 task_type 从执行器注册表取执行器并执行。

    QA-BUG-003：worker 每任务经 asyncio.run 新建 event loop，db/base.py 的全局连接池
    若绑定旧 loop 跨循环复用会崩溃，故必须在首次导入执行器（首次创建 engine）前声明
    WORKER_MODE → NullPool；异常兜底确保 task_jobs 不滞留 pending。

    ：trace_id 由 API 进程生成、作为任务参数显式传入，经 contextvars 传入执行器
    （禁止全局可变状态；并发多任务由 contextvars 隔离）。
    """
    os.environ.setdefault("WORKER_MODE", "true") # db/base.py 按 == "true" 判定 NullPool
    from app.tasks.executors.registry import ExecutorRegistry

    try:
        executor = ExecutorRegistry.get(task_type)
        asyncio.run(_run_with_trace(executor, job_id, params or {}, trace_id))
    except Exception as exc: # noqa: BLE001 兜底：未捕获异常落终态 failed
        logger.exception("task_job 执行失败 job=%s task_type=%s", job_id, task_type)
        asyncio.run(_mark_job_failed(job_id, _WORKER_FAILED_MESSAGE))
        raise
    return job_id


async def _run_with_trace(executor, job_id: str, params: dict, trace_id: str | None) -> None:
    """在 async event loop 内注入 trace 上下文并写 task root span，再执行 executor。

    task root span 在此（worker 层）统一写入，覆盖所有执行器（含 resume_parse / plan_reassess
    等非图执行器），保证每个任务都有 task root span 供 agent/llm/rag span 回溯 parent。
    trace_id 缺失（旧队列/历史任务）时生成并回写 task_jobs.trace_id，避免 span 不可查。
    终态以 task_jobs.status 为准（executor 内部 mark_succeeded/failed 但可能正常返回）。
    """
    from app.observability.tracer import (
        finish_span,
        reset_trace_context,
        set_trace_context,
        start_task_span,
    )

    tid = await _ensure_trace_id(job_id, trace_id)
    t0 = time.monotonic()
    task_span = await start_task_span(name=f"task:{job_id}", trace_id=tid)
    task_span_id = str(task_span.id) if task_span is not None else None
    tokens = set_trace_context(tid, task_span_id)
    try:
        await executor.execute(job_id, params)
    except BaseException as exc: # noqa: BLE001 含 CancelledError/SystemExit 等，标记 failed 后继续抛出
        await finish_span(
            task_span_id, status="failed", duration_ms=_worker_elapsed_ms(t0), error_message=str(exc)
        )
        raise
    else:
        final_status = "succeeded" if await _job_status(job_id) == "succeeded" else "failed"
        await finish_span(task_span_id, status=final_status, duration_ms=_worker_elapsed_ms(t0))
    finally:
        reset_trace_context(tokens)


async def _ensure_trace_id(job_id: str, trace_id: str | None) -> str:
    """trace_id 缺失（旧队列/历史任务 NULL）时生成并回写 task_jobs.trace_id（保证 span 可查）。"""
    if trace_id:
        return trace_id
    from app.db.base import AsyncSessionLocal
    from app.models import TaskJob

    new_tid = uuid.uuid4()
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(TaskJob, uuid.UUID(job_id))
            if job is not None and job.trace_id is None:
                job.trace_id = new_tid
                await session.commit()
    except Exception: # noqa: BLE001 回写失败仅记日志，不阻断任务
        logger.warning("worker: 回写 trace_id 失败 job=%s", job_id)
    return str(new_tid)


async def _job_status(job_id: str) -> str | None:
    """读取 task_jobs 终态（task root span 的 succeeded/failed 以真实状态为准）。"""
    from app.db.base import AsyncSessionLocal
    from app.models import TaskJob

    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(TaskJob, uuid.UUID(job_id))
            return job.status if job is not None else None
    except Exception: # noqa: BLE001 读取失败仅记日志
        logger.warning("worker: 读取任务状态失败 job=%s", job_id)
        return None


def _worker_elapsed_ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


async def _mark_job_failed(job_id: str, error_message: str) -> None:
    """兜底落 failed：失败原因用户友好，详细异常走日志 / Celery 侧失败态。"""
    from app.db.base import AsyncSessionLocal
    from app.repositories.task_job_repository import TaskJobRepository

    try:
        async with AsyncSessionLocal() as session:
            repo = TaskJobRepository(session)
            job = await repo.get_by_id(uuid.UUID(job_id))
            if job is not None and job.status not in ("succeeded", "failed", "cancelled"):
                await repo.mark_failed(job, error_message)
                await session.commit()
    except Exception: # noqa: BLE001 兜底再失败仅记日志，不影响 Celery 侧失败态
        logger.exception("task_job 兜底标记 failed 失败 job=%s", job_id)
