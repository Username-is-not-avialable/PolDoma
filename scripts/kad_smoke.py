"""Smoke-тест клиента КАД: один поиск через живую браузерную сессию."""
import asyncio
import re

from app.services.kad.client import search, shutdown_session


async def main() -> None:
    try:
        result = await search("2026-09-21", "2026-09-24", courts=["EKATERINBURG"])
    finally:
        shutdown_session()
    if isinstance(result, str):
        nums = re.findall(r'class="num_case">\s*([^<]+?)\s*<', result)
        total = re.search(r'id="documentsTotalCount" value="(\d+)"', result)
        print(f"HTTP OK, HTML len={len(result)}, дел на странице={len(nums)}, "
              f"всего={total.group(1) if total else '?'}")
        print("Примеры:", nums[:5])
    else:
        print("HTTP OK, JSON:", result)


asyncio.run(main())
