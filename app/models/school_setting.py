"""Yiriba SaaS — School settings model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SchoolSetting(Base):
    """Paramètres d'une école — clé/valeur pour des configs flexibles."""

    __tablename__ = "school_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relations ─────────────────────────────────────────────────
    school: Mapped["School"] = relationship(back_populates="settings")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("school_id", "key", name="uq_setting_school_key"),
    )

    def __repr__(self) -> str:
        return f"SchoolSetting(key='{self.key}', value='{self.value}')"
