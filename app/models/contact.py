"""Модель контакта (потенциального клиента для предложения услуг)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Contact(Base):
    """Контакт компании в базе (потенциальный адресат рассылки)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Наименование компании или ИП",
    )
    inn: Mapped[str] = mapped_column(
        String(12),
        unique=True,
        index=True,
        nullable=False,
        doc="ИНН для сопоставления со сторонами судебных дел",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Email для отправки коммерческого предложения",
    )
    phone: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        doc="Контактный телефон",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Флаг активности контакта (рассылать ли письма)",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Примечания / комментарии менеджера",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Contact id={self.id} inn={self.inn!r} email={self.email!r} company={self.company_name[:30]!r}>"
