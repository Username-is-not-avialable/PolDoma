"""Планировщик фоновых задач мониторинга КАД (APScheduler)."""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.services.monitor import run_monitoring_cycle

logger = logging.getLogger("scheduler")

_scheduler: AsyncIOScheduler | None = None
JOB_ID = "kad_periodic_monitoring"


def get_scheduler() -> AsyncIOScheduler:
    """Возвращает глобальный экземпляр планировщика."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def start_scheduler() -> AsyncIOScheduler:
    """Запускает планировщик задач, если включен в настройках."""
    scheduler = get_scheduler()
    if not settings.scheduler_enabled:
        logger.info("APScheduler отключен в настройках (SCHEDULER_ENABLED=false).")
        return scheduler

    if not scheduler.running:
        scheduler.add_job(
            run_monitoring_cycle,
            trigger="interval",
            minutes=settings.kad_poll_interval_minutes,
            id=JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.start()
        logger.info(
            "APScheduler успешно запущен: опрос КАД каждые %s минут.",
            settings.kad_poll_interval_minutes,
        )
    return scheduler


def stop_scheduler() -> None:
    """Останавливает планировщик задач."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler остановлен.")
        _scheduler = None


def get_scheduler_status() -> dict[str, Any]:
    """Возвращает текущее состояние планировщика и запланированных задач."""
    scheduler = get_scheduler()
    jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                }
            )
    return {
        "running": scheduler.running,
        "enabled": settings.scheduler_enabled,
        "poll_interval_minutes": settings.kad_poll_interval_minutes,
        "jobs": jobs,
    }
