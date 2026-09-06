"""Yiriba SaaS — Attendance model (absences, retards, incivismes).

Granularite par creneau horaire (slot_index).
Contrainte unique sur (student_id, date, period, slot_index) pour eviter les doublons.
"""

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StatutPresence(str, enum.Enum):
    """Statuts de presence — en francais."""
    PRESENT = "present"
    ABSENT = "absent"
    RETARD = "late"
    EXCUSE = "excused"
    INCIVISME = "incivisme"


class Attendance(Base):
    """Presence / Absence / Retard / Incivisme — un enregistrement par eleve par creneau."""

    __tablename__ = "attendances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    recorded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # --- Donnees ---
    date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(String(5), nullable=False)  # T1, T2, T3, S1, S2
    slot_index: Mapped[int] = mapped_column(Integer, default=0)  # 0=matin, 1=apres-midi

    status: Mapped[StatutPresence] = mapped_column(
        Enum(StatutPresence, values_callable=lambda x: [e.value for e in x]), nullable=False, default=StatutPresence.PRESENT
    )
    minutes_late: Mapped[int | None] = mapped_column(default=None)
    is_justified: Mapped[bool] = mapped_column(Boolean, default=False)
    justification: Mapped[str | None] = mapped_column(Text)

    # --- Workflow justification + validation (module Présences complet) ---
    justification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none", server_default="none"
    )  # none / pending / accepted / refused
    validated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    validated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- Relations ---
    student: Mapped["Student"] = relationship(back_populates="attendances")  # noqa: F821

    __table_args__ = (
        UniqueConstraint(
            "school_id", "student_id", "date", "period",
            name="uq_attendance_school"
        ),
    )

    def __repr__(self) -> str:
        return f"Attendance(student={self.student_id}, date={self.date}, status={self.status})"
