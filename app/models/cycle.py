"""Yiriba SaaS — Cycle + Level models.

Cycle = Préscolaire, Primaire, Collège, Lycée
Level = CP1, CE1, 6e, 5e, 2nde, Terminale, etc.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Cycle(Base):
    """Cycle d'enseignement — appartient à une école."""

    __tablename__ = "cycles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)  # "Primaire", "Collège"
    code: Mapped[str] = mapped_column(String(20), nullable=False)  # "primaire", "college"
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    levels: Mapped[list["Level"]] = relationship(  # noqa: F821
        back_populates="cycle", cascade="all, delete-orphan", order_by="Level.display_order"
    )

    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_cycle_school_code"),
    )

    def __repr__(self) -> str:
        return f"Cycle(name='{self.name}', school_id={self.school_id})"


class Level(Base):
    """Niveau d'enseignement — appartient à un cycle."""

    __tablename__ = "levels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cycle_id: Mapped[int] = mapped_column(
        ForeignKey("cycles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)  # "6e", "Terminale"
    code: Mapped[str] = mapped_column(String(20), nullable=False)  # "6e", "terminale"
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    cycle: Mapped["Cycle"] = relationship(back_populates="levels")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("school_id", "cycle_id", "code", name="uq_level_school_cycle_code"),
    )

    def __repr__(self) -> str:
        return f"Level(name='{self.name}', cycle_id={self.cycle_id})"
