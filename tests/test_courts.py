"""Тесты справочника судов КАД (без сети)."""

from __future__ import annotations

import pytest

from app.services.kad.courts import all_courts, find_courts, normalize, require_code




def test_all_courts_loaded():
    courts = all_courts()
    assert len(courts) > 100
    assert courts["EKATERINBURG"] == "АС Свердловской области"


def test_find_courts_by_partial_name():
    matches = find_courts("свердловск")
    assert ("EKATERINBURG", "АС Свердловской области") in matches


def test_normalize_ignores_case_and_spaces():
    assert normalize("  АС   Свердловской  области ") == "ас свердловской области"


def test_require_code_unknown_raises():
    with pytest.raises(KeyError):
        require_code("Такого суда нет")
