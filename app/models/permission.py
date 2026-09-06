"""Yiriba SaaS — Permission and Role models (RBAC).

Rôles = données en base, pas en dur dans le code.
Le directeur de chaque école crée des rôles personnalisés.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Permission(Base):
    """Permission atomique — prédéfinie au seed, jamais modifiable par l'utilisateur.

    Exemples : student.create, grade.read, payment.refund, role.update
    """

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    codename: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    resource: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Permission({self.codename})"


class Role(Base):
    """Rôle — système (seed, is_system=True) OU personnalisé (créé par le directeur).

    Chaque école a ses propres rôles (school_id non-nullable).
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    school: Mapped["School"] = relationship(back_populates="roles")  # noqa: F821
    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(back_populates="role")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_role_school_name"),
    )

    def __repr__(self) -> str:
        return f"Role(id={self.id}, name='{self.name}', school_id={self.school_id})"


class RolePermission(Base):
    """Table de liaison rôle ↔ permission."""

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )

    # ── Relations ─────────────────────────────────────────────────
    role: Mapped["Role"] = relationship(back_populates="permissions")
    permission: Mapped["Permission"] = relationship()
