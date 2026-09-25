"""Сервис мониторинга КАД: опрос, дедупликация дел в БД, матчинг по имени и рассылка."""

from __future__ import annotations

import asyncio
from datetime import date
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models.case import Case as OrmCase, Side as OrmSide
from app.models.contact import Contact
from app.models.notification import Notification
from app.services.kad.client import iter_cases
from app.services.kad.parser import Case as KadCase
from app.services.mailer import send_case_notification
from app.services.matching import match_side_to_contacts

logger = logging.getLogger("monitor")

_monitoring_lock = asyncio.Lock()


async def _already_notified(
    session: AsyncSession, case_id: int, contact_id: int
) -> bool:
    """Проверяет, отправлялось ли уже уведомление по паре (дело, контакт)."""
    res = await session.execute(
        select(Notification.id).where(
            Notification.case_id == case_id,
            Notification.contact_id == contact_id,
        )
    )
    return res.scalar_one_or_none() is not None


async def save_case_if_new(
    session: AsyncSession,
    kad_case: KadCase,
) -> tuple[OrmCase | None, bool]:
    """Сохраняет дело и его стороны в БД, если дела с таким guid ещё нет.

    Возвращает (orm_case, is_new).
    """
    if not kad_case.guid:
        return None, False

    stmt = select(OrmCase).where(OrmCase.guid == kad_case.guid)
    res = await session.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing is not None:
        return existing, False

    new_case = OrmCase(
        guid=kad_case.guid,
        case_number=kad_case.case_number,
        case_type=kad_case.case_type,
        court=kad_case.court,
        judge=kad_case.judge,
        start_date=kad_case.start_date,
    )
    for s in kad_case.sides:
        new_case.sides.append(
            OrmSide(
                role=s.role,
                name=s.name,
                inn=s.inn,
                address=s.address,
            )
        )
    session.add(new_case)
    await session.commit()
    logger.info("Сохранено новое дело: %s (GUID: %s)", new_case.case_number, new_case.guid)
    return new_case, True


async def run_monitoring_cycle(
    target_date: str | None = None,
    courts: list[str] | None = None,
    case_types: list[str] | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Выполняет один цикл мониторинга КАД.

    1. Читает активные контакты из базы.
    2. Опрашивает КАД за указанную дату (по умолчанию сегодня).
    3. Дедуплицирует и сохраняет новые дела в БД.
    4. Для новых дел ищет ответчиков среди контактов по ФИО / наименованию.
    5. При совпадении отправляет email-уведомление.
    """
    if _monitoring_lock.locked():
        logger.warning("Предыдущий цикл мониторинга ещё выполняется, пропуск итерации.")
        return {"status": "skipped", "reason": "already_running"}

    async with _monitoring_lock:
        if not target_date:
            target_date = date.today().isoformat()
        if courts is None:
            courts = settings.kad_poll_courts
        if case_types is None:
            case_types = settings.kad_poll_case_types
        if max_pages is None:
            max_pages = settings.kad_max_pages_per_poll

        logger.info(
            "Старт цикла мониторинга КАД: date=%s, courts=%s, case_types=%s",
            target_date,
            courts,
            case_types,
        )

        # 1. Загружаем активные контакты из БД
        async with async_session_factory() as session:
            contacts_res = await session.execute(
                select(Contact).where(Contact.is_active == True)  # noqa: E712
            )
            contacts = list(contacts_res.scalars().all())

        logger.info("Загружено активных контактов для сопоставления: %s", len(contacts))

        stats = {
            "target_date": target_date,
            "total_cases_found": 0,
            "new_cases_saved": 0,
            "matches_found": 0,
            "notifications_sent": 0,
            "already_notified_skipped": 0,
            "errors": [],
        }

        # 2. Итерируемся по типам дел и судам
        seen_guids: set[str] = set()

        for c_type in case_types:
            try:
                async for kad_case in iter_cases(
                    date_from=target_date,
                    date_to=target_date,
                    courts=courts,
                    case_type=c_type,
                    max_pages=max_pages,
                ):
                    if not kad_case.guid or kad_case.guid in seen_guids:
                        continue
                    seen_guids.add(kad_case.guid)
                    stats["total_cases_found"] += 1

                    # 3. Дедупликация и сохранение
                    async with async_session_factory() as session:
                        orm_case, is_new = await save_case_if_new(session, kad_case)

                    if orm_case is None:
                        continue
                    if is_new:
                        stats["new_cases_saved"] += 1

                    # 4. Поиск совпадений по ответчикам (матчинг по имени / ФИО).
                    # Матчинг выполняется для всех найденных дел, а дедупликация
                    # отправок опирается на таблицу notifications: письмо, которое
                    # не удалось отправить, будет повторено в следующем цикле.
                    for side in kad_case.sides:
                        if side.role != "respondent":
                            continue

                        matched_contact = match_side_to_contacts(side, contacts)
                        if not matched_contact:
                            continue

                        stats["matches_found"] += 1
                        logger.info(
                            "Найдено совпадение ответчика по имени: дело=%s, ответчик=%r ↔ контакт=%r (email=%s)",
                            kad_case.case_number,
                            side.name,
                            matched_contact.company_name,
                            matched_contact.email,
                        )

                        # Дедупликация: не отправляем повторно по паре (дело, контакт)
                        async with async_session_factory() as session:
                            if await _already_notified(
                                session, orm_case.id, matched_contact.id
                            ):
                                stats["already_notified_skipped"] += 1
                                logger.info(
                                    "Уведомление по паре case=%s contact=%s уже отправлялось — пропуск.",
                                    orm_case.id,
                                    matched_contact.id,
                                )
                                continue

                        # 5. Отправка email-уведомления
                        try:
                            await send_case_notification(
                                to_email=matched_contact.email,
                                case=kad_case,
                                recipient_name=matched_contact.company_name,
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.error(
                                "Ошибка отправки письма для контакта %s: %s",
                                matched_contact.email,
                                exc,
                            )
                            stats["errors"].append(
                                f"Email error for {matched_contact.email}: {exc}"
                            )
                            continue

                        stats["notifications_sent"] += 1
                        # Фиксируем отправку, чтобы не дублировать письмо
                        async with async_session_factory() as session:
                            session.add(
                                Notification(
                                    case_id=orm_case.id,
                                    contact_id=matched_contact.id,
                                    email=matched_contact.email,
                                )
                            )
                            await session.commit()

            except Exception as exc:  # noqa: BLE001
                logger.error("Ошибка при опросе КАД (тип=%s): %s", c_type, exc)
                stats["errors"].append(f"KAD error ({c_type}): {exc}")

        logger.info("Цикл мониторинга КАД завершён: %s", stats)
        return stats
