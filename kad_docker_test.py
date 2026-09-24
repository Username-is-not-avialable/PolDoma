"""Тестовый запрос в КАД из docker-контейнера с xvfb (эмуляция дисплея)."""
import asyncio
from app.services.kad.client import search, shutdown_session

async def main():
    try:
        result = await search("2026-09-21", "2026-09-24", courts=["EKATERINBURG"])
    finally:
        shutdown_session()
    if isinstance(result, str):
        print("HTTP OK, ответ HTML, длина:", len(result))
        print("Фрагмент:", result[:300])
    else:
        print("HTTP OK, ответ JSON, ключи:", list(result)[:10])

asyncio.run(main())
