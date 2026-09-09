"""Yiriba SaaS — Modèles niveau PLATEFORME (Super Admin YIRIBA).

Distinct du niveau école :
- PlatformSetting    : paramètres globaux de la plateforme (mode maintenance, nom, email contact)
- SubscriptionPayment: paiements des écoles à YIRIBA (abonnement — PAS la scolarité des élèves)
- SupportRequest     : demandes envoyées par les écoles via « Contacter YIRIBA »
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlatformSetting(Base):
    """Paramètre global de la plateforme (clé/valeur).

    Clés utilisées :
    - maintenance_mode : "true" | "false"
    - platform_name    : nom affiché de la plateforme
    - contact_email    : email de contact YIRIBA
    - notifications_read_at : date ISO de dernière lecture des notifications Super Admin
    """

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SubscriptionPayment(Base):
    """Paiement d'une école à YIRIBA pour son abonnement.

    ⚠️ À ne PAS confondre avec app.models.payment.Payment qui est la
    scolarité payée par les parents à l'école.
    """

    __tablename__ = "subscription_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )

    reference: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="XOF", nullable=False)

    # cash | transfer | mobile_money | check | other
    method: Mapped[str] = mapped_column(String(30), default="transfer", nullable=False)
    # paid | pending | failed | refunded
    status: Mapped[str] = mapped_column(String(20), default="paid", nullable=False)

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    recorded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SupportRequest(Base):
    """Demande de support envoyée par une école (« Contacter YIRIBA »).

    Le message part aussi en conversation au compte support (mécanisme
    existant) ; cette table permet au Super Admin de suivre/répondre.
    """

    __tablename__ = "support_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))

    # low | normal | high | urgent
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    # new | in_progress | resolved
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)

    response: Mapped[str | None] = mapped_column(Text)
    responded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
