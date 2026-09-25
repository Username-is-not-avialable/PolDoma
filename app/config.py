"""Настройки приложения (загружаются из окружения / .env)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # КАД
    kad_base_url: str = "https://kad.arbitr.ru"
    # headless-режим НЕ проходит pravocaptcha (WASM-модуль падает), из-за чего
    # API отвечает 451. Включать только для отладки; рабочий режим — headed
    # (реальный дисплей) или Xvfb в контейнере.
    kad_browser_headless: bool = False

    # Диапазон дат поиска (пустые строки = сегодня)
    kad_search_date_from: str = ""
    kad_search_date_to: str = ""

    # База данных PostgreSQL
    database_url: str = "postgresql+asyncpg://poldoma_user:poldoma_pass@localhost:5434/poldoma"
    db_echo: bool = False

    # SMTP для email-рассылки
    smtp_host: str = "smtp.yandex.ru"
    smtp_port: int = 465
    smtp_use_ssl: bool = True       # True для порта 465 (SMTPS), False для 587 или 1025
    smtp_starttls: bool = False     # True для STARTTLS (обычно порт 587)
    smtp_user: str = ""             # email / логин (напр. ivan@yandex.ru или info@poldoma.ru)
    smtp_password: str = ""         # пароль приложения (App Password)
    smtp_from_email: str = ""       # адрес отправителя (если пусто, берётся smtp_user)
    smtp_from_name: str = "ПолдОма"  # отображаемое имя отправителя
    smtp_timeout: float = 30.0      # таймаут сетевого подключения (сек)


settings = Settings()
