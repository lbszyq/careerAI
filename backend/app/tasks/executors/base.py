"""任务执行器抽象接口。

接入 AI 任务执行器时，实现本接口并通过
ExecutorRegistry.register() 注册，即可被任务框架统一调度。
"""
from abc import ABC, abstractmethod


class TaskExecutor(ABC):
    """异步任务执行器：定义任务类型与执行逻辑。"""

    task_type: str

    @abstractmethod
    async def execute(self, job_id: str, params: dict) -> None:
        """执行任务并推进 task_jobs 状态/进度。

        :param job_id: task_jobs.id（字符串 UUID）
        :param params: 触发端点传入的业务参数（如 profile_id、report_id）
        """
        raise NotImplementedError