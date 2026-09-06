"""Yiriba SaaS — TeacherSubject: spécialités d'un enseignant.

Un enseignant peut avoir plusieurs spécialités (matières).
Ce modèle est DISTINCT de TeacherClass qui lie enseignant + classe + matière.
TeacherSubject = domaines de compétence de l'enseignant.
TeacherClass = affectation concrète dans une classe.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TeacherSubject(Base):
    """Spécialité d'un enseignant — matière qu'il maîtrise."""

    __tablename__ = "teacher_subjects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    level_preference: Mapped[str | None] = mapped_column(
        String(50)
    )  # ex: "Primaire", "Collège", "Lycée"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "school_id", "teacher_id", "subject_id",
            name="uq_teacher_subject_school",
        ),
    )

    # ── Relations ─────────────────────────────────────────────────
    subject: Mapped["Subject"] = relationship()  # noqa: F821
    teacher: Mapped["User"] = relationship()  # noqa: F821
