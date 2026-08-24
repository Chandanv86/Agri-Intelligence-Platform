"""Celery application scaffold.

See docs/PRODUCTION_IMPLEMENTATION_PLAN.md §2 for the full design rationale.
This module only wires up the Celery app and task routing/limits; it does
NOT change the existing synchronous DEMO snapshot path in
app/services/snapshot.py -- that stays exactly as-is until credentials
exist to make a real LIVE path meaningful (see docs/KNOWN_LIMITATIONS.md).

Importing this module must never require Redis to be reachable (tests and
`uvicorn app.main:app` must keep working with zero infra running) -- Celery
itself defers the actual connection until a task is sent/consumed, so plain
`import` here is safe.
"""

from celery import Celery

from ..core.config import settings

celery_app = Celery(
    "agri_intel",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_acks_late=True,               # a worker crash mid-GEE-call must not lose the task
    worker_prefetch_multiplier=1,      # don't hoard slow IO-bound tasks on one worker
    task_time_limit=120,               # hard kill runaway connector calls
    task_soft_time_limit=90,
    result_expires=60 * 60 * 6,        # 6h -- snapshots go stale on their own anyway
    task_routes={
        "agri.build_snapshot": {"queue": "snapshot"},
        "agri.build_baseline": {"queue": "baseline"},
    },
    task_default_queue="snapshot",
)

# Task modules register themselves on import.
celery_app.autodiscover_tasks(["app.workers"], related_name="tasks")
