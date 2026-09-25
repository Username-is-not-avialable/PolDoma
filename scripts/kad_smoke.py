"""Smoke-тест клиента КАД: один поиск через живую браузерную сессию.

Запуск:
    python scripts/kad_smoke.py            # поиск + разбор + краткий отчёт
    python scripts/kad_smoke.py --dump     # + сохранить сырой HTML в /tmp/kad_last.html
    python scripts/kad_smoke.py --pages 2  # пройти первую пагинацию (2 страницы)
"""
import asyncio
import sys
from pathlib import Path

from app.services.kad.client import iter_cases, search_page, shutdown_session
from app.services.kad.courts import require_code

DUMP_PATH = Path("/tmp/kad_last.html")


async def main() -> None:
    court = require_code("АС Свердловской области")
    max_pages = None
    if "--pages" in sys.argv:
        max_pages = int(sys.argv[sys.argv.index("--pages") + 1])
    try:
        if max_pages is None:
            result = await search_page("2026-09-21", "2026-09-24", courts=[court])
            if result.raw is not None and "--dump" in sys.argv:
                DUMP_PATH.write_text(result.raw, encoding="utf-8")
                print(f"Сырой HTML сохранён: {DUMP_PATH} ({len(result.raw)} байт)")
            print(f"HTTP OK: дел на странице={len(result.cases)}, "
                  f"всего={result.total}, страниц={result.pages}")
            for case in result.cases[:5]:
                parties = ", ".join(p.name for p in case.parties[:2])
                print(f"  {case.case_number} [{case.case_type}] {case.court} "
                      f"судья={case.judge} | {parties}")
        else:
            count = 0
            async for case in iter_cases(
                "2026-09-21", "2026-09-24", courts=[court], max_pages=max_pages
            ):
                count += 1
                if count <= 3:
                    print(f"  {case.case_number} [{case.case_type}] {case.court}")
            print(f"HTTP OK: собрано дел за {max_pages} стр.: {count}")
    finally:
        shutdown_session()


asyncio.run(main())
