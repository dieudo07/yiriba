"""Yiriba SaaS — Discipline models (rules + records).

DisciplinaryRuleSet = barème configurable par école (une ligne par type d'incident).
DisciplinaryRecord   = incident enregistré (auto depuis Attendance ou manuel).

Les points_deducted sont COPIÉS depuis la règle au moment de l'incident
pour garantir un historique stable même si le barème change ensuite.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DisciplinaryRuleSet(Base):
    """Barème disciplinaire — une ligne par type d'incident par école.

    Modifiable dans Paramètres > Discipline par l'administrateur.
    """
    __tablename__ = "disciplinary_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Types prédéfinis : absence_non_justifiee, retard, incivilite, autre
    points_deducted: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    description: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "school_id", "incident_type",
            name="uq_disciplinary_rule_school_type",
        ),
    )

    def __repr__(self) -> str:
        return f"DisciplinaryRule({self.incident_type}, -{self.points_deducted}pts)"


class DisciplinaryRecord(Base):
    """Enregistrement disciplinaire — un incident par élève.

    source="auto"  → généré automatiquement depuis Attendance
    source="manual" → saisi manuellement par un enseignant ou admin

    status="active"    → incident en vigueur
    status="cancelled" → annulé (soft delete pour audit trail)
    """
    __tablename__ = "disciplinary_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(5), nullable=False)  # T1, T2, T3, S1, S2
    academic_year: Mapped[str] = mapped_column(String(10), nullable=False)

    # --- Incident ---
    incident_type: Mapped[str] = mapped_column(String(30), nullable=False)
    points_deducted: Mapped[float] = mapped_column(Float, nullable=False)
    # Copié depuis DisciplinaryRuleSet au moment de la création

    # --- Source ---
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # auto | manual
    recorded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200))

    # --- Status ---
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | cancelled
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "idx_disciplinary_student_period",
            "student_id", "period", "academic_year",
        ),
    )

    def __repr__(self) -> str:
        return f"DisciplinaryRecord(student={self.student_id}, type={self.incident_type}, -{self.points_deducted}pts)"
