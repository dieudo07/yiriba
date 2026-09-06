"""Yiriba SaaS — Payment models (frais scolarite, recus, mobile money).

FeeObligation = ce qu'une famille doit
Payment = ce qui a ete effectivement paye
Jamais une seule table qui mele du et paye.
"""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PaymentStatus(str, enum.Enum):
    """Statuts de paiement."""
    PENDING = "pending"        # En attente de confirmation
    CONFIRMED = "confirmed"    # Paiement valide
    FAILED = "failed"          # Paiement echoue
    REFUNDED = "refunded"      # Rembourse
    CANCELLED = "cancelled"    # Annule


class FeeObligation(Base):
    """Obligation de paiement — frais scolaires par classe/niveau/élève et période."""

    __tablename__ = "fee_obligations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=True, index=True
    )
    level: Mapped[str | None] = mapped_column(String(50), nullable=True)  # ex: "6eme", "primaire"
    category: Mapped[str] = mapped_column(
        String(50), default="scolarite"
    )  # scolarite | inscription | cantine | transport | activites | examens | autre
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: "Frais de scolarité annuelle"
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    period: Mapped[str] = mapped_column(String(20), default="annuel")  # T1, T2, T3, S1, S2, annuel
    academic_year: Mapped[str] = mapped_column(String(10), default="2025-2026")
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(default=True)  # obligatoire ou facultatif

    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- Relations ---
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="obligation", cascade="all, delete-orphan"
    )
    installments: Mapped[list["FeeInstallment"]] = relationship(
        back_populates="obligation", cascade="all, delete-orphan", order_by="FeeInstallment.installment_number"
    )


class FeeInstallment(Base):
    """Échéance / tranche d'une obligation de paiement."""

    __tablename__ = "fee_installments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    obligation_id: Mapped[int] = mapped_column(
        ForeignKey("fee_obligations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installment_number: Mapped[int] = mapped_column(default=1)  # 1, 2, 3...
    title: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: "Tranche 1 - Octobre"
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- Relations ---
    obligation: Mapped["FeeObligation"] = relationship(back_populates="installments")
    payments: Mapped[list["Payment"]] = relationship(back_populates="installment")


class Payment(Base):
    """Paiement effectue par un eleve.

    idempotency_key = anti-doublon webhook (un meme paiement ne doit
    jamais etre compte deux fois si le webhook est renvoye).
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    obligation_id: Mapped[int | None] = mapped_column(
        ForeignKey("fee_obligations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    installment_id: Mapped[int | None] = mapped_column(
        ForeignKey("fee_installments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recorded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # --- Montant ---
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_method: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # cash | mobile_money | bank | cheque | other

    # --- Transaction ---
    transaction_id: Mapped[str | None] = mapped_column(String(100))

    # --- Mobile Money ---
    mobile_operator: Mapped[str | None] = mapped_column(String(20))  # mtn | orange | wave | moov
    mobile_number: Mapped[str | None] = mapped_column(String(30))

    # --- Statut ---
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, values_callable=lambda x: [e.value for e in x]), default=PaymentStatus.CONFIRMED
    )

    # --- Anti-doublon webhook ---
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    webhook_received: Mapped[bool | None] = mapped_column(default=False)
    webhook_raw: Mapped[str | None] = mapped_column(Text)  # JSON brut du webhook (audit)

    # --- Remboursement / Annulation ---
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    refund_reason: Mapped[str | None] = mapped_column(String(200))

    # --- Correction ---
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    corrected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correction_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Recu ---
    receipt_url: Mapped[str | None] = mapped_column(String(500))
    receipt_qr_token: Mapped[str | None] = mapped_column(String(200))  # Token signe HMAC pour QR

    notes: Mapped[str | None] = mapped_column(Text)

    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- Relations ---
    obligation: Mapped["FeeObligation | None"] = relationship(back_populates="payments")
    installment: Mapped["FeeInstallment | None"] = relationship(back_populates="payments")

    def __repr__(self) -> str:
        return f"Payment(id={self.id}, amount={self.amount}, method={self.payment_method})"
