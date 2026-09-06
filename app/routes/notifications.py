"""Yiriba SaaS — Notification center routes: list, mark read, unread count."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_current_user, get_school_id, require_permission
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class MarkRead(BaseModel):
    notification_ids: list[int] | None = None  # None = mark all as read


@router.get("/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get count of unread in-app notifications for the current user."""
    school_id = get_school_id(user)
    count = (await db.execute(
        select(func.count(Notification.id)).where(
            Notification.school_id == school_id,
            Notification.recipient_id == user.id,
            Notification.is_read == False,  # noqa: E712
            Notification.channel == "in_app",
        )
    )).scalar() or 0
    return {"unread_count": count}


@router.get("")
async def list_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List in-app notifications for the current user, paginated."""
    school_id = get_school_id(user)

    total = (await db.execute(
        select(func.count(Notification.id)).where(
            Notification.school_id == school_id,
            Notification.recipient_id == user.id,
            Notification.channel == "in_app",
        )
    )).scalar() or 0

    result = await db.execute(
        select(Notification).where(
            Notification.school_id == school_id,
            Notification.recipient_id == user.id,
            Notification.channel == "in_app",
        ).order_by(Notification.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    notifications = result.scalars().all()

    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.category.value if hasattr(n.category, 'value') else n.category,
                "title": n.subject or "",
                "body": n.body,
                "is_read": n.is_read,
                "related_entity_type": n.related_entity_type,
                "related_entity_id": n.related_entity_id,
                "created_at": n.created_at.isoformat() if n.created_at else "",
            }
            for n in notifications
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/mark-read")
async def mark_notifications_read(
    data: MarkRead,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark notifications as read. If notification_ids is None, mark all as read."""
    school_id = get_school_id(user)

    query = update(Notification).where(
        Notification.school_id == school_id,
        Notification.recipient_id == user.id,
        Notification.is_read == False,  # noqa: E712
        Notification.channel == "in_app",
    )

    if data.notification_ids:
        query = query.where(Notification.id.in_(data.notification_ids))

    query = query.values(is_read=True)
    await db.execute(query)
    await db.commit()

    return {"message": "Notifications marquees comme lues"}


# ── Filtres avancés (type, statut de lecture, recherche) ─────────


@router.get("/search")
async def search_notifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    type: str | None = Query(None),
    read: str | None = Query(None, pattern="^(true|false)$"),
    q: str | None = Query(None, max_length=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Centre de notifications avec filtres : type, lu/non-lu, recherche texte."""
    import math
    school_id = get_school_id(user)

    conditions = [
        Notification.school_id == school_id,
        Notification.recipient_id == user.id,
        Notification.channel == "in_app",
    ]
    if type:
        conditions.append(Notification.category == type)
    if read == "true":
        conditions.append(Notification.is_read == True)  # noqa: E712
    elif read == "false":
        conditions.append(Notification.is_read == False)  # noqa: E712
    if q:
        conditions.append(
            (Notification.subject.ilike(f"%{q}%")) | (Notification.body.ilike(f"%{q}%"))
        )

    total = (await db.execute(
        select(func.count(Notification.id)).where(*conditions)
    )).scalar() or 0
    rows = (await db.execute(
        select(Notification).where(*conditions)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()

    unread_total = (await db.execute(
        select(func.count(Notification.id)).where(
            Notification.school_id == school_id,
            Notification.recipient_id == user.id,
            Notification.channel == "in_app",
            Notification.is_read == False,  # noqa: E712
        )
    )).scalar() or 0

    return {
        "notifications": [_notif_out(n) for n in rows],
        "total": total, "unread_total": unread_total,
        "page": page, "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


def _notif_out(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.category.value if hasattr(n.category, "value") else n.category,
        "title": n.subject or "",
        "body": n.body,
        "is_read": n.is_read,
        "related_entity_type": n.related_entity_type,
        "related_entity_id": n.related_entity_id,
        "created_at": n.created_at.isoformat() if n.created_at else "",
    }


# ── Annonces (admin) ─────────────────────────────────────────────


class AnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=5000)
    # cibles : all_parents | all_students | all_teachers | everyone
    #          class_parents:<id> | class_students:<id> | users:<1,2,3>
    targets: list[str] = Field(..., min_length=1)
    expires_at: str | None = Field(None, max_length=30)


@router.post("/announcements", status_code=201)
async def create_announcement(
    data: AnnouncementCreate,
    user: User = Depends(require_permission("message.send")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Crée une annonce et notifie les destinataires ciblés.

    Réservé à l'administration (admin/directeur/secrétaire).
    """
    school_id = get_school_id(user)
    role = (user.role_type or "").lower()
    if role not in ("admin", "directeur", "secretaire"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration")

    from app.services import notification_service as ns

    recipients: list = []
    class_ids: list[int] = []
    user_ids: list[int] = []

    for t in data.targets:
        if t == "all_parents":
            recipients += await ns.get_school_role_users(db, school_id, ["parent"])
        elif t == "all_students":
            recipients += await ns.get_school_role_users(db, school_id, ["student"])
        elif t == "all_teachers":
            recipients += await ns.get_school_role_users(db, school_id, ["teacher"])
        elif t == "everyone":
            recipients += await ns.get_school_role_users(
                db, school_id, ["parent", "student", "teacher", "educator", "secretary", "comptable"],
            )
        elif t.startswith("class_parents:"):
            cid = int(t.split(":")[1])
            class_ids.append(cid)
            sids = await ns.get_class_students(db, school_id, cid)
            recipients += await ns.get_parents_of_students(db, school_id, sids)
        elif t.startswith("class_students:"):
            cid = int(t.split(":")[1])
            class_ids.append(cid)
            sids = await ns.get_class_students(db, school_id, cid)
            recipients += await ns.get_students_users(db, school_id, sids)
        elif t.startswith("users:"):
            user_ids += [int(x) for x in t.split(":")[1].split(",") if x]
        else:
            raise HTTPException(status_code=400, detail=f"Cible inconnue : {t}")

    if user_ids:
        rows = (await db.execute(
            select(User).where(
                User.id.in_(user_ids), User.school_id == school_id,
                User.is_active == True,  # noqa: E712
            )
        )).scalars().all()
        recipients += list(rows)

    # Dédupliquer
    seen = set()
    unique_recipients = []
    for r in recipients:
        if r.id not in seen:
            seen.add(r.id)
            unique_recipients.append(r)

    sent = await ns.notify_users(
        db, school_id, unique_recipients, ns.EVENT_ANNOUNCEMENT,
        data.title, data.content,
        related_entity_type="announcement",
    )
    await db.commit()

    from app.services.audit_service import safe_audit
    await safe_audit(
        db, school_id=school_id, user_id=user.id,
        action="announcement.create", resource="announcement",
        details={"title": data.title, "targets": data.targets, "recipients": sent},
    )
    return {"recipients": sent, "title": data.title}


# ── Préférences de notifications (par utilisateur) ───────────────


@router.get("/preferences")
async def get_preferences(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Préférences de l'utilisateur : liste des événements et leur activation."""
    from app.models.notification_setting import NotificationSetting as NS

    events = [
        {"key": "bulletin_ready", "label": "Bulletin disponible"},
        {"key": "absence", "label": "Absence de l'élève"},
        {"key": "payment_due", "label": "Rappel d'échéance de paiement"},
        {"key": "payment_received", "label": "Confirmation de paiement"},
        {"key": "announcement", "label": "Annonces de l'établissement"},
        {"key": "new_grade", "label": "Nouvelle note publiée"},
    ]
    # Les réglages école servent de base ; l'utilisateur peut les affiner via user_prefs
    rows = (await db.execute(
        select(NS).where(NS.school_id == get_school_id(user))
    )).scalars().all()
    by_event = {r.event_type: r for r in rows}
    return {
        "events": [
            {
                **e,
                "in_app": by_event[e["key"]].in_app_enabled if e["key"] in by_event else True,
                "email": by_event[e["key"]].email_enabled if e["key"] in by_event else False,
                "exists": e["key"] in by_event,
            }
            for e in events
        ]
    }


class PreferenceUpdate(BaseModel):
    event_key: str = Field(..., max_length=50)
    in_app: bool | None = None
    email: bool | None = None
    is_active: bool | None = None


@router.put("/preferences")
async def update_preference(
    data: PreferenceUpdate,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Met à jour le réglage d'un événement (niveau école — réservé admin)."""
    from app.models.notification_setting import NotificationSetting as NS

    school_id = get_school_id(user)
    row = (await db.execute(
        select(NS).where(NS.school_id == school_id, NS.event_type == data.event_key)
    )).scalar_one_or_none()
    if not row:
        row = NS(school_id=school_id, event_type=data.event_key)
        db.add(row)
    if data.in_app is not None:
        row.in_app_enabled = data.in_app
    if data.email is not None:
        row.email_enabled = data.email
    if data.is_active is not None:
        row.is_active = data.is_active
    await db.commit()

    from app.services.audit_service import safe_audit
    await safe_audit(
        db, school_id=school_id, user_id=user.id,
        action="notification.settings.update", resource="notification_setting",
        details={"event": data.event_key, "in_app": data.in_app, "email": data.email},
    )
    return {"ok": True, "event": data.event_key}
