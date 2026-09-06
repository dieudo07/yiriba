"""Yiriba SaaS — Notification settings model.

Controls which notifications are enabled per event type per school.
Each row = one event type (absence, new grade, payment due, etc.)
with SMS/email toggles and customizable message templates.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# Allowed template variables per event type
TEMPLATE_VARIABLES = {
    "absence": ["{nom_eleve}", "{prenom_eleve}", "{classe}", "{date}", "{ecole}"],
    "new_grade": ["{nom_eleve}", "{prenom_eleve}", "{classe}", "{matiere}", "{note}", "{max_note}", "{ecole}"],
    "payment_due": ["{nom_eleve}", "{prenom_eleve}", "{classe}", "{montant}", "{date_echeance}", "{ecole}"],
    "payment_received": ["{nom_eleve}", "{prenom_eleve}", "{montant}", "{date}", "{ecole}"],
    "bulletin_ready": ["{nom_eleve}", "{prenom_eleve}", "{classe}", "{periode}", "{moyenne}", "{ecole}"],
    "account_validation": ["{prenom_eleve}", "{nom_eleve}", "{email}", "{ecole}"],
    "announcement": ["{titre}", "{message}", "{ecole}"],
    "low_attendance": ["{nom_eleve}", "{prenom_eleve}", "{classe}", "{taux_presence}", "{ecole}"],
}

# Default message templates per event type (French)
DEFAULT_TEMPLATES = {
    "absence": "Bonjour {prenom_eleve} {nom_eleve}, vous etes absent(e) le {date} de l'ecole {ecole}.",
    "new_grade": "Bonjour {prenom_eleve} {nom_eleve}, vous avez recu {note}/{max_note} en {matiere} ({classe}).",
    "payment_due": "Bonjour {prenom_eleve} {nom_eleve}, une echeance de {montant} FCFA est due le {date_echeance} pour {classe}.",
    "payment_received": "Bonjour {prenom_eleve} {nom_eleve}, votre paiement de {montant} FCFA a ete enregistre le {date}.",
    "bulletin_ready": "Bonjour {prenom_eleve} {nom_eleve}, votre bulletin de {periode} est disponible. Moyenne: {moyenne}/20.",
    "account_validation": "Bonjour {prenom_eleve} {nom_eleve}, votre compte {email} a ete active sur {ecole}.",
    "announcement": "{titre}: {message}",
    "low_attendance": "Alerte: {prenom_eleve} {nom_eleve} ({classe}) a un taux de presence de {taux_presence}%.",
}


class NotificationSetting(Base):
    """Notification preferences per event type per school.

    One row per event type. Controls whether SMS/email are enabled
    and stores the customizable message template.
    """

    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Event type identifier
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Channel toggles
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Customizable message template (null = use default)
    message_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("school_id", "event_type", name="uq_notif_setting_school_event"),
    )

    def __repr__(self) -> str:
        return f"NotificationSetting(event='{self.event_type}', sms={self.sms_enabled}, email={self.email_enabled})"
