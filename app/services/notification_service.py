"""Yiriba SaaS — Service de notifications centralisé.

Point d'entrée unique pour créer des notifications in-app (+ email si configuré).

Règles :
- Toutes les notifications sont filtrées par school_id.
- Respecte les préférences par événement (NotificationSetting : in_app / email).
- Le canal email n'est utilisé que si SMTP/Resend est configuré ; sinon in-app seul.
- Chaque notification peut pointer vers une entité (lien direct dans l'UI).
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.notification_setting import NotificationSetting
from app.models.parent_student import ParentStudent
from app.models.user import User

logger = logging.getLogger(__name__)

# Types d'événements supportés (alignés sur notification_setting.TEMPLATE_VARIABLES)
EVENT_BULLETIN_READY = "bulletin_ready"
EVENT_ABSENCE = "absence"
EVENT_PAYMENT_DUE = "payment_due"
EVENT_PAYMENT_RECEIVED = "payment_received"
EVENT_ANNOUNCEMENT = "announcement"
EVENT_NEW_GRADE = "new_grade"
EVENT_MESSAGE = "message"  # géré par message_service (toujours in-app)


def _render_template(template: str | None, default: str, vars: dict[str, Any]) -> str:
    text = template or default
    for k, v in vars.items():
        text = text.replace(k, str(v))
    return text


async def _get_setting(db: AsyncSession, school_id: int, event_type: str) -> NotificationSetting | None:
    return (await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.school_id == school_id,
            NotificationSetting.event_type == event_type,
        )
    )).scalar_one_or_none()


async def notify_user(
    db: AsyncSession,
    school_id: int,
    recipient: User,
    event_type: str,
    subject: str,
    body: str,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
) -> Notification | None:
    """Crée une notification in-app pour un utilisateur.

    Respecte NotificationSetting (in_app_enabled). L'email serait envoyé
    via email_service si email_enabled et SMTP configuré (hors scope in-app).
    """
    if not recipient or not recipient.is_active:
        return None

    setting = await _get_setting(db, school_id, event_type)
    if setting and not setting.is_active:
        return None
    if setting and not setting.in_app_enabled:
        return None  # in-app désactivé pour cet événement

    notif = Notification(
        school_id=school_id,
        recipient_id=recipient.id,
        channel="in_app",
        category=event_type if event_type in (
            "absence", "payment_reminder", "grade_published", "announcement",
            "account_validation", "other",
        ) else "other",
        subject=subject,
        body=body,
        status="sent",
        is_read=False,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    db.add(notif)
    return notif


async def notify_users(
    db: AsyncSession,
    school_id: int,
    recipients: list[User],
    event_type: str,
    subject: str,
    body: str,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
) -> int:
    """Notifie une liste d'utilisateurs. Retourne le nombre de notifications créées."""
    count = 0
    for r in recipients:
        if await notify_user(db, school_id, r, event_type, subject, body,
                             related_entity_type, related_entity_id):
            count += 1
    return count


# ── Résolution de destinataires ──────────────────────────────────


async def get_parents_of_students(
    db: AsyncSession, school_id: int, student_ids: list[int]
) -> list[User]:
    """Parents (comptes users) liés aux élèves donnés, dans l'école."""
    if not student_ids:
        return []
    links = (await db.execute(
        select(ParentStudent).where(
            ParentStudent.school_id == school_id,
            ParentStudent.student_id.in_(student_ids),
        )
    )).scalars().all()
    parent_ids = list({l.parent_id for l in links})
    if not parent_ids:
        return []
    return list((await db.execute(
        select(User).where(
            User.id.in_(parent_ids),
            User.school_id == school_id,
            User.is_active == True,  # noqa: E712
        )
    )).scalars().all())


async def get_students_users(
    db: AsyncSession, school_id: int, student_ids: list[int]
) -> list[User]:
    """Comptes users (élèves) liés aux students donnés."""
    if not student_ids:
        return []
    from app.models.student import Student
    rows = (await db.execute(
        select(Student.user_id).where(
            Student.id.in_(student_ids),
            Student.school_id == school_id,
            Student.user_id.isnot(None),  # noqa: E711
        )
    )).scalars().all()
    user_ids = list({u for u in rows if u})
    if not user_ids:
        return []
    return list((await db.execute(
        select(User).where(
            User.id.in_(user_ids),
            User.school_id == school_id,
            User.is_active == True,  # noqa: E712
        )
    )).scalars().all())


async def get_class_students(db: AsyncSession, school_id: int, class_id: int) -> list[int]:
    """IDs des élèves actifs d'une classe."""
    from app.models.class_ import Enrollment
    return list((await db.execute(
        select(Enrollment.student_id).where(
            Enrollment.class_id == class_id,
            Enrollment.school_id == school_id,
            Enrollment.status == "active",
        )
    )).scalars().all())


async def get_school_role_users(
    db: AsyncSession, school_id: int, role_types: list[str]
) -> list[User]:
    """Tous les utilisateurs actifs d'une école ayant ces rôles."""
    return list((await db.execute(
        select(User).where(
            User.school_id == school_id,
            User.role_type.in_(role_types),
            User.is_active == True,  # noqa: E712
        )
    )).scalars().all())


# ── Helpers métier (hooks appelés depuis les autres modules) ─────


async def notify_bulletin_published(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    class_id: int,
    period_label: str,
    overall_average: float,
    bulletin_id: int,
) -> int:
    """À la publication d'un bulletin : notifie le(s) parent(s) et l'élève."""
    from app.models.student import Student
    from app.models.class_ import Class

    student = (await db.execute(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        return 0
    cls = (await db.execute(
        select(Class).where(Class.id == class_id)
    )).scalar_one_or_none()

    setting = await _get_setting(db, school_id, EVENT_BULLETIN_READY)
    vars = {
        "{nom_eleve}": student.last_name,
        "{prenom_eleve}": student.first_name,
        "{classe}": cls.name if cls else "",
        "{periode}": period_label,
        "{moyenne}": overall_average,
        "{ecole}": "",
    }
    default = f"Le bulletin {period_label} de {student.first_name} {student.last_name} ({cls.name if cls else ''}) est disponible. Moyenne : {overall_average}/20."
    body = _render_template(setting.message_template if setting else None, default, vars)

    count = 0
    parents = await get_parents_of_students(db, school_id, [student_id])
    count += await notify_users(
        db, school_id, parents, EVENT_BULLETIN_READY,
        f"Nouveau bulletin disponible — {period_label}", body,
        related_entity_type="bulletin", related_entity_id=bulletin_id,
    )
    student_users = await get_students_users(db, school_id, [student_id])
    count += await notify_users(
        db, school_id, student_users, EVENT_BULLETIN_READY,
        f"Votre bulletin {period_label} est disponible", body,
        related_entity_type="bulletin", related_entity_id=bulletin_id,
    )
    return count


async def notify_absence_recorded(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    date_str: str,
    attendance_id: int | None = None,
) -> int:
    """À l'enregistrement d'une absence : notifie le(s) parent(s)."""
    from app.models.student import Student

    student = (await db.execute(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        return 0

    setting = await _get_setting(db, school_id, EVENT_ABSENCE)
    vars = {
        "{nom_eleve}": student.last_name,
        "{prenom_eleve}": student.first_name,
        "{date}": date_str,
        "{ecole}": "",
    }
    default = f"Votre enfant {student.first_name} {student.last_name} a été absent le {date_str}."
    body = _render_template(setting.message_template if setting else None, default, vars)

    parents = await get_parents_of_students(db, school_id, [student_id])
    return await notify_users(
        db, school_id, parents, EVENT_ABSENCE,
        "Absence enregistrée", body,
        related_entity_type="attendance", related_entity_id=attendance_id,
    )


async def notify_payment_confirmation(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    amount: str,
    payment_id: int | None = None,
) -> int:
    """À l'enregistrement d'un paiement : confirme au(x) parent(s)."""
    from app.models.student import Student

    student = (await db.execute(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        return 0

    setting = await _get_setting(db, school_id, EVENT_PAYMENT_RECEIVED)
    vars = {
        "{nom_eleve}": student.last_name,
        "{prenom_eleve}": student.first_name,
        "{montant}": amount,
        "{date}": "",
        "{ecole}": "",
    }
    default = f"Votre paiement de {amount} FCFA pour {student.first_name} {student.last_name} a été enregistré. Merci."
    body = _render_template(setting.message_template if setting else None, default, vars)

    parents = await get_parents_of_students(db, school_id, [student_id])
    return await notify_users(
        db, school_id, parents, EVENT_PAYMENT_RECEIVED,
        "Paiement confirmé", body,
        related_entity_type="payment", related_entity_id=payment_id,
    )


async def notify_payment_reminder(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    balance: str,
    due_date: str | None = None,
) -> int:
    """Relance d'impayé : notifie le(s) parent(s) d'un solde restant."""
    from app.models.student import Student

    student = (await db.execute(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        return 0

    setting = await _get_setting(db, school_id, EVENT_PAYMENT_DUE)
    vars = {
        "{nom_eleve}": student.last_name,
        "{prenom_eleve}": student.first_name,
        "{montant}": balance,
        "{date}": due_date or "",
        "{ecole}": "",
    }
    default = f"Rappel : un solde de {balance} FCFA reste dû pour {student.first_name} {student.last_name}."
    if due_date:
        default += f" Merci de régulariser avant le {due_date}."
    body = _render_template(setting.message_template if setting else None, default, vars)

    parents = await get_parents_of_students(db, school_id, [student_id])
    return await notify_users(
        db, school_id, parents, EVENT_PAYMENT_DUE,
        "Rappel de paiement", body,
        related_entity_type="student", related_entity_id=student_id,
    )


async def notify_absence_justified(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    date_str: str,
) -> int:
    """Justification acceptée : notifie le(s) parent(s)."""
    from app.models.student import Student

    student = (await db.execute(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        return 0

    setting = await _get_setting(db, school_id, EVENT_ABSENCE)
    vars = {
        "{nom_eleve}": student.last_name,
        "{prenom_eleve}": student.first_name,
        "{date}": date_str,
        "{ecole}": "",
    }
    default = f"L'absence de {student.first_name} {student.last_name} du {date_str} a été justifiée et acceptée."
    body = _render_template(setting.message_template if setting else None, default, vars)

    parents = await get_parents_of_students(db, school_id, [student_id])
    return await notify_users(
        db, school_id, parents, EVENT_ABSENCE,
        "Absence justifiée", body,
        related_entity_type="attendance", related_entity_id=None,
    )
