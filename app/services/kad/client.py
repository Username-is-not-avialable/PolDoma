"""Клиент API КАД (kad.arbitr.ru) поверх живой Playwright-сессии.

Запросы уходят из живой страницы (fetch внутри браузера): это даёт браузерный
TLS-отпечаток и cookies сессии, прошедшей DDoS-Guard и pravocaptcha — обычный
httpx получает 403/451. Браузер запускается один раз и живёт, пока работает
процесс; все обращения идут через один фоновый поток (sync_playwright нельзя
дёргать из разных потоков).

Схема тела запроса восстановлена по JS фронтенда КАД (returnRequestInfo):
тип дела передаётся полем CaseType (G/A/B), участники — Sides с ролью.
Ответ приходит HTML-фрагментом — разбор в parser.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import random
import threading
import time
from concurrent.futures import Future
from typing import Any, AsyncIterator, Callable

from playwright.sync_api import sync_playwright

from app.config import settings
from app.services.kad.parser import Case, SearchPage, parse_search_page

# Поисковый эндпоинт один: тип дела — поле CaseType (G/A/B), не отдельный URL.
SEARCH_ENDPOINT = "/Kad/SearchInstances"

# Тип дела: принимаем и код КАД, и человекочитаемый алиас
CASE_TYPES: dict[str, str] = {
    "g": "G", "г": "G", "civil": "G", "гражданское": "G", "гражданские": "G",
    "a": "A", "а": "A", "administrative": "A", "admin": "A",
    "административное": "A", "административные": "A",
    "b": "B", "б": "B", "bankruptcy": "B", "банкротное": "B", "банкротные": "B",
}

# Роль участника — значения переключателя на сайте (#sug-participants)
SIDE_TYPES: dict[str, int] = {
    "any": -1, "любой": -1,
    "plaintiff": 0, "истец": 0,
    "respondent": 1, "ответчик": 1,
    "third": 2, "третье лицо": 2, "третье": 2,
    "other": 3, "иное лицо": 3, "иное": 3,
}

PAGE_LOAD_TIMEOUT_MS = 60_000
WAIT_AFTER_LOAD_S = 12        # запас на челлендж DDoS-Guard при открытии
REQUEST_TIMEOUT_MS = 60_000
PAUSE_BETWEEN_REQUESTS_S = 3.0  # пауза между страницами пагинации
REQUEST_ATTEMPTS = 3            # попыток на один запрос
BACKOFF_BASE_S = 5.0            # база экспоненциальной паузы между попытками


class KadBlocked(RuntimeError):
    """Сессия не признана (403)."""


class KadIpBlocked(RuntimeError):
    """DDoS-Guard ограничил доступ по IP (451) — слишком много запросов.

    Блок снимается со временем (часы/сутки) либо сменой IP; cookies и
    заголовки здесь не помогут. Контакты: support_kad@pravo.tech
    """


class KadErrorResponse(RuntimeError):
    """КАД вернул неожиданный HTTP-статус."""


class KadSessionLost(RuntimeError):
    """Браузерная сессия умерла (закрыта страница/браузер) — нужен перезапуск."""


def _default_headers() -> dict[str, str]:
    """Заголовки как у фронтенда КАД; куки добавляет сам контекст браузера."""
    return {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "x-date-format": "iso",
        "Origin": settings.kad_base_url,
        "Referer": settings.kad_base_url + "/",
        "X-Requested-With": "XMLHttpRequest",
    }


def case_type_code(case_type: str | None) -> str | None:
    """Алиас типа дела → код КАД (G/A/B)."""
    if not case_type:
        return None
    code = CASE_TYPES.get(str(case_type).strip().lower())
    if code is None:
        raise ValueError(
            f"Неизвестный тип дела: {case_type!r}. Допустимо: {sorted(set(CASE_TYPES))}"
        )
    return code


def side(
    name: str,
    role: str = "respondent",
    exact_match: bool = False,
) -> dict[str, Any]:
    """Участник дела для фильтра Sides (по умолчанию — ответчик).

    `name` — название организации/ИНН так, как их принимает поле поиска КАД.
    """
    role_key = str(role).strip().lower()
    if role_key not in SIDE_TYPES:
        raise ValueError(
            f"Неизвестная роль участника: {role!r}. Допустимо: {sorted(SIDE_TYPES)}"
        )
    return {
        "Name": name.strip(),
        "Type": SIDE_TYPES[role_key],
        "ExactMatch": bool(exact_match),
    }


def _normalize_date(value: str | None, *, end: bool) -> str | None:
    """Дата в формате фронтенда ('2026-09-21T00:00:00') или None."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if "T" in value:
        return value
    return f"{value}T{'23:59:59' if end else '00:00:00'}"


def build_search_body(
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    per_page: int = 25,
    courts: list[str] | None = None,
    case_type: str | None = None,
    sides: list[dict[str, Any]] | None = None,
    judges: list[dict[str, Any]] | None = None,
    case_numbers: list[str] | None = None,
    with_vks: bool = False,
) -> dict[str, Any]:
    """Тело поиска — как у фронтенда КАД (returnRequestInfo в kad.js).

    - `courts` — коды судов (см. app/services/kad/courts.py): ['EKATERINBURG']; 
    - `case_type` — 'G' (гражданские) / 'A' (административные) / 'B' (банкротные);
    - `sides` — участники, удобнее собирать через side(...);
    - пустые даты уходят как null.
    """
    return {
        "Page": page,
        "Count": per_page,
        "Courts": [c for c in (courts or []) if c],
        "DateFrom": _normalize_date(date_from, end=False),
        "DateTo": _normalize_date(date_to, end=True),
        "Sides": list(sides or []),
        "Judges": list(judges or []),
        "CaseNumbers": [n for n in (case_numbers or []) if n],
        "WithVKSInstances": bool(with_vks),
        **({"CaseType": code} if (code := case_type_code(case_type)) else {}),
    }


class _SearchResult:
    """Сырой ответ КАД: статус + текст (JSON или HTML — решает parser)."""

    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self.text = text


# Инициализация pravocaptcha в живой странице: грузим wasm-модуль КАД
# (wasm.js -> wasm.default(...) -> кука 'wasm'), затем fingerprint (fp.js).
# Кука 'wasm' обязательна для API: без неё КАД отвечает 451 (анти-бот).
_BOOTSTRAP_JS = """
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
    из-за чего API отвечает 451. Поэтому браузер запускается в оконном режиме
    (окно можно минимизировать); на сервере — Xvfb.
    """

    def __init__(self, headless: bool = False) -> None:
        if headless:
            logging.warning(
                "KAD: headless-режим не проходит pravocaptcha — API вернёт 451. "
                "Используйте headed-браузер или Xvfb "
                "(см. docs/получение-данных-с-кад.md)"
            )
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless,
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
        self._page.evaluate(
            "() => document.querySelectorAll('.b-promo_notification').forEach(e => e.remove())"
        )
        boot = self._page.evaluate(_BOOTSTRAP_JS)
        if not (isinstance(boot, dict) and boot.get("ok")):
            raise KadErrorResponse(
                f"Не удалось инициализировать pravocaptcha (кука 'wasm'): {boot}"
            )
        self._closed = False

    @property
    def alive(self) -> bool:
        """Сессия жива: браузер и страница не закрыты."""
        if self._closed:
            return False
        try:
            return not self._browser.is_closed() and not self._page.is_closed()
        except Exception:  # noqa: BLE001 — драйвер уже отвалился
            return False

    def request(self, endpoint: str, body: dict[str, Any]) -> _SearchResult:
        try:
            result = self._page.evaluate(
                _FETCH_JS,
                [settings.kad_base_url + endpoint, json.dumps(body, ensure_ascii=False)],
            )
        except Exception as exc:  # noqa: BLE001 — драйвер/страница отвалились
            self._closed = True
            raise KadSessionLost(f"Сессия браузера потеряна: {exc}") from exc
        return _SearchResult(result["status"], result["text"])

    def close(self) -> None:
        self._closed = True
        try:
            self._browser.close()
        except Exception:  # noqa: BLE001 — при закрытии ошибки не критичны
            pass
        finally:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass


class _PlaywrightWorker:
    """Единственный поток, владеющий Playwright и браузерной сессией.

    sync_playwright требует, чтобы все операции шли из потока, в котором создан
    объект; поэтому клиент складывает задачи в очередь, а воркер выполняет их
    у себя. Мёртвая сессия (закрытая страница/браузер) автоматически
    пересоздаётся — это и есть watchdog для долгоживущего сервиса.
    """

    def __init__(self) -> None:
        self._tasks: queue.Queue[tuple[Future, Callable[[_BrowserSession], Any]]] = queue.Queue()
        self._session: _BrowserSession | None = None
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="kad-playwright-worker"
        )
        self._thread.start()

    def _drop_session(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def _ensure_session(self) -> _BrowserSession:
        if self._session is None or not self._session.alive:
            self._drop_session()
            logging.info("KAD: поднимаю новую браузерную сессию")
            self._session = _BrowserSession(headless=settings.kad_browser_headless)
        return self._session

    def _loop(self) -> None:
        while True:
            future, fn = self._tasks.get()
            try:
                future.set_result(fn(self._ensure_session()))
            except BaseException as exc:  # noqa: BLE001 — отдаём любое исключение
                if isinstance(exc, KadSessionLost):
                    self._drop_session()  # следующая задача поднимет сессию заново
                future.set_exception(exc)
                future.exception()  # подавляем "Future exception was never retrieved"

    def submit(self, fn: Callable[[_BrowserSession], Any]) -> Any:
        future: Future = Future()
        self._tasks.put((future, fn))
        return future.result()

    def shutdown(self) -> None:
        try:
            future: Future = Future()
            self._tasks.put((future, lambda _s: self._drop_session()))
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


def _make_result(result: _SearchResult, endpoint: str) -> _SearchResult:
    """Проверка статуса ответа КАД."""
    if result.status == 403:
        raise KadBlocked("403 от КАД — сессия не признана (проверьте pravocaptcha).")
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
    return result


async def _post(
    endpoint: str,
    body: dict[str, Any],
    *,
    attempts: int = REQUEST_ATTEMPTS,
) -> _SearchResult:
    """POST через живую сессию с ретраями и экспоненциальным бэкоффом.

    Повторяем при обрыве сессии (watchdog пересоздаст браузер) и при 403/451
    (даём сайту «остыть»). Последняя ошибка пробрасывается наружу.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await asyncio.to_thread(
                _get_worker().submit, lambda s: s.request(endpoint, body)
            )
            return _make_result(result, endpoint)
        except (KadSessionLost, KadBlocked, KadIpBlocked, KadErrorResponse) as exc:
            last_exc = exc
            if attempt == attempts:
                break
            delay = BACKOFF_BASE_S * (2 ** (attempt - 1)) + random.uniform(0, 1.0)
            logging.warning(
                "KAD: попытка %s/%s не удалась (%s), пауза %.1f с",
                attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


async def search_page(
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    page: int = 1,
    per_page: int = 25,
    courts: list[str] | None = None,
    case_type: str | None = None,
    sides: list[dict[str, Any]] | None = None,
    judges: list[dict[str, Any]] | None = None,
    case_numbers: list[str] | None = None,
    with_vks: bool = False,
    endpoint: str = SEARCH_ENDPOINT,
) -> SearchPage:
    """Одна страница результатов поиска КАД (с пагинацией и моделью Case)."""
    body = build_search_body(
        date_from,
        date_to,
        page=page,
        per_page=per_page,
        courts=courts,
        case_type=case_type,
        sides=sides,
        judges=judges,
        case_numbers=case_numbers,
        with_vks=with_vks,
    )
    result = await _post(endpoint, body)
    return parse_search_page(result.text if not result.text.lstrip().startswith(("{", "[")) else result.json())


async def iter_cases(
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    courts: list[str] | None = None,
    case_type: str | None = None,
    sides: list[dict[str, Any]] | None = None,
    max_pages: int | None = None,
    pause_s: float = PAUSE_BETWEEN_REQUESTS_S,
) -> AsyncIterator[Case]:
    """Все дела по фильтру, страница за страницей (с паузами против лимитов)."""
    page_number = 1
    while True:
        result = await search_page(
            date_from,
            date_to,
            page=page_number,
            courts=courts,
            case_type=case_type,
            sides=sides,
        )
        for case in result.cases:
            yield case
        if not result.has_next or (max_pages is not None and page_number >= max_pages):
            return
        page_number += 1
        await asyncio.sleep(pause_s)


def shutdown_session() -> None:
    """Закрыть фоновый браузер (вызывать при завершении приложения)."""
    global _worker
    with _worker_lock:
        if _worker is not None:
            _worker.shutdown()
            _worker = None
