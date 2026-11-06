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

# ML Evolution tasks（显式注册：autodiscover 只扫描 app.tasks）
import app.core.data_ask.ml_evolution.tasks  # noqa: F401,E402

import app.core.data_ask.profile_tasks  # noqa: F401  # 阶段一画像任务

import app.core.data_ask.distill_tasks  # noqa: F401  # 阶段二知识蒸馏任务

import app.core.data_ask.metric_tasks  # noqa: F401  # P1 训练度量日物化任务

import app.core.data_ask.factory_tasks  # noqa: F401  # 阶段三智能体工厂任务


import app.core.data_ask.evaluation.eval_tasks  # noqa: F401  # 阶段四评估进化任务

import app.core.data_ask.train_center_tasks  # noqa: F401  # P1 训练中心统一工单任务

import app.core.dashboard.tasks  # noqa: F401  # 经营分析看板生成任务

import app.core.dashboard.subscribe_tasks  # noqa: F401  # P3 订阅推送与阈值告警任务

import app.core.analysis.preagg  # noqa: F401  # P6 预聚合刷新任务

from celery.schedules import crontab  # noqa: E402

celery_app.conf.beat_schedule = {
    "ds-eval-weekly-evolution": {
        "task": "ds_eval.weekly_evolution",
        "schedule": crontab(day_of_week="mon", hour=2, minute=0),
    },
    "agent-metric-daily": {
        "task": "ds_distill.materialize_metrics",
        "schedule": crontab(hour=3, minute=10),
    },
    "ds-distill-nightly-all": {
        # 北京时间 02:30（worker/beat 时区为 UTC）
        "task": "ds_distill.nightly_all_sources",
        "schedule": crontab(hour=18, minute=30),
    },
    "studio-dispatch-subscriptions": {
        "task": "studio.dispatch_subscriptions",
        "schedule": crontab(minute="*"),
    },
    "studio-check-alerts": {
        "task": "studio.check_alerts",
        "schedule": crontab(minute="*"),
    },
    "studio-refresh-preaggs": {
        "task": "studio.refresh_preaggs",
        "schedule": crontab(minute="*"),
    },
}
