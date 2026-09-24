"""Нормализация сырого JSON-ответа КАД в модель Case.

Структура ответа уточняется после первого живого запроса — сначала пробуем
известные по open-source парсерам варианты ключей (Items / Records / Cases).
"""

from __future__ import annotations

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


def parse_response(payload: dict[str, Any]) -> list[Case]:
    return [parse_case(rec) for rec in extract_records(payload)]
