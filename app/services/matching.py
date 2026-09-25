"""Сервис сопоставления (матчинга) сторон судебных дел с базой контактов по имени / ФИО."""

from __future__ import annotations

import re
from typing import Sequence

from app.models.contact import Contact
from app.services.kad.parser import Side

# Регулярное выражение для очистки организационно-правовых форм, кавычек и спецсимволов
_CLEAN_RE = re.compile(
    r"""(?xi)
    \b(индивидуальный\s+предприниматель|ип|ооо|зао|оао|пао|ао|некоммерческое\s+партнерство|нп|
       товарищество|муп|гуп|фгуп|фку|гку|ано|фонд|союз|ассоциация)\b
    |[«»""'’`\(\)\[\]\{\}\.,;:\-\\\/]+
    """
)
_WS_RE = re.compile(r"\s+")


def normalize_name(raw_name: str | None) -> str:
    """Нормализует наименование компании или ФИО для нечувствительного к регистру сравнения.

    - Приводит к нижнему регистру
    - Удаляет кавычки и пунктуацию
    - Удаляет популярные ОПФ (ООО, ИП, АО и т.д.)
    - Схлопывает множественные пробелы
    """
    if not raw_name:
        return ""
    # Заменяем ё на е
    text = raw_name.replace("ё", "е").replace("Ё", "Е").lower()
    # Удаляем ОПФ и спецсимволы
    cleaned = _CLEAN_RE.sub(" ", text)
    # Нормализуем пробелы
    return _WS_RE.sub(" ", cleaned).strip()


def match_side_to_contacts(
    side: Side,
    contacts: Sequence[Contact],
) -> Contact | None:
    """Ищет совпадение стороны дела с активными контактами по нормализованному ФИО/наименованию.

    Возвращает первый совпавший контакт или None.
    """
    side_norm = normalize_name(side.name)
    if not side_norm:
        return None

    for contact in contacts:
        if not contact.is_active:
            continue
        contact_norm = normalize_name(contact.company_name)
        if not contact_norm:
            continue

        # Прямое совпадение нормализованных строк
        if side_norm == contact_norm:
            return contact

        # Включение одного в другое (например, "Иванов Петр Сергеевич" и "Иванов Петр")
        if (len(side_norm) >= 6 and side_norm in contact_norm) or (
            len(contact_norm) >= 6 and contact_norm in side_norm
        ):
            return contact

    return None
