"""执行器包：导入即注册（AI 执行器，/）。"""
from app.tasks.executors import ( # noqa: F401 注册副作用
    plan_reassess_executor,
    plan_regenerate_executor,
    report_stage1_executor,
    report_stage2_executor,
    resume_parse_executor,
)
