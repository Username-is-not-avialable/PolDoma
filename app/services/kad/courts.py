"""Справочник судов КАД: код ↔ название.

Коды используются в теле поискового запроса (поле Courts), например
['EKATERINBURG'] — АС Свердловской области. Список снят со страницы
kad.arbitr.ru (select#Courts) и лежит рядом в courts.json.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).with_name("courts.json")


def normalize(name: str) -> str:
    """Нормализация названия для сравнения: пробелы + регистр."""
    return re.sub(r"\s+", " ", name).strip().casefold()


@lru_cache(maxsize=1)
def all_courts() -> dict[str, str]:
    """Словарь код → название (все суды из справочника КАД)."""
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    return {item["code"]: item["name"] for item in data}


def find_courts(query: str) -> list[tuple[str, str]]:
    """Поиск судов по названию: сначала точное совпадение, затем вхождение."""
    needle = normalize(query)
    exact: list[tuple[str, str]] = []
    partial: list[tuple[str, str]] = []
    for code, name in all_courts().items():
        target = normalize(name)
        if target == needle:
            exact.append((code, name))
        elif needle in target:
            partial.append((code, name))
    return exact + partial


def require_code(name: str) -> str:
    """Код суда по названию; ошибка, если суд не найден."""
    matches = find_courts(name)
    if not matches:
        raise KeyError(f"Суд не найден в справочнике КАД: {name!r}")
    return matches[0][0]
