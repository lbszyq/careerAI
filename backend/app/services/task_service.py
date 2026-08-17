"""异步任务编排：创建任务记录 → 派发 Celery → 状态查询 → 取消。"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode, TaskErrorCode
from app.models import TaskJob, User
from app.models.trace_span import TraceSpan
from app.repositories.task_job_repository import TaskJobRepository
from app.schemas.task import (
    TaskCancelResult,
    TaskJobOut,
    TaskTriggerRequest,
    TaskTriggerResult,
)
from app.services.error_codes import TaskCancelErrorCode, TaskQuotaErrorCode
from app.tasks.workers import run_task_job

logger = logging.getLogger("careerai.tasks")

# （越权审计）：trigger 端点白名单——显式枚举 5 个对外可注册任务类型。
# 前端不调用 trigger（tasksApi.ts 标注开发/调试用，全前端无调用点），白名单不误伤正常流程；
# 未知/内部类型一律 TASK_TYPE_UNSUPPORTED 拒绝（防空集：测试断言白名单 == 注册表全量）。
PUBLIC_TASK_TYPES = frozenset(
    {"resume_parse", "report_stage1", "report_stage2", "plan_regenerate", "plan_reassess"}
)

# 限流：原无既有配额、且消耗 AI 的任务类型（reports 3202 只覆盖 report_stage1 的完成口径；
# resume_parse / plan_regenerate / plan_reassess 原无任何配额）。report_stage2 仅能对本人已完成
# 报告 + 方向触发（资源归属已校验），且 Stage1 已有当日配额，不重复计数。
QUOTA_ELIGIBLE_TYPES = frozenset({"resume_parse", "plan_regenerate", "plan_reassess"})


class TaskService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.job_repo = TaskJobRepository(session)

    async def trigger(self, user: User, req: TaskTriggerRequest) -> TaskTriggerResult:
        """通用任务触发（开发/调试用）：白名单 + 归属拒绝。

        归属锚点：current_user.id（唯一可信）。params.user_id 仅允许等于当前用户——
        任何他人生份覆写（IDOR）直接 403/1002；executor 层另按 job.user_id 二次校验资源归属。
        """
        if req.task_type not in PUBLIC_TASK_TYPES:
            raise ApiError(TaskErrorCode.TASK_TYPE_UNSUPPORTED, f"不支持的任务类型: {req.task_type}", 400)
        params = req.params or {}
        raw_user_id = params.get("user_id")
        if raw_user_id is not None:
            try:
                claimed_user_id = uuid.UUID(str(raw_user_id))
            except (TypeError, ValueError):
                raise ApiError(ErrorCode.INVALID_PARAM, "user_id 参数非法", 400) from None
            if claimed_user_id != user.id:
                raise ApiError(TaskErrorCode.TASK_NOT_OWNED, "无权以他人身份触发任务", 403)
        job = await self.create_and_dispatch(user, req.task_type, params)
        return TaskTriggerResult(task_id=job.id, status=job.status)

    async def create_and_dispatch(self, user: User, task_type: str, params: dict) -> TaskJob:
        """落库 task_jobs → commit → 派发 Celery（服务重启不丢，任务链）。

        ：trace_id 在此（API 进程）生成，写入 task_jobs.trace_id 并作为任务参数
        显式传入 Celery worker（禁止全局可变状态）。

         限流：配额类型任务创建前校验当日额度（3004 TASK_QUOTA_EXCEEDED），
        覆盖 trigger 端点与全部服务层派发入口（upload_resume / _regenerate_plan / create_reassessment）。
        """
        if task_type in QUOTA_ELIGIBLE_TYPES:
            limit = get_settings().AI_DAILY_TASK_LIMIT
            used = await self.job_repo.count_quota_today(user.id, tuple(QUOTA_ELIGIBLE_TYPES))
            if used >= limit:
                raise ApiError(
                    TaskQuotaErrorCode.TASK_QUOTA_EXCEEDED,
                    f"当日任务次数已超限（{limit} 次/天）",
                    429,
                )
        job = await self.job_repo.create(user_id=user.id, task_type=task_type)
        trace_id = uuid.uuid4()
        job.trace_id = trace_id
        await self.session.commit()
        async_result = run_task_job.delay(str(job.id), task_type, params, str(trace_id))
        job.celery_task_id = async_result.id
        await self.session.commit()
        return job

    async def get_job(self, user: User, job_id: uuid.UUID) -> TaskJobOut:
        job = await self._get_owned_job(user, job_id)
        return TaskJobOut.model_validate(job)

    async def get_trace(self, user: User, job_id: uuid.UUID) -> list[TraceSpan]:
        """任务链路 span 查询：复用 get_job 所有权校验（4001/1002）。

        trace_id 为 NULL（历史任务）或无 span 时返回空列表（不报错）。
        """
        job = await self._get_owned_job(user, job_id)
        if job.trace_id is None:
            return []
        stmt = (
            select(TraceSpan)
            .where(TraceSpan.trace_id == job.trace_id)
            .order_by(TraceSpan.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _get_owned_job(self, user: User, job_id: uuid.UUID) -> TaskJob:
        """加载任务并校验所有权（get_job 同款：4001 不存在 / 1002 无权访问）。"""
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            raise ApiError(TaskErrorCode.TASK_NOT_FOUND, "任务不存在", 404)
        if job.user_id is not None and job.user_id != user.id:
            raise ApiError(TaskErrorCode.TASK_NOT_OWNED, "无权访问该任务", 403)
        return job

    async def cancel(self, user: User, job_id: uuid.UUID) -> TaskCancelResult:
        """取消进行中任务（tasks-contract）：Celery revoke + status=cancelled + finished_at。

        终态（succeeded/failed/cancelled）不可取消 → 3003。取消后业务行不落库由执行器
        的 _is_cancelled 检测保证（决策③）。
        """
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            raise ApiError(TaskErrorCode.TASK_NOT_FOUND, "任务不存在", 404)
        if job.user_id is not None and job.user_id != user.id:
            raise ApiError(TaskErrorCode.TASK_NOT_OWNED, "无权操作该任务", 403)
        if job.status in ("succeeded", "failed", "cancelled"):
            raise ApiError(TaskCancelErrorCode.TASK_ALREADY_FINISHED, "任务已结束，无法取消", 409)

        if job.celery_task_id:
            try:
                from app.tasks.celery_app import celery_app

                celery_app.control.revoke(job.celery_task_id, terminate=False)
            except Exception: # noqa: BLE001 取消以状态为准，broker 不可用时 best-effort
                logger.warning("cancel: revoke 失败 job=%s celery=%s", job.id, job.celery_task_id)
        await self.job_repo.mark_cancelled(job)
        await self.session.commit()
        return TaskCancelResult(task_id=job.id, status=job.status)
