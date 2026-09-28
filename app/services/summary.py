"""Формирование краткой сводки о новых судебных делах и её запись в файл."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.services.kad.parser import Case as KadCase
from app.services.mailer import get_case_url

logger = logging.getLogger("summary")


def build_summary_text(new_cases: list[KadCase], target_date: str) -> str:
    """Краткая текстовая сводка о списке новых дел (для файла и письма)."""
    lines = [
        f"Сводка о новых судебных делах за {target_date}",
        f"Сформирована: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Всего новых дел: {len(new_cases)}",
        "",
    ]
    for i, case in enumerate(new_cases, start=1):
        respondents = "; ".join(
            s.name for s in case.sides if s.role == "respondent"
        ) or "—"
        lines.extend(
            [
                f"{i}. {case.case_number}"
                + (f" [{case.case_type}]" if case.case_type else ""),
                f"   Суд: {case.court or '—'}",
                f"   Судья: {case.judge or '—'}",
                f"   Ответчики: {respondents}",
                f"   Ссылка: {get_case_url(case.guid)}",
                "",
            ]
        )
    return "\n".join(lines)


def write_summary(
    new_cases: list[KadCase],
    target_date: str,
    reports_dir: str | None = None,
) -> Path:
    """Дописывает сводку в дневной файл `kad_<дата>.md`, возвращает путь.

    Файл открывается в режиме append: несколько циклов за день
    накапливаются в одном файле по порядку.
    """
    directory = Path(reports_dir or settings.summary_reports_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"kad_{target_date}.md"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(build_summary_text(new_cases, target_date))
        fh.write("\n")
    logger.info("Сводка о %s новых делах записана в %s", len(new_cases), path)
    return path
