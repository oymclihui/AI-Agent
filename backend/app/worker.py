"""
Celery worker for background tasks (document ingestion, long-running workflows).
"""
from celery import Celery
from app.config import settings

celery_app = Celery(
    "aiagnet",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])
