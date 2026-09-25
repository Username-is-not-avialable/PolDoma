"""Тесты планировщика (app.scheduler)."""

from __future__ import annotations

import asyncio

import pytest

import app.scheduler as sched
from app.config import settings


@pytest.fixture(autouse=True)
async def _reset_scheduler():
    """Гарантирует, что глобальный планировщик не «утекает» между тестами."""
    yield
    if sched._scheduler is not None and sched._scheduler.running:
        sched._scheduler.shutdown(wait=False)
    sched._scheduler = None
    # даём event loop обработать отложенный shutdown
    await asyncio.sleep(0)


async def test_start_scheduler_registers_job(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(settings, "kad_poll_interval_minutes", 15)

    scheduler = sched.start_scheduler()
    try:
        assert scheduler.running
        job = scheduler.get_job(sched.JOB_ID)
        assert job is not None
        assert job.trigger.interval.total_seconds() == 15 * 60

        status = sched.get_scheduler_status()
        assert status["running"] is True
        assert status["enabled"] is True
        assert status["poll_interval_minutes"] == 15
        assert any(j["id"] == sched.JOB_ID for j in status["jobs"])
    finally:
        sched.stop_scheduler()
        await asyncio.sleep(0)

    assert sched._scheduler is None


async def test_start_scheduler_is_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    try:
        first = sched.start_scheduler()
        second = sched.start_scheduler()
        assert first is second
        assert second.running
        # дублирующий add_job не должен уронить планировщик
        assert second.get_job(sched.JOB_ID) is not None
    finally:
        sched.stop_scheduler()
        await asyncio.sleep(0)


async def test_start_scheduler_disabled_by_settings(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    scheduler = sched.start_scheduler()
    assert not scheduler.running
    assert scheduler.get_job(sched.JOB_ID) is None

    status = sched.get_scheduler_status()
    assert status["running"] is False
    assert status["enabled"] is False
    assert status["jobs"] == []


async def test_stop_scheduler_without_start_is_safe():
    sched.stop_scheduler()  # не должно выбрасывать исключения
    assert sched._scheduler is None


async def test_get_scheduler_status_before_start(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    status = sched.get_scheduler_status()
    assert status["running"] is False
    assert status["jobs"] == []
    assert status["poll_interval_minutes"] == settings.kad_poll_interval_minutes
