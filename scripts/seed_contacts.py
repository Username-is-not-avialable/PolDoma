"""Скрипт первоначального наполнения таблицы contacts тестовыми данными.

Использование:
    python scripts/seed_contacts.py           # Добавить тестовые контакты
    python scripts/seed_contacts.py --clean   # Очистить таблицу contacts перед наполнением
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, engine
from app.models.contact import Contact

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_contacts")

# Реалистичный набор тестовых контактов.
# Включает компании из тестовых фикстур КАД (в т.ч. ООО "РЕМИСТР" с ИНН 8602107193)
# и строительные/производственные компании УрФО для сквозного тестирования.
SAMPLE_CONTACTS: list[dict[str, str | bool | None]] = [
    {
        "company_name": 'ООО "РЕМИСТР"',
        "inn": "8602107193",
        "email": "info@remistr.ru",
        "phone": "+7 (3462) 55-01-20",
        "is_active": True,
        "notes": "Ответчик по делу А60-59233/2026 в КАД (Сургут / Свердловская область)",
    },
    {
        "company_name": 'ООО "Ассоциация энергосберегающих предприятий"',
        "inn": "6671072519",
        "email": "contact@aep-ural.ru",
        "phone": "+7 (343) 287-11-22",
        "is_active": True,
        "notes": "Участник судебных споров в АС Свердловской области",
    },
    {
        "company_name": 'АО Страховое "РЕСО-Гарантия"',
        "inn": "7710045520",
        "email": "arbitr@reso.ru",
        "phone": "+7 (495) 730-30-00",
        "is_active": True,
        "notes": "Федеральная страховая компания (суброгационные споры)",
    },
    {
        "company_name": 'ООО "УралСтройМонтаж"',
        "inn": "6670412389",
        "email": "tender@uralstroymontazh.ru",
        "phone": "+7 (343) 310-44-55",
        "is_active": True,
        "notes": "Генподрядчик в Екатеринбурге, подрядные споры",
    },
    {
        "company_name": 'ООО "Вектор Развития"',
        "inn": "6685123901",
        "email": "director@vektor-ekb.ru",
        "phone": "+7 (343) 220-19-80",
        "is_active": True,
        "notes": "Поставки строительных материалов",
    },
    {
        "company_name": 'ООО "ТехноПромСервис"',
        "inn": "7453298710",
        "email": "sales@tehnoprom-chel.ru",
        "phone": "+7 (351) 799-30-40",
        "is_active": True,
        "notes": "Челябинский филиал оборудования, ключевой клиент",
    },
    {
        "company_name": 'ИП Иванов Петр Сергеевич',
        "inn": "667201928374",
        "email": "ip.ivanov.ekb@mail.ru",
        "phone": "+7 (912) 600-77-88",
        "is_active": True,
        "notes": "Индивидуальный предприниматель (субподряд, отделка)",
    },
    {
        "company_name": 'ООО "Неактивный Партнер"',
        "inn": "7701998877",
        "email": "inactive@test-company.ru",
        "phone": "+7 (495) 000-00-00",
        "is_active": False,
        "notes": "Тестовый контакт с флагом is_active=False (не рассылать)",
    },
]


async def clean_contacts(session: AsyncSession) -> int:
    """Удаляет все записи из таблицы contacts."""
    res = await session.execute(delete(Contact))
    await session.commit()
    count = res.rowcount or 0
    logger.info("Таблица contacts очищена (удалено записей: %s)", count)
    return count


async def seed_contacts(
    session: AsyncSession,
    contacts_data: Sequence[dict[str, str | bool | None]] = SAMPLE_CONTACTS,
) -> int:
    """Наполняет таблицу contacts записями.

    Использует upsert (ON CONFLICT (inn) DO UPDATE), чтобы повторный
    запуск скрипта был идемпотентным и обновлял реквизиты при изменении.
    """
    if not contacts_data:
        return 0

    inserted_or_updated = 0
    dialect = session.bind.dialect.name if session.bind else "postgresql"

    if dialect == "postgresql":
        for data in contacts_data:
            stmt = (
                pg_insert(Contact)
                .values(**data)
                .on_conflict_do_update(
                    index_elements=[Contact.inn],
                    set_={
                        "company_name": data["company_name"],
                        "email": data["email"],
                        "phone": data.get("phone"),
                        "is_active": data.get("is_active", True),
                        "notes": data.get("notes"),
                    },
                )
            )
            await session.execute(stmt)
            inserted_or_updated += 1
    else:
        # Для SQLite / тестовой БД
        for data in contacts_data:
            existing = (
                await session.execute(
                    select(Contact).where(Contact.inn == data["inn"])
                )
            ).scalar_one_or_none()
            if existing:
                existing.company_name = str(data["company_name"])
                existing.email = str(data["email"])
                existing.phone = data.get("phone")  # type: ignore[assignment]
                existing.is_active = bool(data.get("is_active", True))
                existing.notes = data.get("notes")  # type: ignore[assignment]
            else:
                session.add(Contact(**data))  # type: ignore[arg-type]
            inserted_or_updated += 1

    await session.commit()
    logger.info("Успешно записано/обновлено контактов: %s", inserted_or_updated)
    return inserted_or_updated


async def main() -> None:
    parser = argparse.ArgumentParser(description="Наполнение таблицы contacts тестовыми данными")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Очистить таблицу contacts перед наполнением",
    )
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.clean:
            await clean_contacts(session)

        count_before = (await session.execute(select(func.count()).select_from(Contact))).scalar() or 0
        logger.info("Контактов в базе до наполнения: %s", count_before)

        await seed_contacts(session)

        count_after = (await session.execute(select(func.count()).select_from(Contact))).scalar() or 0
        logger.info("Контактов в базе после наполнения: %s", count_after)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
