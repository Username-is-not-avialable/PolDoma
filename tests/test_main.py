"""Тесты FastAPI-приложения (app.main): /health, /api/v1/monitor/trigger, lifespan."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

import app.main as main_module
from app.config import settings


class _BrokenEngine:
    """Движок, который всегда падает при подключении (имитация недоступной БД)."""

    def connect(self):
        raise RuntimeError("connection refused")

    async def dispose(self) -> None:  # noqa: D102
        return None


@pytest.fixture
def sqlite_engine():
    """Локальный SQLite-движок вместо боевого PostgreSQL в lifespan/health."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield engine
    # dispose уже вызван lifespan'ом; повторный вызов безопасен


@pytest.fixture
def client(monkeypatch, sqlite_engine):
    """TestClient с отключённым планировщиком и изолированной БД."""
    monkeypatch.setattr(main_module, "engine", sqlite_engine)
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert set(data["scheduler"]) >= {"running", "enabled", "jobs"}
    assert data["scheduler"]["enabled"] is False


def test_health_degraded_when_db_unavailable(monkeypatch):
    monkeypatch.setattr(main_module, "engine", _BrokenEngine())
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    with TestClient(main_module.app) as test_client:
        resp = test_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["database"] == "disconnected"


def test_trigger_monitoring_accepted(client, monkeypatch):
    cycle_mock = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(main_module, "run_monitoring_cycle", cycle_mock)

    resp = client.post(
        "/api/v1/monitor/trigger",
        params={"target_date": "2026-09-25", "max_pages": 3},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"

    # BackgroundTasks выполняются до возврата ответа TestClient
    cycle_mock.assert_awaited_once_with(target_date="2026-09-25", max_pages=3)


def test_trigger_monitoring_defaults(client, monkeypatch):
    cycle_mock = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(main_module, "run_monitoring_cycle", cycle_mock)

    resp = client.post("/api/v1/monitor/trigger")
    assert resp.status_code == 202
    cycle_mock.assert_awaited_once_with(target_date=None, max_pages=None)


def test_lifespan_calls_start_and_stop_scheduler(monkeypatch, sqlite_engine):
    """Lifespan при старте запускает планировщик, при остановке — гасит всё."""
    monkeypatch.setattr(main_module, "engine", sqlite_engine)
    start_mock = Mock(return_value=None)
    stop_mock = Mock(return_value=None)
    shutdown_session_mock = Mock(return_value=None)
    monkeypatch.setattr(main_module, "start_scheduler", start_mock)
    monkeypatch.setattr(main_module, "stop_scheduler", stop_mock)
    monkeypatch.setattr(main_module, "shutdown_session", shutdown_session_mock)

    with TestClient(main_module.app):
        pass

    start_mock.assert_called_once()
    stop_mock.assert_called_once()
    shutdown_session_mock.assert_called_once()


def test_openapi_available(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/monitor/trigger" in paths
