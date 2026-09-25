"""Тесты сервиса матчинга сторон дел с контактами (app.services.matching)."""

from __future__ import annotations

from app.models.contact import Contact
from app.services.kad.parser import Side
from app.services.matching import match_side_to_contacts, normalize_name


def _contact(name: str, *, active: bool = True, inn: str = "6670000001") -> Contact:
    """Создаёт контакт-объект вне БД (для чисто-функциональных тестов)."""
    return Contact(
        company_name=name,
        inn=inn,
        email="test@example.com",
        is_active=active,
    )


# ------------------------- normalize_name -------------------------


def test_normalize_lowercases_and_strips_quotes():
    assert normalize_name('ООО "РЕМИСТР"') == "ремистр"


def test_normalize_removes_opf_variants():
    assert normalize_name("ООО «Ромашка»") == "ромашка"
    assert normalize_name("ЗАО Ромашка") == "ромашка"
    assert normalize_name("АО Ромашка") == "ромашка"
    assert normalize_name("ИП Иванов Иван Иванович") == "иванов иван иванович"
    assert normalize_name("Индивидуальный предприниматель Иванов") == "иванов"


def test_normalize_replaces_yo():
    assert normalize_name("Дятёл") == "дятел"
    assert normalize_name("Ёлка-2") == "елка 2"


def test_normalize_collapses_whitespace():
    assert normalize_name("  ООО    Ромашка \n Торг  ") == "ромашка торг"


def test_normalize_empty_and_none():
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


# ------------------------- match_side_to_contacts -------------------------


def test_match_exact_after_normalization():
    side = Side(name='ООО "Ромашка"', role="respondent")
    contact = _contact("ООО «Ромашка»")
    assert match_side_to_contacts(side, [contact]) is contact


def test_match_case_insensitive():
    side = Side(name="ООО РЕМИСТР", role="respondent")
    contact = _contact('ооо "ремистр"')
    assert match_side_to_contacts(side, [contact]) is contact


def test_match_substring_full_name_vs_short():
    """ФИО из дела целиком содержится в наименовании контакта (и наоборот)."""
    side = Side(name="Иванов Иван Иванович", role="respondent")
    contact = _contact("ИП Иванов Иван Иванович")
    assert match_side_to_contacts(side, [contact]) is contact

    side_short = Side(name="Иванов Иван", role="respondent")
    contact_full = _contact("Иванов Иван Иванович")
    assert match_side_to_contacts(side_short, [contact_full]) is contact_full


def test_no_match_for_different_names():
    side = Side(name='ООО "Ромашка"', role="respondent")
    contact = _contact("ООО ДругаяФирма")
    assert match_side_to_contacts(side, [contact]) is None


def test_inactive_contact_is_skipped():
    side = Side(name='ООО "Ромашка"', role="respondent")
    active = _contact("ООО Ромашка", active=False)
    assert match_side_to_contacts(side, [active]) is None


def test_empty_side_name_returns_none():
    side = Side(name="   ", role="respondent")
    contact = _contact("ООО Ромашка")
    assert match_side_to_contacts(side, [contact]) is None


def test_short_names_do_not_substring_match():
    """Слишком короткие строки (< 6 символов) не матчатся включением."""
    side = Side(name="ООО АО", role="respondent")  # нормализуется до ""
    assert normalize_name(side.name) == ""
    contact = _contact("АО АО")
    assert match_side_to_contacts(side, [contact]) is None
