"""Тесты клиента КАД: тело запроса, пагинация, ретраи (без сети)."""

from __future__ import annotations

import pytest

from app.services.kad import client as kad
from app.services.kad.parser import Case, SearchPage


# ---------------------------- тело запроса ----------------------------


def test_build_search_body_case_type_and_sides():
    body = kad.build_search_body(
        "2026-09-21",
        "2026-09-24",
        courts=["EKATERINBURG"],
        case_type="civil",
        sides=[kad.side("ООО Ромашка", "ответчик", exact_match=True)],
    )
    assert body["CaseType"] == "G"
    assert body["Sides"] == [{"Name": "ООО Ромашка", "Type": 1, "ExactMatch": True}]
    assert body["Courts"] == ["EKATERINBURG"]


@pytest.mark.parametrize(
    ("alias", "code"),
    [("civil", "G"), ("administrative", "A"), ("bankruptcy", "B"), ("g", "G"), ("А", "A")],
)
def test_case_type_aliases(alias, code):
    assert kad.case_type_code(alias) == code


def test_unknown_case_type_raises():
    with pytest.raises(ValueError):
        kad.case_type_code("уголовное")


def test_unknown_side_role_raises():
    with pytest.raises(ValueError):
        kad.side("ООО Ромашка", "судья")


def test_empty_dates_become_null():
    body = kad.build_search_body(None, None)
    assert body["DateFrom"] is None
    assert body["DateTo"] is None
    assert "CaseType" not in body


def test_side_role_codes_match_site():
    assert kad.SIDE_TYPES["respondent"] == 1
    assert kad.SIDE_TYPES["plaintiff"] == 0
    assert kad.SIDE_TYPES["any"] == -1


# ---------------------------- пагинация ----------------------------


def test_has_next_flag():
    assert SearchPage(page=1, pages=3).has_next is True
    assert SearchPage(page=3, pages=3).has_next is False
    assert SearchPage(page=1, pages=None).has_next is False


def _case(number: str) -> Case:
    return Case(guid=f"guid-{number}", case_number=number)


async def test_iter_cases_walks_pages(monkeypatch):
    pages = {
        1: SearchPage(cases=[_case("c1"), _case("c2")], page=1, pages=3),
        2: SearchPage(cases=[_case("c3")], page=2, pages=3),
        3: SearchPage(cases=[], page=3, pages=3),
    }
    calls = []

    async def fake_search_page(*args, **kwargs):
        calls.append(kwargs["page"])
        return pages[kwargs["page"]]

    monkeypatch.setattr(kad, "search_page", fake_search_page)
    collected = [c async for c in kad.iter_cases("2026-09-21", "2026-09-24", pause_s=0)]
    assert [c.case_number for c in collected] == ["c1", "c2", "c3"]
    assert calls == [1, 2, 3]


async def test_iter_cases_respects_max_pages(monkeypatch):
    async def fake_search_page(*args, **kwargs):
        page = kwargs["page"]
        return SearchPage(cases=[_case(f"p{page}")], page=page, pages=10)

    monkeypatch.setattr(kad, "search_page", fake_search_page)
    collected = [
        c async for c in kad.iter_cases("2026-09-21", "2026-09-24", max_pages=2, pause_s=0)
    ]
    assert [c.case_number for c in collected] == ["p1", "p2"]


# ---------------------------- ретраи ----------------------------


class _FakeWorker:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def submit(self, fn):
        self.calls += 1
        if self.calls <= self.failures:
            raise kad.KadIpBlocked("451")
        return kad._SearchResult(200, "<html></html>")


async def test_post_retries_on_451(monkeypatch):
    worker = _FakeWorker(failures=2)
    monkeypatch.setattr(kad, "_get_worker", lambda: worker)
    monkeypatch.setattr(kad, "BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(kad, "REQUEST_ATTEMPTS", 3)
    result = await kad._post("/Kad/SearchInstances", {}, attempts=3)
    assert result.status == 200
    assert worker.calls == 3


async def test_post_raises_after_all_attempts(monkeypatch):
    worker = _FakeWorker(failures=99)
    monkeypatch.setattr(kad, "_get_worker", lambda: worker)
    monkeypatch.setattr(kad, "BACKOFF_BASE_S", 0.0)
    with pytest.raises(kad.KadIpBlocked):
        await kad._post("/Kad/SearchInstances", {}, attempts=2)
    assert worker.calls == 2


async def test_post_recreates_session_after_loss(monkeypatch):
    class _LostWorker:
        def __init__(self):
            self.calls = 0

        def submit(self, fn):
            self.calls += 1
            if self.calls == 1:
                raise kad.KadSessionLost("драйвер отвалился")
            return kad._SearchResult(200, "<html></html>")

    worker = _LostWorker()
    monkeypatch.setattr(kad, "_get_worker", lambda: worker)
    monkeypatch.setattr(kad, "BACKOFF_BASE_S", 0.0)
    result = await kad._post("/Kad/SearchInstances", {}, attempts=2)
    assert result.status == 200
    assert worker.calls == 2
