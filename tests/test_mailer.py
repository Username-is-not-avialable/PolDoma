"""Тесты для сервиса формирования и отправки email (app.services.mailer)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import aiosmtplib
import pytest

from app.config import settings
from app.models.case import Case as OrmCase
from app.services.kad.parser import Case as KadCase
from app.services.mailer import (
    build_case_notification_message,
    get_case_url,
    send_case_notification,
    send_message,
    send_summary_email,
)


def test_get_case_url():
    guid = "0a56fe8a-9e32-4759-9943-42e126ab56a3"
    url = get_case_url(guid)
    assert url == f"https://kad.arbitr.ru/Card/{guid}"


def test_build_case_notification_message_with_recipient_name():
    case = KadCase(
        guid="1111-2222-3333",
        case_number="А60-59233/2026",
    )
    with patch.object(settings, "smtp_from_email", "sender@test.ru"), patch.object(
        settings, "smtp_from_name", "ПолдОма"
    ):
        msg = build_case_notification_message(
            to_email="client@example.com",
            case=case,
            recipient_name='ООО "РЕМИСТР"',
        )

    assert msg["To"] == "client@example.com"
    assert msg["Subject"] == "Уведомление о судебном деле А60-59233/2026"
    assert "ПолдОма" in msg["From"]
    assert "sender@test.ru" in msg["From"]

    body = msg.get_content()
    expected_text = (
        'ООО "РЕМИСТР", на вас подали в суд. Ссылка на дело: https://kad.arbitr.ru/Card/1111-2222-3333\n'
    )
    assert body == expected_text


def test_build_case_notification_message_without_recipient_name():
    case = KadCase(
        guid="aaaa-bbbb-cccc",
        case_number="А40-12345/2026",
    )
    with patch.object(settings, "smtp_from_email", "sender@test.ru"), patch.object(
        settings, "smtp_from_name", ""
    ):
        msg = build_case_notification_message(
            to_email="someone@example.com",
            case=case,
            recipient_name=None,
        )

    assert msg["To"] == "someone@example.com"
    body = msg.get_content()
    assert (
        body
        == "На вас подали в суд. Ссылка на дело: https://kad.arbitr.ru/Card/aaaa-bbbb-cccc\n"
    )


def test_build_case_notification_message_with_orm_case():
    orm_case = OrmCase(
        guid="orm-guid-999",
        case_number="А60-777/2026",
    )
    with patch.object(settings, "smtp_from_email", "sender@test.ru"):
        msg = build_case_notification_message(
            to_email="test@test.ru",
            case=orm_case,
            recipient_name="Иванов И.И.",
        )
    body = msg.get_content()
    assert "Иванов И.И., на вас подали в суд." in body
    assert "https://kad.arbitr.ru/Card/orm-guid-999" in body


async def test_send_message_success():
    case = KadCase(guid="guid-test", case_number="А60-1/2026")
    msg = build_case_notification_message("target@test.ru", case)

    mock_smtp_instance = AsyncMock()
    mock_smtp_instance.__aenter__.return_value = mock_smtp_instance
    mock_smtp_instance.login = AsyncMock()
    mock_smtp_instance.send_message = AsyncMock(return_value="250 Message accepted")

    with patch("aiosmtplib.SMTP", return_value=mock_smtp_instance), patch.object(
        settings, "smtp_user", "user@test.ru"
    ), patch.object(settings, "smtp_password", "secret"):
        res = await send_message(msg)

    assert res["status"] == "sent"
    mock_smtp_instance.login.assert_awaited_once_with("user@test.ru", "secret")
    mock_smtp_instance.send_message.assert_awaited_once_with(msg)


async def test_send_case_notification_passes_exception():
    case = KadCase(guid="guid-err", case_number="А60-2/2026")

    mock_smtp_instance = AsyncMock()
    mock_smtp_instance.__aenter__.return_value = mock_smtp_instance
    mock_smtp_instance.send_message = AsyncMock(
        side_effect=aiosmtplib.SMTPException("SMTP Server refused connection")
    )

    with patch("aiosmtplib.SMTP", return_value=mock_smtp_instance), patch.object(
        settings, "smtp_user", "user@test.ru"
    ):
        with pytest.raises(aiosmtplib.SMTPException):
            await send_case_notification("test@err.ru", case, "ООО Ошибка")


async def test_send_summary_email_builds_and_sends():
    """Дайджест: тема с датой, тело = готовый текст сводки."""
    mock_smtp_instance = AsyncMock()
    mock_smtp_instance.__aenter__.return_value = mock_smtp_instance
    mock_smtp_instance.login = AsyncMock()
    mock_smtp_instance.send_message = AsyncMock(return_value="250 OK")

    summary_text = "Сводка о новых судебных делах за 2026-09-25\nВсего новых дел: 3"

    with patch("aiosmtplib.SMTP", return_value=mock_smtp_instance), patch.object(
        settings, "smtp_user", "user@test.ru"
    ), patch.object(settings, "smtp_from_email", "sender@test.ru"):
        res = await send_summary_email(
            to_email="admin@test.ru",
            summary_text=summary_text,
            target_date="2026-09-25",
        )

    assert res["status"] == "sent"
    sent = mock_smtp_instance.send_message.call_args.args[0]
    assert sent["To"] == "admin@test.ru"
    assert sent["Subject"] == "Сводка о новых судебных делах за 2026-09-25"
    assert sent.get_content() == summary_text + "\n"
