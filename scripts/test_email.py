"""Скрипт для ручной проверки отправки email через настроенный SMTP.

Использование:
    python scripts/test_email.py --to your_email@example.com
    python scripts/test_email.py --to your_email@example.com --name "Иван Иванович"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import settings
from app.services.kad.parser import Case
from app.services.mailer import send_case_notification

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_email")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Тестовая отправка email-уведомления")
    parser.add_argument(
        "--to",
        required=True,
        help="Email-адрес получателя",
    )
    parser.add_argument(
        "--name",
        default="Уважаемый клиент",
        help="ФИО / Наименование получателя (по умолчанию: 'Уважаемый клиент')",
    )
    parser.add_argument(
        "--case-number",
        default="А60-59233/2026",
        help="Номер судебного дела (по умолчанию реальное дело: А60-59233/2026)",
    )
    parser.add_argument(
        "--guid",
        default="4a1d13f9-7756-4aa8-9274-a6fc7e098492",
        help="GUID карточки дела в КАД",
    )
    args = parser.parse_args()

    logger.info("Параметры SMTP подключения:")
    logger.info("  Хост: %s:%s (SSL: %s, STARTTLS: %s)", settings.smtp_host, settings.smtp_port, settings.smtp_use_ssl, settings.smtp_starttls)
    logger.info("  Пользователь: %s", settings.smtp_user or "<не указан>")
    logger.info("  Отправитель: %s <%s>", settings.smtp_from_name, settings.smtp_from_email or settings.smtp_user or "<не указан>")
    logger.info("  Получатель: %s", args.to)

    test_case = Case(
        guid=args.guid,
        case_number=args.case_number,
    )

    try:
        res = await send_case_notification(
            to_email=args.to,
            case=test_case,
            recipient_name=args.name,
        )
        logger.info("Результат отправки: %s", res)
        print("\n[УСПЕХ] Письмо успешно отправлено! Проверьте папку 'Входящие' (и 'Спам') на адресе %s\n" % args.to)
    except Exception as exc:
        logger.exception("Ошибка при отправке письма: %s", exc)
        print("\n[ОШИБКА] Не удалось отправить письмо: %s\n" % exc)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
