"""Получение и сохранение cookies kad.arbitr.ru через Playwright.

Обход Cloudflare: запускаем реальный браузер, он сам проходит JS-челлендж.
Сохраняем cookies + User-Agent в JSON-файл для использования в client.py.

Запуск:
    python -m app.services.kad.cookie_fetcher            # headless (по .env)
    python -m app.services.kad.cookie_fetcher --visible  # видно окно (капча руками)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.config import settings

KAD_PAGE_TIMEOUT_MS = 60_000
WAIT_AFTER_LOAD_S = 15  # запас на прохождение JS-челленджа Cloudflare


def fetch_cookies(base_url: str, headless: bool = True) -> dict:
    """Открывает КАД в браузере и возвращает {'cookies': [...], 'user_agent': '...'}."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(base_url, timeout=KAD_PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        # Даём Cloudflare время на автоматический челлендж; при капче пользователь
        # решает её в видимом окне (--visible).
        time.sleep(WAIT_AFTER_LOAD_S)
        result = {
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "user_agent": page.evaluate("navigator.userAgent"),
            "cookies": context.cookies(base_url),
        }
        browser.close()
    return result


def save_cookies(data: dict, path: str | None = None) -> Path:
    target = Path(path or settings.kad_cookie_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> None:
    headless = settings.kad_cookie_headless and "--visible" not in sys.argv
    print(f"Открываю {settings.kad_base_url} (headless={headless})...")
    data = fetch_cookies(settings.kad_base_url, headless=headless)
    path = save_cookies(data)
    print(f"Сохранено {len(data['cookies'])} cookies → {path}")


if __name__ == "__main__":
    main()
