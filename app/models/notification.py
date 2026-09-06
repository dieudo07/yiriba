"""Yiriba SaaS — Notification model (historique des notifications envoyees).

Canal : sms | email | push | in_app
Statut : pending | sent | failed | read
Retry automatique avec backoff exponentiel (3 tentatives).
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationChannel(str, enum.Enum):
    """Canal de notification."""
    SMS = "sms"
    EMAIL = "email"
    PUSH = "push"
    IN_APP = "in_app"


class NotificationCategory(str, enum.Enum):
    """Categorie de notification."""
    ABSENCE = "absence"
    PAYMENT_REMINDER = "payment_reminder"
    GRADE_PUBLISHED = "grade_published"
    ANNOUNCEMENT = "announcement"
    ACCOUNT_VALIDATION = "account_validation"
    OTHER = "other"


class NotificationStatus(str, enum.Enum):
    """Statut d'envoi de la notification."""
    PENDING = "pending"    # En attente d'envoi
    SENT = "sent"          # Envoye avec succes
    FAILED = "failed"      # Echec apres 3 tentatives
    READ = "read"          # Lu par le destinataire


class Notification(Base):
    """Historique des notifications envoyees.

    Permet de garder une trace meme si l'API SMS est indisponible.
    Les notifications echouees sont relancables manuellement par l'admin.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    recipient_phone: Mapped[str | None] = mapped_column(String(30))
    recipient_email: Mapped[str | None] = mapped_column(String(200))

    # --- Contenu ---
    channel: Mapped[NotificationChannel] = mapped_column(
        nullable=False, default=NotificationChannel.IN_APP
    )
    category: Mapped[NotificationCategory] = mapped_column(
        nullable=False, default=NotificationCategory.OTHER
    )
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Statut d'envoi ---
    status: Mapped[NotificationStatus] = mapped_column(
        nullable=False, default=NotificationStatus.PENDING
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_read: Mapped[bool] = mapped_column(default=False, index=True)
    error_message: Mapped[str | None] = mapped_column(String(500))

    # --- Link to related entity ---
    related_entity_type: Mapped[str | None] = mapped_column(String(50))
    related_entity_id: Mapped[int | None] = mapped_column(Integer)

    # --- Retry ---
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"Notification(id={self.id}, channel='{self.channel}', status='{self.status}')"
