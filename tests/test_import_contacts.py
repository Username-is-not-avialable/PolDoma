"""Тесты для скрипта импорта контактов из Excel (import_contacts)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.contact import Contact
from scripts.import_contacts import (
    DEFAULT_EMAIL,
    DEFAULT_FILE,
    REASON_EMPTY,
    REASON_INVALID,
    clean_contacts,
    is_skippable_name,
    normalize_inn,
    normalize_name,
    parse_workbook,
    save_contacts,
    validate_email,
)


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


def _make_xlsx(
    path: Path,
    rows: list[tuple[Any, Any]],
    header: bool = True,
    sheet_title: str = "Лист1",
) -> Path:
    """Создаёт тестовый xlsx: строка 1 — заголовок «Истец» / «ИНН»."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_title
    if header:
        worksheet.append(["Истец", "ИНН"])
    for name, inn in rows:
        worksheet.append([name, inn])
    workbook.save(path)
    return path


@pytest.mark.parametrize(
    "value, expected",
    [
        ("7702157710", "7702157710"),
        ("0101000776", "0101000776"),  # ведущий ноль должен сохраниться
        ("27413474985", "27413474985"),  # 11 цифр — тоже валидно
        (" 7702157710 ", "7702157710"),
        (7801419491, "7801419491"),  # Excel-число
        (7801419491.0, "7801419491"),  # Excel-дробное число без дробной части
    ],
)
def test_normalize_inn_accepts_digit_sequences(value: Any, expected: str):
    inn, reason = normalize_inn(value)
    assert reason is None
    assert inn == expected


@pytest.mark.parametrize(
    "value, expected_reason",
    [
        (None, REASON_EMPTY),
        ("", REASON_EMPTY),
        ("   ", REASON_EMPTY),
        ("\xa0", REASON_EMPTY),
        ("7702157710, 7727107856", REASON_INVALID),  # несколько ИНН в ячейке
        ("5433976916\r\n5433967333", REASON_INVALID),  # перенос строки
        ("------------", REASON_INVALID),  # заглушка
        ("Ип Кретинин Ю.Ю.", REASON_INVALID),  # вместо ИНН — название
        ("7702 157710", REASON_INVALID),  # пробел внутри
        ("77021577100a", REASON_INVALID),
        (True, REASON_INVALID),  # bool — не ИНН
        (1.5, REASON_INVALID),
    ],
)
def test_normalize_inn_rejects_invalid(value: Any, expected_reason: str):
    inn, reason = normalize_inn(value)
    assert inn is None
    assert reason == expected_reason


def test_normalize_name_collapses_whitespace():
    assert normalize_name('  ООО "ЗОЛОТОЕ КОЛЬЦО"\r\nООО "ОПОРА" ') == (
        'ООО "ЗОЛОТОЕ КОЛЬЦО" ООО "ОПОРА"'
    )
    assert normalize_name("ООО\u00a0\"Ромашка\"") == 'ООО "Ромашка"'
    assert normalize_name(None) is None
    assert normalize_name("   ") is None


@pytest.mark.parametrize("name", ["удалить", "УДАЛИТЬ", " удалить ", "удалить.", "delete"])
def test_is_skippable_name_true(name: str):
    assert is_skippable_name(name) is True


@pytest.mark.parametrize(
    "name",
    ['Удалов И.И.', 'ООО "Удалить Сервис"', 'ООО "Ромашка"', ""],
)
def test_is_skippable_name_false(name: str):
    assert is_skippable_name(name) is False


def test_validate_email():
    assert validate_email(DEFAULT_EMAIL) == DEFAULT_EMAIL
    assert validate_email("  test@example.ru  ") == "test@example.ru"
    for bad in ("", "no-at-sign", "a@b", "a b@example.ru"):
        with pytest.raises(ValueError):
            validate_email(bad)


def test_parse_workbook_skips_invalid_and_counts(tmp_path: Path):
    path = _make_xlsx(
        tmp_path / "sample.xlsx",
        [
            ('ООО "Ромашка"', "7701234567"),
            ('ООО "Пустой ИНН"', None),
            ('ООО "Мульти"', "7702157710, 7727107856"),
            ("удалить", "7710077498"),
            (None, "7700000001"),
            ('ООО "Дубль"', "7701234567"),
            ('"АЛЬФА АЛЬЯНС"', 7736241375),
            ('"ВЕДУЩИЙ НОЛЬ"', "0101000776"),
        ],
    )

    report = parse_workbook(path)

    assert report.sheet_name == "Лист1"
    assert report.total_rows == 8
    assert report.skipped_empty_inn == 1
    assert report.skipped_invalid_inn == 1
    assert report.skipped_skip_name == 1
    assert report.skipped_empty_name == 1
    assert report.skipped_duplicates == 1
    assert report.imported == 3
    # все прочитанные строки учтены ровно в одной категории
    assert report.total_rows == (
        report.skipped_empty_inn
        + report.skipped_invalid_inn
        + report.skipped_skip_name
        + report.skipped_empty_name
        + report.skipped_duplicates
        + report.imported
    )

    by_inn = {item["inn"]: item for item in report.contacts}
    assert set(by_inn) == {"7701234567", "7736241375", "0101000776"}
    # email проставлен всем, контакт активен, в примечании — строка файла
    assert all(item["email"] == DEFAULT_EMAIL for item in report.contacts)
    assert all(item["is_active"] is True for item in report.contacts)
    assert by_inn["7701234567"]["company_name"] == 'ООО "Ромашка"'
    assert "строка 2" in by_inn["7701234567"]["notes"]
    # число из Excel приведено к строке цифр, ведущий ноль не потерян
    assert by_inn["7736241375"]["company_name"] == '"АЛЬФА АЛЬЯНС"'
    assert by_inn["0101000776"]["company_name"] == '"ВЕДУЩИЙ НОЛЬ"'

    assert len(report.invalid_samples) == 1
    assert "строка 4" in report.invalid_samples[0]


def test_parse_workbook_custom_email(tmp_path: Path):
    path = _make_xlsx(tmp_path / "sample.xlsx", [('ООО "Ромашка"', "7701234567")])
    report = parse_workbook(path, email="other@example.ru")
    assert report.contacts[0]["email"] == "other@example.ru"


def test_parse_workbook_without_header_treats_first_row_as_data(tmp_path: Path):
    path = _make_xlsx(
        tmp_path / "no_header.xlsx",
        [('ООО "Ромашка"', "7701234567"), ('ООО "Василёк"', "7709876543")],
        header=False,
    )
    report = parse_workbook(path)
    assert report.total_rows == 2
    assert report.imported == 2


def test_parse_workbook_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_workbook(tmp_path / "нет файла.xlsx")


def test_parse_workbook_unknown_sheet(tmp_path: Path):
    path = _make_xlsx(tmp_path / "sample.xlsx", [('ООО "Ромашка"', "7701234567")])
    with pytest.raises(ValueError, match="не найден"):
        parse_workbook(path, sheet="НетТакогоЛиста")


async def test_save_contacts_insert_and_idempotency(db_session: AsyncSession):
    contacts = [
        {
            "company_name": '"АЛЬФА АЛЬЯНС"',
            "inn": "7736241375",
            "email": DEFAULT_EMAIL,
            "phone": None,
            "is_active": True,
            "notes": "Импорт из «sample.xlsx», строка 2",
        },
        {
            "company_name": '"ВЕДУЩИЙ НОЛЬ"',
            "inn": "0101000776",
            "email": DEFAULT_EMAIL,
            "phone": None,
            "is_active": True,
            "notes": "Импорт из «sample.xlsx», строка 3",
        },
    ]

    inserted = await save_contacts(db_session, contacts)
    assert inserted == 2

    count = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count == 2

    # ведущий ноль сохранён, email проставлен
    res = await db_session.execute(select(Contact).where(Contact.inn == "0101000776"))
    contact = res.scalar_one()
    assert contact.email == DEFAULT_EMAIL
    assert contact.company_name == '"ВЕДУЩИЙ НОЛЬ"'

    # повторный импорт не создаёт дублей, но обновляет название
    updated = [dict(item) for item in contacts]
    updated[0]["company_name"] = '"АЛЬФА АЛЬЯНС (новое)"'
    await save_contacts(db_session, updated)

    count = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count == 2

    res = await db_session.execute(select(Contact).where(Contact.inn == "7736241375"))
    assert res.scalar_one().company_name == '"АЛЬФА АЛЬЯНС (новое)"'


async def test_save_contacts_empty_list_is_noop(db_session: AsyncSession):
    assert await save_contacts(db_session, []) == 0
    count = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count == 0


async def test_clean_contacts_removes_all(db_session: AsyncSession):
    db_session.add(Contact(company_name="Комп", inn="7700000001", email=DEFAULT_EMAIL))
    await db_session.commit()

    assert await clean_contacts(db_session) == 1
    count = (
        await db_session.execute(select(func.count()).select_from(Contact))
    ).scalar()
    assert count == 0


@pytest.mark.skipif(not DEFAULT_FILE.exists(), reason="нет файла data/список исцов.xlsx")
def test_parse_real_plaintiffs_file():
    """Разбор реального файла проекта (только чтение файла, БД не затрагивается).

    Файл лежит в data/ (каталог в .gitignore), поэтому тест пропускается, если
    его нет. Числа соответствуют текущему файлу: 1238 строк данных, 968 пустых
    ИНН, 19 невалидных значений, 5 строк-пометок «удалить», 2 дубликата ИНН.
    """
    report = parse_workbook(DEFAULT_FILE)

    assert report.total_rows == 1238
    assert report.skipped_empty_inn == 968
    assert report.skipped_invalid_inn == 19
    assert report.skipped_skip_name == 5
    assert report.skipped_empty_name == 0
    assert report.skipped_duplicates == 2
    assert report.imported == 244

    inns = [item["inn"] for item in report.contacts]
    assert len(inns) == len(set(inns))  # ИНН уникальны
    assert all(inn.isdigit() for inn in inns)  # только цифры, без иных знаков
    assert all(item["email"] == DEFAULT_EMAIL for item in report.contacts)
    assert all(item["company_name"] for item in report.contacts)
