"""Точка входа FastAPI приложения.

Управляет жизненным циклом (Lifespan):
- Инициализация и проверка подключения к БД
- Запуск планировщика периодического опроса КАД (APScheduler)
- Корректное завершение (shutdown): остановка планировщика, закрытие сессии браузера КАД, закрытие пула БД.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import Any

from fastapi import BackgroundTasks, FastAPI, status
from sqlalchemy import text

from app.database import engine
from app.scheduler import get_scheduler_status, start_scheduler, stop_scheduler
from app.services.kad.client import shutdown_session
from app.services.monitor import run_monitoring_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    logger.info("Запуск приложения PolDoma...")

    # 1. Проверяем подключение к базе данных
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1;"))
        logger.info("Подключение к PostgreSQL успешно проверено.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("База данных недоступна при старте: %s", exc)

    # 2. Запускаем планировщик периодических задач
    start_scheduler()

    yield

    # При завершении работы приложения:
    logger.info("Остановка приложения PolDoma...")

    # 1. Останавливаем планировщик
    stop_scheduler()

    # 2. Закрываем фоновую сессию браузера Playwright
    try:
        shutdown_session()
        logger.info("Браузерная сессия КАД успешно закрыта.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ошибка при закрытии сессии КАД: %s", exc)

    # 3. Закрываем пул соединений БД
    try:
        await engine.dispose()
        logger.info("Пул соединений с БД закрыт.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ошибка при закрытии пула БД: %s", exc)


app = FastAPI(
    title="PolDoma - Мониторинг КАД и рассылка уведомлений",
    description="Автоматический опрос новых дел в КАД, дедупликация в БД, матчинг по именам и email-уведомления",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", summary="Проверка состояния сервиса")
async def health_check() -> dict[str, Any]:
    """Проверка доступности базы данных и статуса планировщика."""
    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1;"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False

    scheduler_status = get_scheduler_status()

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "scheduler": scheduler_status,
    }


@app.post(
    "/api/v1/monitor/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ручной запуск цикла мониторинга в фоне",
)
async def trigger_monitoring(
    background_tasks: BackgroundTasks,
    target_date: str | None = None,
    max_pages: int | None = None,
) -> dict[str, str]:
    """Запускает один цикл мониторинга в фоновом режиме без блокировки ответа API."""
    background_tasks.add_task(
        run_monitoring_cycle,
        target_date=target_date,
        max_pages=max_pages,
    )
    return {
        "status": "accepted",
        "message": "Цикл мониторинга запущен в фоновом режиме",
    }
