"""Yiriba SaaS — AcademicYear model.

Chaque année scolaire appartient à une école.
is_current = True pour l'année en cours.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AcademicYear(Base):
    """Année scolaire — chaque école a ses propres années."""

    __tablename__ = "academic_years"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(10), nullable=False)  # "2025-2026"
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned | active | closed | archived
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    school: Mapped["School"] = relationship()  # noqa: F821
    periods: Mapped[list["AcademicPeriod"]] = relationship(back_populates="academic_year")

    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_academic_year_school_name"),
    )

    def __repr__(self) -> str:
        return f"AcademicYear(name='{self.name}', school_id={self.school_id})"


class AcademicPeriod(Base):
    """Période académique — Trimestre, Semestre ou personnalisé.

    Chaque période appartient à une année scolaire et une école.
    """

    __tablename__ = "academic_periods"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    academic_year_id: Mapped[int] = mapped_column(
        ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)  # "Trimestre 1", "Semestre 2", "Période A"
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)  # trimester | semester | custom
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    order_index: Mapped[int] = mapped_column(default=1)  # Pour l'ordre d'affichage
    status: Mapped[str] = mapped_column(String(20), default="upcoming")  # upcoming | active | completed
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Relations ─────────────────────────────────────────────────
    academic_year: Mapped["AcademicYear"] = relationship()
    school: Mapped["School"] = relationship()  # noqa: F821

    __table_args__ = (
        UniqueConstraint("school_id", "academic_year_id", "name", name="uq_period_school_year_name"),
    )

    def __repr__(self) -> str:
        return f"AcademicPeriod(name='{self.name}', year_id={self.academic_year_id})"
