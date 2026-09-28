"""Тесты парсера КАД на зафиксированных ответах (без сети).

Структура фикстуры — ожидаемая по open-source парсерам; после первого
живого запроса её нужно заменить реальным ответом.
"""

from __future__ import annotations

from pathlib import Path

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


# ------------------------- HTML-ответ КАД -------------------------

FIXTURE_HTML = (
    Path(__file__).parent / "fixtures" / "kad_search_instances.html"
).read_text(encoding="utf-8")


def test_parse_html_cases_count_and_fields():
    cases = parse_response(FIXTURE_HTML)
    assert len(cases) == 3
    first = cases[0]
    assert first.case_number == "А60-59238/2026"
    assert first.guid == "1fccc72b-9aba-4836-8c1b-e99019aea5c5"
    assert first.case_type == "Г"
    assert first.court == "АС Свердловской области"
    assert first.judge == "Кузьминская О. А."
    assert first.start_date == "22.09.2026 0:00:00"


def test_parse_html_case_types():
    cases = {c.case_number: c for c in parse_response(FIXTURE_HTML)}
    assert cases["А60-59226/2026"].case_type == "Б"
    assert cases["А60-59233/2026"].case_type == "А"


def test_parse_html_parties_with_inn_and_address():
    case = parse_response(FIXTURE_HTML)[0]
    roles = {p.role: p for p in case.parties}
    plaintiff = roles["plaintiff"]
    assert plaintiff.name == 'АО Страховое "РЕСО-Гарантия"'
    assert plaintiff.inn == "7710045520"
    assert "г. Москва" in plaintiff.address
    respondent = roles["respondent"]
    assert respondent.inn == "6658515673"


def test_parse_html_multiple_respondents_and_empty_plaintiff():
    cases = {c.case_number: c for c in parse_response(FIXTURE_HTML)}
    multi = cases["А60-59233/2026"]
    respondents = [p for p in multi.parties if p.role == "respondent"]
    assert len(respondents) == 2
    assert respondents[1].name == 'ООО "РЕМИСТР"'
    assert respondents[1].inn == "8602107193"
    assert multi.judge is None  # судья не указан
    # истец есть
    assert [p.name for p in multi.parties if p.role == "plaintiff"] == [
        "ПРОКУРАТУРА СВЕРДЛОВСКОЙ ОБЛАСТИ"
    ]
    # у второго дела истца нет вовсе
    assert cases["А60-59226/2026"].parties[0].role == "respondent"


def test_parse_html_ignores_html_without_rows():
    assert parse_response("<html><body>Ничего не найдено</body></html>") == []
