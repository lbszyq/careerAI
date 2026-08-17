"""Celery 应用（Redis broker；Windows 下 worker 需 --pool=solo）。"""
import os

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "careerai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.workers"],
)

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)