"""Тесты парсера КАД на зафиксированных ответах (без сети).

Структура фикстуры — ожидаемая по open-source парсерам; после первого
живого запроса её нужно заменить реальным ответом.
"""

from __future__ import annotations

import pytest

from app.services.kad.parser import Case, parse_case, parse_response
from app.services.kad.client import build_search_body

FIXTURE = {
    "Items": [
        {
            "Id": "6fb9afec-b71d-4183-b917-4cace5958c16",
            "N": "А40-180791/2024",
            "CaseType": "Б",
            "Date": "2026-09-24",
            "Court": {"Name": "АС города Москвы"},
            "Judges": ["Иванов И. И."],
            "Sides": {
                "Items": [
                    {"Name": 'ООО "Ромашка"', "Inn": "7701234567", "Role": "Истец"},
                    {"Name": 'ООО "Василёк"', "Inn": "7709876543", "Role": "Ответчик"},
                ]
            },
        }
    ],
    "TotalCount": 1,
}


def test_parse_response_returns_cases():
    cases = parse_response(FIXTURE)
    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, Case)
    assert case.guid == "6fb9afec-b71d-4183-b917-4cace5958c16"
    assert case.case_number == "А40-180791/2024"
    assert case.court == "АС города Москвы"
    assert case.judge == "Иванов И. И."
    assert case.start_date == "2026-09-24"


def test_parse_case_splits_parties():
    case = parse_case(FIXTURE["Items"][0])
    roles = {p.role: p for p in case.parties}
    assert roles["plaintiff"].name == 'ООО "Ромашка"'
    assert roles["respondent"].inn == "7709876543"


def test_extract_records_unknown_payload():
    with pytest.raises(ValueError):
        parse_response({"Unexpected": []})


def test_build_search_body_matches_frontend_format():
    """Тело запроса должно повторять формат фронтенда КАД (kad.arbitr.ru.har)."""
    body = build_search_body("2026-09-21", "2026-09-24", courts=["EKATERINBURG"])
    assert body["DateFrom"] == "2026-09-21T00:00:00"
    assert body["DateTo"] == "2026-09-24T23:59:59"
    assert body["Courts"] == ["EKATERINBURG"]
    assert body["Page"] == 1
    assert body["Count"] == 25
    assert body["WithVKSInstances"] is False
    assert "CaseType" not in body
    assert "ChosenCourts" not in body
