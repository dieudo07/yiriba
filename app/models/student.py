"""Yiriba SaaS — Student model.

Status-based soft delete: jamais de suppression physique.
school_id toujours extrait du JWT, jamais du payload client.
"""

from datetime import date, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import StudentStatus


class Student(Base):
    """Élève — chaque élève appartient à une école (school_id non-nullable).

    Soft delete via status : INACTIVE / WITHDRAWN / TRANSFERRED / GRADUATED.
    Jamais de DELETE physique pour préserver l'intégrité historique.
    """

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Identifiant ──────────────────────────────────────────────
    matricule: Mapped[str] = mapped_column(String(30), default="", index=True)

    # ── Identité civile ──────────────────────────────────────────
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(DateTime(timezone=True))
    birth_place: Mapped[str | None] = mapped_column(String(100))
    nationality: Mapped[str] = mapped_column(String(60), default="Burkinabè")
    gender: Mapped[str] = mapped_column(String(1), default="M")  # M ou F

    # ── Contact ──────────────────────────────────────────────────
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(30))

    # ── Compte lié ────────────────────────────────────────────────
    # Lien explicite vers le compte utilisateur élève (User).
    # Unique source de vérité pour le portail : jamais de matching par nom/email.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, unique=True
    )

    # ── Photo ────────────────────────────────────────────────────
    photo_url: Mapped[str | None] = mapped_column(String(500))

    # ── Informations scolaires ───────────────────────────────────
    previous_school: Mapped[str | None] = mapped_column(String(200))
    medical_info: Mapped[str | None] = mapped_column(Text)
    is_repeater: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)

    # ── Statut (soft delete) ─────────────────────────────────────
    status: Mapped[StudentStatus] = mapped_column(
        Enum(StudentStatus, values_callable=lambda x: [e.value for e in x]), nullable=False, default=StudentStatus.ACTIVE
    )
    status_reason: Mapped[str | None] = mapped_column(String(200))

    # ── Timestamps ───────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relations ────────────────────────────────────────────────
    school: Mapped["School"] = relationship(back_populates="students")  # noqa: F821
    enrollments: Mapped[list["Enrollment"]] = relationship(  # noqa: F821
        back_populates="student", cascade="all, delete-orphan"
    )
    grades: Mapped[list["Grade"]] = relationship(  # noqa: F821
        back_populates="student", cascade="all, delete-orphan"
    )
    attendances: Mapped[list["Attendance"]] = relationship(  # noqa: F821
        back_populates="student", cascade="all, delete-orphan"
    )
    parent_links: Mapped[list["ParentStudent"]] = relationship(  # noqa: F821
        back_populates="student", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Student(id={self.id}, name='{self.first_name} {self.last_name}', status={self.status})"
