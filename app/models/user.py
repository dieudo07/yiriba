"""Yiriba SaaS — User model with multi-role support and account confirmation.

Le statut 'pending' empêche la connexion tant que le directeur ne valide pas.
Ondelete de role_id = RESTRICT : impossible de supprimer un rôle avec des utilisateurs.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserStatus(str, enum.Enum):
    PENDING = "pending"      # Compte créé, en attente de validation
    ACTIVE = "active"        # Compte activé, peut se connecter
    SUSPENDED = "suspended"  # Compte suspendu temporairement
    REJECTED = "rejected"    # Demande rejetée par le directeur


class UserRole(str, enum.Enum):
    """Rôle global — détermine le portail d'accès.

    Les sous-rôles admin (Directeur, Secrétaire) vivent
    dans la table `roles` via RBAC.
    """
    ADMIN = "admin"          # Administration / Direction
    TEACHER = "teacher"      # Enseignant
    EDUCATOR = "educator"    # Éducateur
    SECRETARY = "secretary"  # Secrétaire
    PARENT = "parent"        # Parent d'élève
    STUDENT = "student"      # Élève
    COMPTABLE = "comptable"  # Comptable / Finance


class User(Base):
    """Utilisateur du système — chaque user appartient à une école (school_id)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )

    # ── Identité ──────────────────────────────────────────────────
    email: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    username: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)  # Identifiant YIRIBA (YRB-XXXXXX) pour élèves
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))

    # ── Sécurité compte ───────────────────────────────────────────
    must_change_password: Mapped[bool] = mapped_column(default=False)  # Première connexion

    # ── Rôle & Permissions ────────────────────────────────────────
    role_type: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]), nullable=False, default=UserRole.ADMIN
    )
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=True
    )
    # RESTRICT: impossible de supprimer un rôle qui a des utilisateurs

    # ── Statut & Confirmation ─────────────────────────────────────
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, values_callable=lambda x: [e.value for e in x]), nullable=False, default=UserStatus.PENDING
    )
    invited_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmation_token: Mapped[str | None] = mapped_column(String(100), unique=True)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_confirmation_token: Mapped[str | None] = mapped_column(String(100), unique=True)
    account_confirmation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # ── Sécurité ──────────────────────────────────────────────────
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(String(45))
    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    temp_password_displayed: Mapped[bool] = mapped_column(default=False)  # Mot de passe temporaire déjà affiché à l'admin

    # ── Timestamps ────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    school: Mapped["School"] = relationship(back_populates="users")  # noqa: F821
    role: Mapped["Role | None"] = relationship(back_populates="users")  # noqa: F821
    invited_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[invited_by], remote_side="User.id"
    )

    def __repr__(self) -> str:
        return f"User(id={self.id}, email='{self.email}', role={self.role_type})"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
