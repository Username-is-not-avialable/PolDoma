"""Smoke-тест клиента КАД: один поиск через живую браузерную сессию."""
import asyncio

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

    cases = parse_response(result)
    print(f"HTTP OK, HTML {len(result)} байт, разобрано дел: {len(cases)}")
    for case in cases[:5]:
        parties = ", ".join(p.name for p in case.parties[:2])
        print(f"  {case.case_number} [{case.case_type}] {case.court} "
              f"судья={case.judge} | {parties}")


asyncio.run(main())
