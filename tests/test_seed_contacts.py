"""Тесты для скрипта наполнения тестовыми контактами (seed_contacts)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.contact import Contact
from scripts.seed_contacts import SAMPLE_CONTACTS, clean_contacts, seed_contacts


@pytest.fixture
async def db_session():
    """Изолированная сессия в SQLite in-memory."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    await test_engine.dispose()


async def test_seed_contacts_populates_table(db_session: AsyncSession):
    count_before = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count_before == 0

    inserted = await seed_contacts(db_session, SAMPLE_CONTACTS)
    assert inserted == len(SAMPLE_CONTACTS)

    count_after = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count_after == len(SAMPLE_CONTACTS)

    # Проверяем наличие ключевого контакта (ООО "РЕМИСТР")
    res = await db_session.execute(select(Contact).where(Contact.inn == "8602107193"))
    remistr = res.scalar_one_or_none()
    assert remistr is not None
    assert remistr.company_name == 'ООО "РЕМИСТР"'
    assert remistr.is_active is True


async def test_seed_contacts_idempotency_and_update(db_session: AsyncSession):
    await seed_contacts(db_session, SAMPLE_CONTACTS)

    # Повторный вызов с обновлённым email для одной из компаний
    modified = [dict(item) for item in SAMPLE_CONTACTS]
    modified[0]["email"] = "new_remistr@test.ru"

    await seed_contacts(db_session, modified)

    # Количество контактов не должно увеличиться
    count = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count == len(SAMPLE_CONTACTS)

    # Но email должен обновиться
    res = await db_session.execute(select(Contact).where(Contact.inn == "8602107193"))
    remistr = res.scalar_one()
    assert remistr.email == "new_remistr@test.ru"


async def test_clean_contacts_removes_all(db_session: AsyncSession):
    await seed_contacts(db_session, SAMPLE_CONTACTS)
    count = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count > 0

    deleted = await clean_contacts(db_session)
    assert deleted == count

    count_after = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count_after == 0
