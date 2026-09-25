"""Тесты сервиса мониторинга КАД (app.services.monitor).

Используется изолированная in-memory SQLite; KAD-клиент и SMTP замоканы.
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.monitor as monitor
from app.database import Base
from app.models.case import Case as OrmCase
from app.models.contact import Contact
from app.models.notification import Notification
from app.services.kad.parser import Case as KadCase, Side as KadSide


@pytest.fixture
async def session_factory():
    """Изолированная фабрика сессий в SQLite in-memory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    yield factory
    await engine.dispose()


@pytest.fixture
async def contact(session_factory) -> Contact:
    """Активный контакт для матчинга."""
    async with session_factory() as session:
        contact = Contact(
            company_name='ООО "РЕМИСТР"',
            inn="6604045210",
            email="remistr@example.com",
            is_active=True,
        )
        session.add(contact)
        await session.commit()
        await session.refresh(contact)
        return contact


def make_kad_case(guid: str = "guid-1", number: str = "А60-100/2026") -> KadCase:
    return KadCase(
        guid=guid,
        case_number=number,
        case_type="И",
        court="АС Свердловской области",
        judge="Иванов И. И.",
        start_date="25.09.2026",
        sides=[
            KadSide(name='ООО "РЕМИСТР"', role="respondent", inn="6604045210"),
            KadSide(name="ПАО Рога и Копыта", role="plaintiff"),
        ],
    )


async def _run_with_mocks(
    session_factory,
    kad_cases: list[KadCase],
    send_mock: AsyncMock | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Запускает цикл мониторинга с замоканными KAD-клиентом, SMTP и БД."""

    async def fake_iter_cases(**_kwargs: Any) -> AsyncIterator[KadCase]:
        for case in kad_cases:
            yield case

    if send_mock is None:
        send_mock = AsyncMock(return_value={"status": "sent"})

    original_factory = monitor.async_session_factory
    original_iter = monitor.iter_cases
    original_send = monitor.send_case_notification
    monitor.async_session_factory = session_factory
    monitor.iter_cases = fake_iter_cases
    monitor.send_case_notification = send_mock
    try:
        return await monitor.run_monitoring_cycle(**kwargs)
    finally:
        monitor.async_session_factory = original_factory
        monitor.iter_cases = original_iter
        monitor.send_case_notification = original_send


# ------------------------- save_case_if_new -------------------------


async def test_save_case_if_new_saves_case_and_sides(session_factory):
    kad_case = make_kad_case()
    async with session_factory() as session:
        orm_case, is_new = await monitor.save_case_if_new(session, kad_case)

    assert is_new is True
    assert orm_case is not None
    assert orm_case.guid == "guid-1"
    assert orm_case.case_number == "А60-100/2026"

    async with session_factory() as session:
        saved = (
            await session.execute(select(OrmCase).where(OrmCase.guid == "guid-1"))
        ).scalar_one()
        assert len(saved.sides) == 2
        roles = {s.role for s in saved.sides}
        assert roles == {"respondent", "plaintiff"}


async def test_save_case_if_new_deduplicates_by_guid(session_factory):
    kad_case = make_kad_case()
    async with session_factory() as session:
        _, first_new = await monitor.save_case_if_new(session, kad_case)
    async with session_factory() as session:
        existing, second_new = await monitor.save_case_if_new(session, kad_case)

    assert first_new is True
    assert second_new is False
    assert existing is not None
    assert existing.guid == "guid-1"

    async with session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(OrmCase))
        ).scalar_one()
    assert count == 1


async def test_save_case_if_new_empty_guid(session_factory):
    kad_case = KadCase(guid="", case_number="А60-2/2026")
    async with session_factory() as session:
        orm_case, is_new = await monitor.save_case_if_new(session, kad_case)
    assert orm_case is None
    assert is_new is False


# ------------------------- run_monitoring_cycle -------------------------


async def test_cycle_saves_new_case_and_sends_notification(
    session_factory, contact
):
    send_mock = AsyncMock(return_value={"status": "sent"})
    stats = await _run_with_mocks(
        session_factory,
        [make_kad_case()],
        send_mock=send_mock,
        target_date="2026-09-25",
        case_types=["G"],
        courts=["EKATERINBURG"],
        max_pages=1,
    )

    assert stats["target_date"] == "2026-09-25"
    assert stats["total_cases_found"] == 1
    assert stats["new_cases_saved"] == 1
    assert stats["matches_found"] == 1
    assert stats["notifications_sent"] == 1
    assert stats["errors"] == []

    # Письмо отправлено на адрес контакта с указанием его наименования
    send_mock.assert_awaited_once()
    call_kwargs = send_mock.call_args.kwargs
    assert call_kwargs["to_email"] == "remistr@example.com"
    assert call_kwargs["recipient_name"] == 'ООО "РЕМИСТР"'

    # Дело сохранено в БД
    async with session_factory() as session:
        saved = (
            await session.execute(select(OrmCase).where(OrmCase.guid == "guid-1"))
        ).scalar_one()
        assert saved.id is not None

        # Есть запись в журнале уведомлений
        notif = (
            await session.execute(select(Notification))
        ).scalars().one_or_none()
        assert notif is not None
        assert notif.email == "remistr@example.com"
        assert notif.case_id == saved.id
        assert notif.contact_id == contact.id


async def test_cycle_deduplicates_second_run(session_factory, contact):
    send_mock = AsyncMock(return_value={"status": "sent"})
    cases = [make_kad_case()]

    first = await _run_with_mocks(
        session_factory,
        cases,
        send_mock=send_mock,
        target_date="2026-09-25",
        case_types=["G"],
        courts=["EKATERINBURG"],
        max_pages=1,
    )
    second = await _run_with_mocks(
        session_factory,
        cases,
        send_mock=send_mock,
        target_date="2026-09-25",
        case_types=["G"],
        courts=["EKATERINBURG"],
        max_pages=1,
    )

    assert first["new_cases_saved"] == 1
    assert first["notifications_sent"] == 1
    # Дело уже есть, уведомление уже отправлено — повторов нет
    assert second["new_cases_saved"] == 0
    assert second["already_notified_skipped"] == 1
    assert second["notifications_sent"] == 0
    assert send_mock.await_count == 1

    async with session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(OrmCase))
        ).scalar_one()
        notif_count = (
            await session.execute(select(func.count()).select_from(Notification))
        ).scalar_one()
    assert count == 1
    assert notif_count == 1


async def test_cycle_no_match_does_not_send(session_factory):
    """Нет совпадения с контактами — письма нет, но дело сохраняется."""
    kad_case = make_kad_case(guid="guid-2", number="А60-200/2026")
    kad_case.sides = [KadSide(name='ООО "НеРомашка"', role="respondent")]

    send_mock = AsyncMock(return_value={"status": "sent"})
    stats = await _run_with_mocks(
        session_factory,
        [kad_case],
        send_mock=send_mock,
        target_date="2026-09-25",
        case_types=["G"],
        courts=["EKATERINBURG"],
        max_pages=1,
    )

    assert stats["new_cases_saved"] == 1
    assert stats["matches_found"] == 0
    assert stats["notifications_sent"] == 0
    send_mock.assert_not_awaited()

    async with session_factory() as session:
        saved = (
            await session.execute(select(OrmCase).where(OrmCase.guid == "guid-2"))
        ).scalar_one()
        assert saved.id is not None


async def test_cycle_ignores_inactive_contacts(session_factory):
    """Неактивные контакты не получают уведомлений."""
    async with session_factory() as session:
        session.add(
            Contact(
                company_name='ООО "РЕМИСТР"',
                inn="6604045210",
                email="remistr@example.com",
                is_active=False,
            )
        )
        await session.commit()

    send_mock = AsyncMock(return_value={"status": "sent"})
    stats = await _run_with_mocks(
        session_factory,
        [make_kad_case()],
        send_mock=send_mock,
        target_date="2026-09-25",
        case_types=["G"],
        courts=["EKATERINBURG"],
        max_pages=1,
    )

    assert stats["matches_found"] == 0
    assert stats["notifications_sent"] == 0
    send_mock.assert_not_awaited()


async def test_cycle_email_error_recorded_and_notification_not_saved(
    session_factory, contact
):
    """Ошибка SMTP попадает в stats, запись в notifications не создаётся."""
    send_mock = AsyncMock(side_effect=RuntimeError("SMTP down"))
    stats = await _run_with_mocks(
        session_factory,
        [make_kad_case()],
        send_mock=send_mock,
        target_date="2026-09-25",
        case_types=["G"],
        courts=["EKATERINBURG"],
        max_pages=1,
    )

    assert stats["notifications_sent"] == 0
    assert len(stats["errors"]) == 1
    assert "SMTP down" in stats["errors"][0]

    # Дело сохранено, но уведомление не зафиксировано (будет повтор)
    async with session_factory() as session:
        case_count = (
            await session.execute(select(func.count()).select_from(OrmCase))
        ).scalar_one()
        notif_count = (
            await session.execute(select(func.count()).select_from(Notification))
        ).scalar_one()
    assert case_count == 1
    assert notif_count == 0

    # Повторный цикл с работающим SMTP должен отправить письмо
    retry_mock = AsyncMock(return_value={"status": "sent"})
    retry_stats = await _run_with_mocks(
        session_factory,
        [make_kad_case()],
        send_mock=retry_mock,
        target_date="2026-09-25",
        case_types=["G"],
        courts=["EKATERINBURG"],
        max_pages=1,
    )
    assert retry_stats["new_cases_saved"] == 0
    assert retry_stats["notifications_sent"] == 1
    retry_mock.assert_awaited_once()


async def test_cycle_skips_when_already_running(session_factory, contact):
    """Повторный запуск во время выполняющегося цикла отклоняется."""
    assert not monitor._monitoring_lock.locked()
    async with monitor._monitoring_lock:
        stats = await monitor.run_monitoring_cycle(target_date="2026-09-25")
    assert stats == {"status": "skipped", "reason": "already_running"}
