"""Yiriba SaaS — Class, Subject, Enrollment, TeacherClass models."""

from datetime import datetime

from decimal import Decimal
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Class(Base):
    """Classe — appartient à une école. Nouvelle ligne par année scolaire."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)  # ex: "6ème A"
    level_id: Mapped[int | None] = mapped_column(
        ForeignKey("levels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Legacy (à supprimer après migration complète)
    level: Mapped[str | None] = mapped_column(String(50))  # ex: "6ème", "CE2"
    capacity: Mapped[int] = mapped_column(Integer, default=50)
    academic_year: Mapped[str] = mapped_column(String(10), default="2025-2026")

    # ── Période académique ────────────────────────────────────────
    period_type: Mapped[str] = mapped_column(String(10), default="trimestre")  # trimestre | semestre

    # ── Frais de scolarité ──────────────────────────────────────
    enrollment_fee: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Montant de l'inscription
    annual_tuition: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Scolarité annuelle

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("school_id", "academic_year_id", "level_id", "name", name="uq_class_school_year_level_name"),
    )

    # ── Relations ─────────────────────────────────────────────────
    school: Mapped["School"] = relationship(back_populates="classes")  # noqa: F821
    level_rel: Mapped["Level | None"] = relationship()  # noqa: F821
    academic_year_rel: Mapped["AcademicYear | None"] = relationship()  # noqa: F821
    enrollments: Mapped[list["Enrollment"]] = relationship(  # noqa: F821
        back_populates="class_", cascade="all, delete-orphan"
    )
    class_subjects: Mapped[list["ClassSubject"]] = relationship(  # noqa: F821
        back_populates="class_", cascade="all, delete-orphan"
    )
    teacher_classes: Mapped[list["TeacherClass"]] = relationship(  # noqa: F821
        back_populates="class_", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Class(id={self.id}, name='{self.name}')"

    @property
    def enrolled_count(self) -> int:
        return len(self.enrollments) if self.enrollments else 0


class Subject(Base):
    """Matière — appartient à une école."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(50))  # scientifique | litteraire | technique | autre
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)
    # Legacy — le coefficient réel est sur ClassSubject
    coefficient: Mapped[int] = mapped_column(Integer, default=1)
    max_grade: Mapped[int] = mapped_column(Integer, default=20)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_subject_school_code"),
    )

    # ── Relations ─────────────────────────────────────────────────
    school: Mapped["School"] = relationship(back_populates="subjects")  # noqa: F821
    evaluations: Mapped[list["Evaluation"]] = relationship(  # noqa: F821
        back_populates="subject", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Subject(id={self.id}, name='{self.name}')"


class ClassSubject(Base):
    """Liaison classe ↔ matière avec teacher assigné."""

    __tablename__ = "class_subjects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True
    )
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Configuration pédagogique ─────────────────────────────────
    coefficient: Mapped[int] = mapped_column(Integer, default=1)  # Coefficient dans cette classe
    max_score: Mapped[float] = mapped_column(Float, default=20.0)  # Barème max
    hours_per_week: Mapped[float | None] = mapped_column(Float, nullable=True)  # Volume horaire
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)  # Obligatoire
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("school_id", "class_id", "subject_id", name="uq_class_subject_school"),
    )

    # ── Relations ─────────────────────────────────────────────────
    class_: Mapped["Class"] = relationship(back_populates="class_subjects")  # noqa: F821
    subject: Mapped["Subject"] = relationship()  # noqa: F821
    academic_year_rel: Mapped["AcademicYear | None"] = relationship()  # noqa: F821


class TeacherClass(Base):
    """Affectation enseignant ↔ classe ↔ matière.

    Un seul enseignant par matière/classe (contrainte unique).
    is_primary distingue le titulaire du suppléant.
    """

    __tablename__ = "teacher_classes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=False
    )
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)  # Titulaire vs suppléant
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    assigned_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("school_id", "class_id", "subject_id", name="uq_teacher_class_school"),
    )

    # ── Relations ─────────────────────────────────────────────────
    class_: Mapped["Class"] = relationship(back_populates="teacher_classes")  # noqa: F821
    subject: Mapped["Subject"] = relationship()  # noqa: F821
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])  # noqa: F821
    assigner: Mapped["User | None"] = relationship(foreign_keys=[assigned_by])  # noqa: F821


class Enrollment(Base):
    """Inscription d'un élève dans une classe pour une année scolaire."""

    __tablename__ = "enrollments"

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
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Legacy (à supprimer après migration)
    academic_year: Mapped[str] = mapped_column(String(10), default="2025-2026")
    is_repeater: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | transferred | withdrawn
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    student: Mapped["Student"] = relationship(back_populates="enrollments")  # noqa: F821
    class_: Mapped["Class"] = relationship(back_populates="enrollments")  # noqa: F821

    def __repr__(self) -> str:
        return f"Enrollment(student={self.student_id}, class={self.class_id})"
