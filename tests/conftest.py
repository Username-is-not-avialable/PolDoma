"""Общие фикстуры тестов.

Защита от реальных писем. В `.env` проекта могут быть заданы боевые
`SUMMARY_EMAIL_TO`, `SMTP_USER` и `SMTP_PASSWORD`, а тесты цикла мониторинга
(`app.services.monitor.run_monitoring_cycle`) подменяют только KAD-клиент и
`send_case_notification`, но не `send_summary_email`. Из-за этого прогон тестов
отправлял настоящие письма-дайджесты на боевой адрес.

Autouse-фикстура ниже закрывает обе точки утечки:

1. обнуляет `settings.summary_email_to` — цикл не формирует дайджест;
2. подменяет `aiosmtplib.SMTP` на заглушку, которая падает при попытке любой
   реальной отправки (страховка для новых тестов).
"""

from __future__ import annotations

from typing import Any

import aiosmtplib
import pytest

from app.config import settings


class _SMTPForbidden:
    """Заглушка `aiosmtplib.SMTP`, запрещающая реальные SMTP-подключения."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "Тест попытался отправить реальное письмо через SMTP. "
            "Замокайте aiosmtplib.SMTP (или соответствующие настройки) в тесте."
        )


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """Изолирует тесты от боевой почты (см. docstring модуля)."""
    monkeypatch.setattr(settings, "summary_email_to", "")
    monkeypatch.setattr(aiosmtplib, "SMTP", _SMTPForbidden)
