"""执行器注册表：task_type → 执行器。AI 执行器注册后自动被 workers 调度。"""
from app.tasks.executors.base import TaskExecutor


class ExecutorRegistry:
    _executors: dict[str, TaskExecutor] = {}

    @classmethod
    def register(cls, executor: TaskExecutor) -> None:
        cls._executors[executor.task_type] = executor

    @classmethod
    def get(cls, task_type: str) -> TaskExecutor:
        return cls._executors[task_type]

    @classmethod
    def has(cls, task_type: str) -> bool:
        return task_type in cls._executors

    @classmethod
    def all_types(cls) -> list[str]:
        return list(cls._executors.keys())