"""Yiriba SaaS — Evaluation + Grade models.

Evaluation = un devoir donné à toute une classe
Grade = la note d'un élève pour cette évaluation
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Evaluation(Base):
    """Évaluation — un devoir donné à une classe pour une matière.

    Types d'évaluation (format Yiriba Desktop) :
    - devoir1 (D/1)
    - devoir2 (D/2)
    - composition (Comp.)
    """

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_subjects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )

    # ── Définition de l'évaluation ────────────────────────────────
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # "Devoir 1 - Algebre"
    assessment_type: Mapped[str] = mapped_column(String(20), nullable=False)  # devoir1 | devoir2 | composition
    period: Mapped[str] = mapped_column(String(5), nullable=False)  # T1, T2, T3, S1, S2
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True
    )
    academic_period_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_periods.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Legacy (à supprimer après migration)
    academic_year: Mapped[str] = mapped_column(String(10), default="2025-2026")
    max_grade: Mapped[float] = mapped_column(Float, default=20.0)
    coefficient: Mapped[int] = mapped_column(default=1)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # ── Publication (fige les notes) ──────────────────────────────
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Timestamps ────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    grades: Mapped[list["Grade"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )
    class_subject_rel: Mapped["ClassSubject | None"] = relationship()  # noqa: F821
    academic_year_rel: Mapped["AcademicYear | None"] = relationship()  # noqa: F821
    academic_period_rel: Mapped["AcademicPeriod | None"] = relationship()  # noqa: F821
    subject: Mapped["Subject"] = relationship()  # noqa: F821
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])  # noqa: F821

    __table_args__ = (
        UniqueConstraint(
            "school_id", "class_id", "subject_id", "assessment_type", "period",
            name="uq_eval_school"
        ),
    )

    def __repr__(self) -> str:
        return f"Evaluation(id={self.id}, name='{self.name}', type='{self.assessment_type}')"


class Grade(Base):
    """Note d'un élève pour une évaluation donnée.

    La moyenne est calculée à la volée (pas stockée en base).
    Le bulletin publié est un snapshot figé dans la table bulletins.
    """

    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Note ──────────────────────────────────────────────────────
    grade: Mapped[float | None] = mapped_column(Float, nullable=True)  # null si ABS/DISP/empty
    status: Mapped[str] = mapped_column(String(20), default="graded")  # graded | absent | excused | empty
    comment: Mapped[str | None] = mapped_column(String(200))

    # ── Traçabilité modification ──────────────────────────────────
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modified_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Relations ─────────────────────────────────────────────────
    evaluation: Mapped["Evaluation"] = relationship(back_populates="grades")
    student: Mapped["Student"] = relationship(back_populates="grades")  # noqa: F821

    __table_args__ = (
        UniqueConstraint(
            "school_id", "evaluation_id", "student_id",
            name="uq_grade_school_eval_student"
        ),
    )

    def __repr__(self) -> str:
        return f"Grade(eval={self.evaluation_id}, student={self.student_id}, grade={self.grade})"
