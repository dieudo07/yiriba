"""Yiriba SaaS — SubscriptionPlan + Subscription models.

Trois forfaits YIRIBA :
- Graine : 100 eleves, 90 jours d'essai
- Racine : 400 eleves, pas d'essai
- Baobab : illimite, tarif personnalise

Subscription = historique des abonnements d'une ecole.
"""

import enum
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ── Enums ──────────────────────────────────────────────────────────


class SubscriptionStatus(str, enum.Enum):
    """Statut d'un abonnement."""

    TRIAL = "trial"        # Periode d'essai en cours
    ACTIVE = "active"      # Abonnement actif
    EXPIRED = "expired"    # Expire (essai ou abonnement)
    CANCELLED = "cancelled"  # Annule


# ── SubscriptionPlan ──────────────────────────────────────────────


class SubscriptionPlan(Base):
    """Forfait YIRIBA — definition du plan commercial.

    Les trois forfaits sont identifies par leur code :
    - graine : 100 eleves, 90j essai
    - racine : 400 eleves, pas d'essai
    - baobab : illimite, tarif personnalise
    """

    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # "Graine"
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # "graine"

    # ── Limites ───────────────────────────────────────────────────
    max_students: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = illimite (Baobab)
    trial_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 = pas d'essai

    # ── Tarification ──────────────────────────────────────────────
    price_per_student_year: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0"), nullable=False
    )

    # ── Fonctionnalites (JSON) ───────────────────────────────────
    features: Mapped[str] = mapped_column(Text, default="{}")  # JSON string

    # ── Statut ────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # ── Timestamps ────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="plan"
    )

    def __repr__(self) -> str:
        return f"SubscriptionPlan(code='{self.code}', name='{self.name}')"


# ── Subscription ──────────────────────────────────────────────────


class Subscription(Base):
    """Abonnement d'une ecole a un forfait.

    Conserve l'historique complet :
    - le montant reellement facture (independant du prix catalogue)
    - le nombre d'eleves au moment de la facturation
    - le tarif personnalise pour Baobab
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False
    )

    # ── Statut ────────────────────────────────────────────────────
    status: Mapped[SubscriptionStatus] = mapped_column(
        String(20), nullable=False, default=SubscriptionStatus.TRIAL
    )

    # ── Dates ─────────────────────────────────────────────────────
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Facturation ───────────────────────────────────────────────
    student_count_at_billing: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )  # Montant reellement facture

    # ── Tarif personnalise (Baobab) ──────────────────────────────
    custom_price_per_student: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Tarif negocie par eleve (Baobab)
    custom_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )  # Montant forfaitaire negocie

    # ── Timestamps ────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    school: Mapped["School"] = relationship()  # noqa: F821
    plan: Mapped["SubscriptionPlan"] = relationship(back_populates="subscriptions")

    __table_args__ = (
        UniqueConstraint("school_id", "plan_id", "started_at", name="uq_subscription_school_plan_start"),
    )

    def __repr__(self) -> str:
        return f"Subscription(school_id={self.school_id}, plan_id={self.plan_id}, status='{self.status}')"
