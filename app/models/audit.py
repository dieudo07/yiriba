"""Yiriba SaaS — Audit log model for tracking all sensitive actions."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """Log d'audit — trace TOUTES les actions sensibles.

    Qui (user_id) a fait quoi (action) sur quoi (resource) à quelle heure.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── Action ────────────────────────────────────────────────────
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # Exemples: user.create, grade.update, payment.confirm, role.delete, login.success, login.failure

    resource: Mapped[str] = mapped_column(String(30), nullable=False)  # user, student, grade, payment, role, etc.
    resource_id: Mapped[int | None] = mapped_column(nullable=True)  # ID de la ressource concernée

    # ── Détails ───────────────────────────────────────────────────
    details: Mapped[str | None] = mapped_column(Text)  # JSON des changements
    ip_address: Mapped[str | None] = mapped_column(String(45))  # IPv4 ou IPv6
    user_agent: Mapped[str | None] = mapped_column(String(300))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"AuditLog(user={self.user_id}, action={self.action}, resource={self.resource})"
