"""Тесты моделей базы данных: Case, Side, Contact."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.case import Case, Side
from app.models.contact import Contact


@pytest.fixture
async def db_session():
    """Тестовая изолированная сессия в SQLite in-memory."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    await test_engine.dispose()


async def test_create_case_with_sides(db_session: AsyncSession):
    case = Case(
        guid="test-guid-123",
        case_number="А60-12345/2026",
        case_type="G",
        court="АС Свердловской области",
        judge="Иванов И.И.",
        start_date="2026-09-25",
    )
    case.sides.append(
        Side(
            role="plaintiff",
            name="ООО Истец",
            inn="6670000001",
            address="г. Екатеринбург",
        )
    )
    case.sides.append(
        Side(
            role="respondent",
            name="ООО Ответчик",
            inn="6670000002",
            address="г. Москва",
        )
    )

    db_session.add(case)
    await db_session.commit()

    # Проверяем чтение
    stmt = select(Case).where(Case.guid == "test-guid-123")
    res = await db_session.execute(stmt)
    saved_case = res.scalar_one()

    assert saved_case.id is not None
    assert saved_case.case_number == "А60-12345/2026"
    assert len(saved_case.sides) == 2

    roles = {s.role: s for s in saved_case.sides}
    assert roles["plaintiff"].name == "ООО Истец"
    assert roles["respondent"].inn == "6670000002"


async def test_case_guid_uniqueness(db_session: AsyncSession):
    case1 = Case(guid="same-guid", case_number="А60-111/2026")
    case2 = Case(guid="same-guid", case_number="А60-222/2026")
    db_session.add(case1)
    await db_session.commit()

    db_session.add(case2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_cascade_delete_sides(db_session: AsyncSession):
    case = Case(guid="guid-cascade", case_number="А60-333/2026")
    case.sides.append(Side(role="plaintiff", name="ООО Удаляемое"))
    db_session.add(case)
    await db_session.commit()

    # Удаляем дело
    await db_session.delete(case)
    await db_session.commit()

    stmt = select(Side).where(Side.name == "ООО Удаляемое")
    res = await db_session.execute(stmt)
    assert res.scalar_one_or_none() is None


async def test_create_and_query_contact(db_session: AsyncSession):
    contact = Contact(
        company_name='ООО "РЕМИСТР"',
        inn="6671000000",
        email="info@remistr.ru",
        phone="+79991234567",
        is_active=True,
    )
    db_session.add(contact)
    await db_session.commit()

    stmt = select(Contact).where(Contact.inn == "6671000000")
    res = await db_session.execute(stmt)
    saved = res.scalar_one()

    assert saved.id is not None
    assert saved.company_name == 'ООО "РЕМИСТР"'
    assert saved.is_active is True


async def test_contact_inn_uniqueness(db_session: AsyncSession):
    c1 = Contact(company_name="Комп 1", inn="7700000001", email="c1@test.ru")
    c2 = Contact(company_name="Комп 2", inn="7700000001", email="c2@test.ru")
    db_session.add(c1)
    await db_session.commit()

    db_session.add(c2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
