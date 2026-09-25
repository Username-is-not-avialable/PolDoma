"""Smoke-тест клиента КАД: один поиск через живую браузерную сессию.

Запуск:
    python scripts/kad_smoke.py            # поиск + разбор + краткий отчёт
    python scripts/kad_smoke.py --dump     # + сохранить сырой HTML в /tmp/kad_last.html
"""
import asyncio
import sys
from pathlib import Path

from app.services.kad.parser import parse_response
from app.services.kad.client import search, shutdown_session


async def main() -> None:
    try:
        result = await search("2026-09-21", "2026-09-24", courts=["EKATERINBURG"])
    finally:
        shutdown_session()

    if not isinstance(result, str):
        print("HTTP OK, JSON:", result)
        return

    if "--dump" in sys.argv:
        dump = Path("/tmp/kad_last.html")
        dump.write_text(result, encoding="utf-8")
        print(f"Сырой HTML сохранён: {dump} ({len(result)} байт)")

    cases = parse_response(result)
    print(f"HTTP OK, HTML {len(result)} байт, разобрано дел: {len(cases)}")
    for case in cases[:5]:
        parties = ", ".join(p.name for p in case.parties[:2])
        print(f"  {case.case_number} [{case.case_type}] {case.court} "
              f"судья={case.judge} | {parties}")


asyncio.run(main())
