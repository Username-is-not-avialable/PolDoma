"""Нормализация ответа КАД в модель Case.

Живой API КАД возвращает HTML-фрагмент таблицы результатов (см.
kad.arbitr.ru.har) — его разбирает parse_html_cases. JSON-ветка
(Items / Records / Cases) оставлена на случай API-режима.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


class Party(BaseModel):
    name: str
    inn: str | None = None
    address: str | None = None
    role: str  # "plaintiff" | "respondent" | "other"


class Case(BaseModel):
    guid: str
    case_number: str
    case_type: str | None = None          # И/А/Б
    court: str | None = None
    judge: str | None = None
    start_date: str | None = None
    parties: list[Party] = Field(default_factory=list)


def extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Достаёт список дел из ответа, поддерживая варианты ключей."""
    for key in ("Items", "Records", "Cases", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    raise ValueError(
        f"Не найден список дел в ответе. Ключи верхнего уровня: {list(payload)}"
    )


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def parse_party(raw: dict[str, Any], role: str) -> Party:
    return Party(
        name=str(raw.get("Name") or raw.get("name") or ""),
        inn=str(raw["Inn"]) if raw.get("Inn") else None,
        address=raw.get("Address"),
        role=role,
    )


def parse_case(raw: dict[str, Any]) -> Case:
    sides = raw.get("Sides") or raw.get("CaseSide") or []
    parties: list[Party] = []
    if isinstance(sides, dict):
        sides = sides.get("Items", [])
    for side in sides:
        side_type = (side.get("SideType") or side.get("Type") or side.get("Role") or "").lower()
        if "ист" in side_type or "plaintiff" in side_type:
            role = "plaintiff"
        elif "ответч" in side_type or "respondent" in side_type:
            role = "respondent"
        else:
            role = "other"
        parties.append(parse_party(side, role))

    judge = _first(raw.get("Judges") or raw.get("Judge"))

    return Case(
        guid=str(raw.get("Id") or raw.get("Guid") or ""),
        case_number=str(raw.get("N") or raw.get("CaseNumber") or raw.get("Number") or ""),
        case_type=raw.get("CaseType"),
        court=(raw.get("Court") or {}).get("Name")
        if isinstance(raw.get("Court"), dict)
        else raw.get("Court"),
        judge=str(judge) if judge else None,
        start_date=raw.get("Date") or raw.get("StartDate"),
        parties=parties,
    )


def parse_response(payload: dict[str, Any] | str) -> list[Case]:
    """Разбор ответа КАД: dict (JSON) -> JSON-парсер, str (HTML) -> HTML-парсер."""
    if isinstance(payload, str):
        return parse_html_cases(payload)
    return [parse_case(rec) for rec in extract_records(payload)]


# ------------------------- HTML-ответ КАД -------------------------
# API КАД возвращает HTML-фрагмент таблицы результатов (content-type:
# text/html). Структура строки (см. kad.arbitr.ru.har):
#
#   <tr>
#     <td class="num">    div (civil|administrative|bankruptcy|default,
#                          title="дата") + a.num_case href=".../Card/<guid>"
#     <td class="court">  div.judge (не всегда) + div[title] (название суда)
#     <td class="plaintiff"> span.js-rollover: имя в <strong>, ниже адрес,
#     <td class="respondent"> <div> с ИНН / датой рождения; сторон может быть
#                          несколько (лишние в div.more)
#   </tr>

_TYPE_BY_CLASS = {
    "civil": "И",           # гражданское (исковое)
    "administrative": "А",   # административное
    "bankruptcy": "Б",      # банкротное
}

_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """Схлопывает пробелы/переводы строк (в т.ч. вокруг HTML-сущностей)."""
    return _WS_RE.sub(" ", text.replace("\xa0", " ")).strip()


def _node_text(node) -> str:
    """Текст узла одним пробелом между фрагментами (html.parser рвёт текст
    на сущностях вроде &quot; — поэтому склеиваем через пробел)."""
    return _clean(node.get_text(" "))


def _parse_party(span, role: str) -> Party | None:
    """Сторона из span.js-rollover: strong — имя, текст — адрес, div — реквизиты."""
    from bs4 import NavigableString

    details = span.select_one("span.js-rolloverHtml") or span
    name = ""
    address_parts: list[str] = []
    inn = None
    for child in details.children:
        if isinstance(child, NavigableString):
            if child.strip():
                address_parts.append(str(child))
            continue
        if child.name == "strong":
            name = _node_text(child)
        elif child.name == "div":
            text = _node_text(child)
            if text.startswith("ИНН:"):
                inn = text.removeprefix("ИНН:").strip()
            elif not text.startswith(("Дата рождения:", "Место рождения:")):
                address_parts.append(text)
    if not name:
        return None
    address = _clean(" ".join(address_parts)) or None
    return Party(name=name, inn=inn, address=address, role=role)


def _parse_party_cell(cell, role: str) -> list[Party]:
    """Все стороны из ячейки plaintiff/respondent."""
    parties: list[Party] = []
    for span in cell.select("span.js-rollover"):
        party = _parse_party(span, role)
        if party is not None:
            parties.append(party)
    return parties


def parse_html_cases(html: str) -> list[Case]:
    """Разбор HTML-фрагмента с результатами поиска КАД в модели Case."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    cases: list[Case] = []
    for row in soup.select("tr"):
        num_cell = row.select_one("td.num")
        link = row.select_one("a.num_case")
        if num_cell is None or link is None:
            continue

        case_number = _node_text(link)
        href = link.get("href", "")
        guid = href.rsplit("/Card/", 1)[1].strip("/ ") if "/Card/" in href else ""

        type_div = num_cell.select_one(
            "div.civil, div.administrative, div.bankruptcy, div.default"
        )
        case_type = None
        start_date = None
        if type_div is not None:
            classes = type_div.get("class") or []
            case_type = _TYPE_BY_CLASS.get(classes[0]) if classes else None
            start_date = _clean(type_div.get("title", "")) or None

        court_cell = row.select_one("td.court")
        judge = None
        court = None
        if court_cell is not None:
            judge_div = court_cell.select_one("div.judge")
            if judge_div is not None:
                judge = _clean(judge_div.get("title", "")) or _node_text(judge_div)
            # название суда — div с атрибутом title (кроме div.judge)
            court_div = next(
                (
                    div
                    for div in court_cell.find_all("div")
                    if "judge" not in (div.get("class") or []) and div.get("title")
                ),
                None,
            )
            if court_div is not None:
                court = _clean(court_div.get("title", "")) or _node_text(court_div)

        parties: list[Party] = []
        for role, selector in (
            ("plaintiff", "td.plaintiff"),
            ("respondent", "td.respondent"),
        ):
            cell = row.select_one(selector)
            if cell is not None:
                parties.extend(_parse_party_cell(cell, role))

        cases.append(
            Case(
                guid=guid,
                case_number=case_number,
                case_type=case_type,
                court=court,
                judge=judge,
                start_date=start_date,
                parties=parties,
            )
        )
    return cases


# ------------------------- Страница результатов -------------------------


class SearchPage(BaseModel):
    """Одна страница результатов поиска КАД.

    `total`/`pages` КАД отдаёт в скрытых input'ах ответа
    (documentsTotalCount / documentsPagesCount); для JSON-режима — None.
    """

    cases: list[Case] = Field(default_factory=list)
    page: int = 1
    page_size: int = 25
    total: int | None = None
    pages: int | None = None
    raw: str | None = None      # сырой HTML-фрагмент (для диагностики/--dump)

    @property
    def has_next(self) -> bool:
        """Есть ли следующая страница."""
        if self.pages is None:
            return False
        return self.page < self.pages


def _hidden_int(soup, element_id: str) -> int | None:
    tag = soup.find("input", id=element_id)
    if tag is None:
        return None
    try:
        return int(tag.get("value", ""))
    except (TypeError, ValueError):
        return None


def parse_search_page(payload: dict[str, Any] | str) -> SearchPage:
    """Разбор ответа поиска: HTML-страница с пагинацией или JSON-список дел."""
    if not isinstance(payload, str):
        return SearchPage(cases=parse_response(payload))

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(payload, "html.parser")
    return SearchPage(
        cases=parse_html_cases(payload),
        page=_hidden_int(soup, "documentsPage") or 1,
        page_size=_hidden_int(soup, "documentsPageSize") or 25,
        total=_hidden_int(soup, "documentsTotalCount"),
        pages=_hidden_int(soup, "documentsPagesCount"),
        raw=payload,
    )
