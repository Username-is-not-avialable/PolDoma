"""Модель журнала отправленных email-уведомлений (дедупликация case × contact)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.case import Case
from app.models.contact import Contact


class Notification(Base):
    """Отправленное уведомление о деле контакту.

    Уникальность пары (case_id, contact_id) гарантирует, что одно письмо
    по конкретному делу конкретному контакту отправляется только один раз.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("case_id", "contact_id", name="uq_notifications_case_contact"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Дело, по которому отправлено уведомление",
    )
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Контакт-адресат уведомления",
    )
    email: Mapped[str] = mapped_column(
        nullable=False,
        doc="Адрес, на который отправлено письмо (на момент отправки)",
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Когда письмо было отправлено",
    )

    case: Mapped[Case] = relationship("Case", lazy="selectin")
    contact: Mapped[Contact] = relationship("Contact", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} case_id={self.case_id} "
            f"contact_id={self.contact_id} email={self.email!r}>"
        )
