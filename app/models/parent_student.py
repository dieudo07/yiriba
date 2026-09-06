"""Yiriba SaaS — ParentStudent model (ManyToMany parent ↔ élève avec rôle).

Un élève peut avoir plusieurs parents (père + mère + tuteur).
Un parent peut avoir plusieurs élèves (frères/soeurs).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ParentRole


class ParentStudent(Base):
    """Table de liaison Parent ↔ Élève avec rôle du parent.

    Le parent est un User avec role_type=PARENT.
    is_primary détermine le parent contact principal.
    """

    __tablename__ = "parent_student"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ParentRole] = mapped_column(
        default=ParentRole.OTHER, nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    parent: Mapped["User"] = relationship()  # noqa: F821
    student: Mapped["Student"] = relationship(back_populates="parent_links")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("school_id", "parent_id", "student_id", name="uq_parent_student_school"),
    )

    def __repr__(self) -> str:
        return f"ParentStudent(parent={self.parent_id}, student={self.student_id}, role={self.role})"
