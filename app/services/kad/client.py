"""Клиент API КАД (kad.arbitr.ru) поверх живой Playwright-сессии.

Запросы шлём через контекст реального браузера (context.request): это даёт
браузерный TLS-отпечаток и cookies сессии, прошедшей DDoS-Guard — обычный
httpx блокируется (403/451). Браузер запускается один раз и живёт, пока
работает процесс; все обращения к нему идут через один фоновый поток
(sync_playwright нельзя дёргать из разных потоков).

Структура тела запроса повторяет фронтенд КАД (см. kad.arbitr.ru.har):
POST /Kad/SearchInstances и др. Ответ приходит HTML-фрагментом (content-type
text/html) — разбор в parser.py.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable

from playwright.sync_api import sync_playwright

from app.config import settings

# Типы дел → эндпоинт поиска
SEARCH_ENDPOINTS: dict[str, str] = {
    "civil": "/Kad/SearchInstances",      # гражданские (исковые)
    "admin": "/Kad/SearchAdmin",          # административные
    "bankruptcy": "/Kad/SearchBankruptcy",  # банкротные
}

PAGE_LOAD_TIMEOUT_MS = 60_000
WAIT_AFTER_LOAD_S = 12  # запас на челлендж DDoS-Guard при первом открытии
REQUEST_TIMEOUT_MS = 60_000


class KadCookiesMissing(RuntimeError):
    """Cookies не найдены — сначала запустите cookie_fetcher."""


class KadBlocked(RuntimeError):
    """КАД/DDoS-Guard отверг запрос (403) — обновите cookies."""


class KadIpBlocked(RuntimeError):
    """DDoS-Guard ограничил доступ по IP (451) — слишком много запросов.

    Блок снимается со временем (часы/сутки) либо сменой IP; cookies и
    заголовки здесь не помогут. Контакты: support_kad@pravo.tech
    """


class KadErrorResponse(RuntimeError):
    """КАД вернул неожиданный HTTP-статус."""


def _default_headers() -> dict[str, str]:
    """Заголовки как у фронтенда КАД (см. HAR); куки добавит контекст."""
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "x-date-format": "iso",
        "Origin": settings.kad_base_url,
        "Referer": settings.kad_base_url + "/",
        "X-Requested-With": "XMLHttpRequest",
    }


def _normalize_date(value: str, *, end: bool) -> str:
    """Приводит дату к формату фронтенда: '2026-09-21T00:00:00' / '...T23:59:59'."""
    value = value.strip()
    if "T" in value:
        return value
    return f"{value}T{'23:59:59' if end else '00:00:00'}"


def build_search_body(
    date_from: str,
    date_to: str,
    page: int = 1,
    per_page: int = 25,
    courts: list[str] | None = None,
) -> dict[str, Any]:
    """Тело поиска — 1:1 как у фронтенда КАД (по kad.arbitr.ru.har)."""
    return {
        "Page": page,
        "Count": per_page,
        "Courts": courts or [],
        "DateFrom": _normalize_date(date_from, end=False),
        "DateTo": _normalize_date(date_to, end=True),
        "Sides": [],          # [{"Name": ..., "Type": 1 (ответчик), ...}]
        "Judges": [],
        "CaseNumbers": [],
        "WithVKSInstances": False,
    }


class _SearchResult:
    """Сырой ответ КАД: статус + текст (JSON или HTML — решает parser)."""

    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self.text = text

    def json(self) -> Any:
        return json.loads(self.text)


# Инициализация pravocaptcha в живой странице: грузим wasm-модуль КАД
# (wasm.js -> wasm.default(...) -> кука 'wasm'), затем fingerprint (fp.js).
# Кука 'wasm' обязательна для API: без неё КАД отвечает 451 (анти-бот).
_PRavo_BOOTSTRAP_JS = """
async () => {
    const load = async (u) => { const r = await fetch(u); (0, eval)(await r.text()); };
    if (typeof window.wasm === 'undefined') {
        await load('/Wasm/api/v1/wasm.js?_=' + Date.now());
        await window.wasm['default']('/Wasm/api/v1/wasm_bg.wasm?_=' + Date.now());
    }
    if (typeof window.fp === 'undefined') {
        await load('/Content/Static/js/common/fp.js?_=1705670688006');
        await window.fp.default('/Content/Static/js/common/fp_bg.wasm?_=1705670688006');
        await window.fp.get();
    }
    // ждём установки куки wasm (ставит сам WASM-модуль)
    for (let i = 0; i < 20; i++) {
        if (document.cookie.includes('wasm=')) return {ok: true};
        await new Promise(r => setTimeout(r, 1000));
    }
    return {ok: false, note: 'wasm cookie not set'};
}
"""

_FETCH_JS = """
async ([url, body]) => {
    const r = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json', 'x-date-format': 'iso',
                  'X-Requested-With': 'XMLHttpRequest'},
        body: body
    });
    return {status: r.status, text: await r.text()};
}
"""


class _BrowserSession:
    """Живой headed-браузер со страницей КАД, прошедшей DDoS-Guard + pravocaptcha.

    Важно: headless не работает — WASM-модуль pravocaptcha в headless
    Chromium падает (RuntimeError: unreachable) и кука 'wasm' не ставится,
    из-за чего API отвечает 451. Поэтому браузер запускается в оконном
    режиме (окно можно минимизировать).
    """

    def __init__(self, headless: bool = False) -> None:
        # headless игнорируется (см. docstring); параметр оставлен для совместимости.
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            viewport={"width": 1600, "height": 900},
            locale="ru-RU",
            timezone_id="Asia/Yekaterinburg",
            color_scheme="light",
        )
        self._page = self._context.new_page()
        self._page.goto(
            settings.kad_base_url,
            timeout=PAGE_LOAD_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )
        time.sleep(WAIT_AFTER_LOAD_S)
        # убрать промо-попапы, перехватывающие события (не влияет на API)
        self._page.evaluate(
            "() => document.querySelectorAll('.b-promo_notification').forEach(e => e.remove())"
        )
        boot = self._page.evaluate(_PRavo_BOOTSTRAP_JS)
        if not (isinstance(boot, dict) and boot.get("ok")):
            raise KadErrorResponse(
                f"Не удалось инициализировать pravocaptcha (кука 'wasm'): {boot}"
            )

    def request(self, endpoint: str, body: dict[str, Any]) -> _SearchResult:
        result = self._page.evaluate(
            _FETCH_JS,
            [settings.kad_base_url + endpoint, json.dumps(body, ensure_ascii=False)],
        )
        return _SearchResult(result["status"], result["text"])

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()


class _PlaywrightWorker:
    """Единственный поток, владеющий Playwright и браузерной сессией.

    sync_playwright требует, чтобы все операции шли из потока, в котором
    создан его объект; поэтому клиент складывает задачи в очередь, а воркер
    выполняет их у себя.
    """

    def __init__(self) -> None:
        self._tasks: queue.Queue[tuple[Future, Callable[[_BrowserSession], Any]]] = queue.Queue()
        self._session: _BrowserSession | None = None
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="kad-playwright-worker"
        )
        self._thread.start()

    def _ensure_session(self) -> _BrowserSession:
        if self._session is None or self._session._browser.is_closed():
            self._session = _BrowserSession(headless=settings.kad_cookie_headless)
        return self._session

    def _loop(self) -> None:
        while True:
            future, fn = self._tasks.get()
            try:
                future.set_result(fn(self._ensure_session()))
            except BaseException as exc:  # noqa: BLE001 — отдаём любое исключение
                future.set_exception(exc)
                future.exception()  # подавляем "Future exception was never retrieved"

    def submit(self, fn: Callable[[_BrowserSession], Any]) -> Any:
        future: Future = Future()
        self._tasks.put((future, fn))
        return future.result()

    def shutdown(self) -> None:
        def _close(_s: _BrowserSession | None) -> None:
            if self._session is not None:
                self._session.close()
                self._session = None

        try:
            future: Future = Future()
            self._tasks.put((future, _close))
            future.result(timeout=30)
        except Exception:  # noqa: BLE001 — при закрытии ошибки не критичны
            pass


_worker: _PlaywrightWorker | None = None
_worker_lock = threading.Lock()


def _get_worker() -> _PlaywrightWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = _PlaywrightWorker()
        return _worker


async def search(
    date_from: str,
    date_to: str,
    endpoint: str = SEARCH_ENDPOINTS["civil"],
    page: int = 1,
    per_page: int = 25,
    courts: list[str] | None = None,
) -> dict[str, Any] | str:
    """POST к эндпоинту поиска через живую браузерную сессию.

    Возвращает сырой ответ: dict (JSON) или str (HTML-фрагмент) — см. parser.
    """
    body = build_search_body(date_from, date_to, page=page, per_page=per_page, courts=courts)

    def _do(session: _BrowserSession) -> _SearchResult:
        return session.request(endpoint, body)

    result: _SearchResult = await asyncio.to_thread(_get_worker().submit, _do)
    if result.status == 403:
        raise KadBlocked("403 от КАД — обновите cookies (cookie_fetcher).")
    if result.status == 451:
        raise KadIpBlocked(
            "451 от КАД — доступ с вашего IP ограничен DDoS-Guard "
            "(слишком много запросов). Подождите или смените IP; "
            "cookies/заголовки не помогут. Контакты: support_kad@pravo.tech"
        )
    if result.status != 200:
        raise KadErrorResponse(
            f"Неожиданный статус {result.status} от {endpoint}: {result.text[:300]}"
        )

    if result.text.lstrip().startswith(("{", "[")):
        return result.json()
    return result.text


def shutdown_session() -> None:
    """Закрыть фоновый браузер (вызывать при завершении приложения)."""
    global _worker
    with _worker_lock:
        if _worker is not None:
            _worker.shutdown()
            _worker = None
