"""Модели судебных дел и их сторон (участников)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Case(Base):
    """Судебное дело, найденное в КАД."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guid: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, doc="GUID карточки в КАД"
    )
    case_number: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, doc="Номер дела (напр. А60-59233/2026)"
    )
    case_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, doc="Тип дела (И/А/Б)"
    )
    court: Mapped[str | None] = mapped_column(
        String(255), nullable=True, doc="Наименование суда"
    )
    judge: Mapped[str | None] = mapped_column(
        String(255), nullable=True, doc="ФИО судьи"
    )
    start_date: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="Дата начала/регистрации дела из КАД"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Дата и время сохранения в БД",
    )

    # Связь со сторонами дела
    sides: Mapped[list[Side]] = relationship(
        "Side",
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Case id={self.id} case_number={self.case_number!r} guid={self.guid!r}>"


class Side(Base):
    """Сторона (участник) судебного дела."""

    __tablename__ = "sides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Роль участника: plaintiff, respondent, other",
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Наименование или ФИО участника",
    )
    inn: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
        index=True,
        doc="ИНН юридического лица (10 цифр) или ИП/физлица (12 цифр)",
    )
    address: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Адрес участника",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    case: Mapped[Case] = relationship("Case", back_populates="sides")

    __table_args__ = (
        Index("ix_sides_case_id_role", "case_id", "role"),
        Index("ix_sides_inn_role", "inn", "role"),
    )

    def __repr__(self) -> str:
        return f"<Side id={self.id} role={self.role!r} inn={self.inn!r} name={self.name[:30]!r}>"
