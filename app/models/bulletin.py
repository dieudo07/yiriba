"""Yiriba SaaS — Bulletin model (snapshot fige des notes/moyennes/rangs).

Le bulletin est un snapshot fige une fois publie.
Le PDF est genere a partir de data_json, jamais recalcule.
Un bulletin publie ne peut etre modifie que par suppression + recreation.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Bulletin(Base):
    """Bulletin — snapshot fige des notes/moyennes/rangs a un instant T."""

    __tablename__ = "bulletins"

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
    period: Mapped[str] = mapped_column(String(5), nullable=False)  # T1, T2, T3, S1, S2
    academic_year: Mapped[str] = mapped_column(String(10), nullable=False)

    # --- Statut ---
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | generated | published

    # --- Donnees figees (SNAPSHOT) ---
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    # Contient :
    # {
    #   "subjects": [
    #     {"name": "Maths", "coeff": 4,
    #      "grades": {"devoir1": 14, "devoir2": 12, "composition": 15},
    #      "average": 13.75, "rank": 3},
    #     ...
    #   ],
    #   "overall_average": 12.5,
    #   "rank": 8,
    #   "total_students": 27,
    #   "previous_averages": {"T1": 11.5, "T2": 12.0},
    #   "conduct_score": 18.0,
    #   "decision": "Admis"
    # }

    overall_average: Mapped[float] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    total_students: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str | None] = mapped_column(String(50))  # Admis | Redouble (uniquement T3/S2)

    # --- Metadonnees ---
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # --- Relations ---
    student: Mapped["Student"] = relationship()  # noqa: F821

    __table_args__ = (
        UniqueConstraint(
            "school_id", "student_id", "period", "academic_year",
            name="uq_bulletin_school"
        ),
    )

    def __repr__(self) -> str:
        return f"Bulletin(student={self.student_id}, period='{self.period}', status='{self.status}')"
