"""Сервис формирования и отправки email-уведомлений."""

from __future__ import annotations

from email.headerregistry import Address
from email.message import EmailMessage
import logging
from typing import Any

import aiosmtplib

from app.config import settings
from app.models.case import Case as OrmCase
from app.services.kad.parser import Case as KadCase

logger = logging.getLogger("mailer")


def get_case_url(guid: str) -> str:
    """Генерирует полную ссылку на карточку дела в КАД."""
    clean_guid = guid.strip("/ ")
    base = settings.kad_base_url.rstrip("/")
    return f"{base}/Card/{clean_guid}"


def build_case_notification_message(
    to_email: str,
    case: KadCase | OrmCase,
    recipient_name: str | None = None,
) -> EmailMessage:
    """Формирует текстовое email-сообщение о новом судебном деле.

    Текст сообщения:
    "{ФИО / Наименование получателя}, на вас подали в суд. Ссылка на дело: {ссылка}"
    """
    case_number = case.case_number or "Дело без номера"
    guid = case.guid or ""
    case_url = get_case_url(guid)

    name = (recipient_name or "").strip()
    greeting = f"{name}, на" if name else "На"

    body_text = f"{greeting} вас подали в суд. Ссылка на дело: {case_url}\n"

    msg = EmailMessage()
    msg["Subject"] = f"Уведомление о судебном деле {case_number}"

    sender_email = settings.smtp_from_email or settings.smtp_user
    sender_name = settings.smtp_from_name
    if sender_name and sender_email:
        # Корректное экранирование имени отправителя (RFC 5322)
        username, domain = sender_email.split("@", 1)
        msg["From"] = str(Address(display_name=sender_name, username=username, domain=domain))
    else:
        msg["From"] = sender_email

    msg["To"] = to_email
    msg.set_content(body_text, charset="utf-8")
    return msg


async def send_message(message: EmailMessage) -> dict[str, Any]:
    """Асинхронная отправка сообщения через SMTP с настройками из settings."""
    sender = settings.smtp_from_email or settings.smtp_user
    if not sender and not settings.smtp_host.startswith(("localhost", "127.0.0.1")):
        raise ValueError("SMTP_USER или SMTP_FROM_EMAIL не настроены в конфигурации")

    client = aiosmtplib.SMTP(
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        use_tls=settings.smtp_use_ssl,
        start_tls=settings.smtp_starttls,
        timeout=settings.smtp_timeout,
    )

    async with client:
        if settings.smtp_user and settings.smtp_password:
            await client.login(settings.smtp_user, settings.smtp_password)
        response = await client.send_message(message)
        logger.info(
            "Email успешно отправлен: to=%s, subject=%s",
            message["To"],
            message["Subject"],
        )
        return {"status": "sent", "response": response}


async def send_summary_email(
    to_email: str,
    summary_text: str,
    target_date: str,
) -> dict[str, Any]:
    """Отправляет дайджест-сводку о новых делах админу.

    `summary_text` формируется заранее (app.services.summary),
    здесь — только сборка конверта и отправка через SMTP.
    """
    msg = EmailMessage()
    msg["Subject"] = f"Сводка о новых судебных делах за {target_date}"

    sender_email = settings.smtp_from_email or settings.smtp_user
    sender_name = settings.smtp_from_name
    if sender_name and sender_email:
        username, domain = sender_email.split("@", 1)
        msg["From"] = str(Address(display_name=sender_name, username=username, domain=domain))
    else:
        msg["From"] = sender_email

    msg["To"] = to_email
    msg.set_content(summary_text, charset="utf-8")
    return await send_message(msg)


async def send_case_notification(
    to_email: str,
    case: KadCase | OrmCase,
    recipient_name: str | None = None,
) -> dict[str, Any]:
    """Сборка и отправка уведомления о деле целевому получателю."""
    message = build_case_notification_message(
        to_email=to_email,
        case=case,
        recipient_name=recipient_name,
    )
    return await send_message(message)
