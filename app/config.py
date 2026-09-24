"""Настройки приложения (загружаются из окружения / .env)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # КАД
    kad_base_url: str = "https://kad.arbitr.ru"
    kad_cookie_file: Path = BASE_DIR / "data" / "kad_cookies.json"
    kad_cookie_headless: bool = True

    # Диапазон дат поиска (пустые строки = сегодня)
    kad_search_date_from: str = ""
    kad_search_date_to: str = ""


settings = Settings()
