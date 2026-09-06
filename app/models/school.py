"""Yiriba SaaS — School (Tenant) model.

Chaque école est un tenant isolé. Toutes les tables métier
ont un `school_id` FK vers cette table.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class School(Base):
    """Établissement scolaire — tenant principal du SaaS."""

    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(20))  # Sigle (ex: CYA)
    school_type: Mapped[str] = mapped_column(String(20), default="college")  # maternelle|primaire|college|lycee|complexe|autre
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))  # Secteur/quartier
    region: Mapped[str | None] = mapped_column(String(100))  # Région/province
    country: Mapped[str] = mapped_column(String(60), default="Burkina Faso")
    website: Mapped[str | None] = mapped_column(String(200))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    motto: Mapped[str | None] = mapped_column(String(200))

    # ── Subscription ──────────────────────────────────────────────
    current_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=True
    )
    subscription_status: Mapped[str] = mapped_column(String(20), default="trial")
    # trial | active | expired | cancelled
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    student_count_at_billing: Mapped[int] = mapped_column(Integer, default=0)

    # Legacy (a supprimer apres migration)
    plan: Mapped[str] = mapped_column(String(20), default="gratuit")
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Discipline ───────────────────────────────────────────────
    discipline_mode: Mapped[str] = mapped_column(
        String(20), default="conduct"
    )  # conduct | general_average

    # ── Status ────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    users: Mapped[list["User"]] = relationship(back_populates="school", cascade="all, delete-orphan")  # noqa: F821
    roles: Mapped[list["Role"]] = relationship(back_populates="school", cascade="all, delete-orphan")  # noqa: F821
    students: Mapped[list["Student"]] = relationship(back_populates="school", cascade="all, delete-orphan")  # noqa: F821
    classes: Mapped[list["Class"]] = relationship(back_populates="school", cascade="all, delete-orphan")  # noqa: F821
    subjects: Mapped[list["Subject"]] = relationship(back_populates="school", cascade="all, delete-orphan")  # noqa: F821
    settings: Mapped[list["SchoolSetting"]] = relationship(back_populates="school", cascade="all, delete-orphan")  # noqa: F821

    def __repr__(self) -> str:
        return f"School(id={self.id}, name='{self.name}')"
