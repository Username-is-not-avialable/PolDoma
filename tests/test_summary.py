"""Тесты сводки о новых делах (app.services.summary)."""

from __future__ import annotations

from app.services.kad.parser import Case as KadCase, Side as KadSide
from app.services.summary import build_summary_text, write_summary


def _case(guid: str = "guid-1", number: str = "А60-100/2026") -> KadCase:
    return KadCase(
        guid=guid,
        case_number=number,
        case_type="Г",
        court="АС Свердловской области",
        judge="Иванов И. И.",
        start_date="25.09.2026",
        sides=[
            KadSide(name='ООО "РЕМИСТР"', role="respondent"),
            KadSide(name="ПАО Рога и Копыта", role="plaintiff"),
        ],
    )


def test_build_summary_text_contains_key_fields():
    text = build_summary_text([_case()], "2026-09-25")

    assert "за 2026-09-25" in text
    assert "Всего новых дел: 1" in text
    assert "А60-100/2026 [Г]" in text
    assert "АС Свердловской области" in text
    assert 'ООО "РЕМИСТР"' in text          # только ответчики
    assert "ПАО Рога и Копыта" not in text  # истец не попадает в сводку
    assert "https://kad.arbitr.ru/Card/guid-1" in text


def test_build_summary_text_multiple_cases():
    cases = [_case("guid-1", "А60-100/2026"), _case("guid-2", "А60-101/2026")]
    text = build_summary_text(cases, "2026-09-25")
    assert "Всего новых дел: 2" in text
    assert "А60-100/2026" in text and "А60-101/2026" in text


def test_build_summary_text_without_respondents():
    case = KadCase(
        guid="guid-3",
        case_number="А60-3/2026",
        sides=[KadSide(name="ООО Истец", role="plaintiff")],
    )
    text = build_summary_text([case], "2026-09-25")
    assert "Ответчики: —" in text


def test_write_summary_creates_file(tmp_path):
    path = write_summary([_case()], "2026-09-25", reports_dir=str(tmp_path))

    assert path == tmp_path / "kad_2026-09-25.md"
    assert path.exists()
    assert "А60-100/2026" in path.read_text(encoding="utf-8")


def test_write_summary_appends_within_day(tmp_path):
    write_summary([_case("guid-1", "А60-100/2026")], "2026-09-25", reports_dir=str(tmp_path))
    write_summary([_case("guid-2", "А60-101/2026")], "2026-09-25", reports_dir=str(tmp_path))

    content = (tmp_path / "kad_2026-09-25.md").read_text(encoding="utf-8")
    assert content.count("Всего новых дел: 1") == 2
    assert "А60-100/2026" in content and "А60-101/2026" in content


def test_write_summary_separate_files_per_day(tmp_path):
    write_summary([_case()], "2026-09-25", reports_dir=str(tmp_path))
    write_summary([_case()], "2026-09-26", reports_dir=str(tmp_path))

    assert (tmp_path / "kad_2026-09-25.md").exists()
    assert (tmp_path / "kad_2026-09-26.md").exists()
