# Структура проекта

Python + FastAPI · PostgreSQL (SQLAlchemy async + Alembic) · Playwright (cookies КАД) · APScheduler · Docker

```
PolDoma/
├── docs/                          # исследование источников, структура проекта
├── pyproject.toml                   # deps: httpx, playwright, pydantic(-settings), pytest
├── docker-compose.yml             # postgres + backend
├── .env.example                   # SMTP, Bitrix24 webhook, параметры БД и КАД
├── alembic/                       # миграции
├── scripts/import_contacts.py     # загрузка контактов из CSV
├── tests/                         # тесты на моках (без сети)
│
└── app/
    ├── main.py                    # точка входа FastAPI
    ├── config.py                  # настройки из env (pydantic-settings)
    ├── database.py                # engine, сессии
    ├── scheduler.py               # APScheduler: опрос КАД, рассылка
    │
    ├── models/                    # ORM: case, contact, campaign, dispatch, reply
    ├── schemas/                   # Pydantic-схемы (API + ответы КАД)
    │
    ├── services/
    │   ├── kad/
    │   │   ├── cookie_fetcher.py  # Playwright: cookies для kad.arbitr.ru (Cloudflare)
    │   │   ├── client.py          # POST /Kad/SearchInstances (и A/B аналоги)
    │   │   ├── parser.py          # нормализация JSON → модели Case
    │   │   └── monitor.py         # периодический опрос (дата=сегодня, ответчик), дедупликация
    │   ├── matching.py            # новые дела ↔ контакты (ИНН/имя)
    │   ├── mailer.py              # рассылка КП + фиксация в dispatches
    │   └── bitrix24/              # REST: crm.lead.add; вебхук приёма ответов
    │
    └── api/                       # CRUD: cases, contacts, campaigns, dispatches
```

## Ключевые решения

- Парсинг только напрямую из КАД; агрегаторы не используются.
- Cookie-fetcher отдельный компонент: cookies кэшируются, обновляются при 403.
- Дедупликация дел — уникальный индекс по GUID карточки/номеру.
- Статусы отправок (`pending → sent/failed`) + timestamp + ID письма — фиксация рассылки.
- Ответы клиентов → лид в Bitrix24 (`crm.lead.add`) с привязкой к делу.
