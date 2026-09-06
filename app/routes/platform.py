"""Yiriba SaaS — Back-office éditeur (plateforme YIRIBA).

Toutes les routes sont réservées à l'éditeur (settings.PLATFORM_ADMIN_EMAILS).
Donne à l'éditeur la vue et le contrôle sur TOUTES les écoles :
résumé global, liste des écoles, détail, gel/dégel de l'accès,
réinitialisation du mot de passe directeur, journal d'audit global.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password
from app.middleware.rbac import require_platform_admin
from app.models.audit import AuditLog
from app.models.enums import StudentStatus
from app.models.school import School
from app.models.student import Student
from app.models.subscription import Subscription, SubscriptionPlan, SubscriptionStatus
from app.models.user import User, UserRole, UserStatus

router = APIRouter(prefix="/api/platform", tags=["platform"])


# ── Helpers ───────────────────────────────────────────────────────


def _trial_expired(school: School) -> bool:
    if school.subscription_status != SubscriptionStatus.TRIAL.value:
        return False
    if school.trial_ends_at is None:
        return False
    return school.trial_ends_at.replace(tzinfo=UTC) < datetime.now(UTC)


async def _access_level(school: School) -> str:
    if school.subscription_status in (
        SubscriptionStatus.EXPIRED.value, SubscriptionStatus.CANCELLED.value
    ):
        return "read_only"
    if school.subscription_status == SubscriptionStatus.ACTIVE.value:
        return "full_access"
    if _trial_expired(school):
        return "read_only"
    return "full_access"


async def _school_counts(db: AsyncSession) -> tuple[dict[int, int], dict[int, int]]:
    """Retourne (students_by_school, users_by_school) en 2 requêtes groupées."""
    student_rows = (await db.execute(
        select(Student.school_id, func.count())
        .where(Student.status == StudentStatus.ACTIVE)
        .group_by(Student.school_id)
    )).all()
    user_rows = (await db.execute(
        select(User.school_id, func.count())
        .where(User.status == UserStatus.ACTIVE, User.is_active.is_(True))
        .group_by(User.school_id)
    )).all()
    students_by_school = dict(student_rows)
    users_by_school = dict(user_rows)
    return students_by_school, users_by_school


async def _current_plan(db: AsyncSession, school: School) -> SubscriptionPlan | None:
    if not school.current_plan_id:
        return None
    return (await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == school.current_plan_id)
    )).scalar_one_or_none()


# ── Résumé global ─────────────────────────────────────────────────


@router.get("/summary")
async def platform_summary(
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Indicateurs globaux de la plateforme (toutes écoles confondues)."""
    schools = (await db.execute(select(School))).scalars().all()

    now = datetime.now(UTC)
    status_counts: dict[str, int] = {s.value: 0 for s in SubscriptionStatus}
    expired_trials = 0
    for school in schools:
        prev = status_counts.get(school.subscription_status, 0)
        status_counts[school.subscription_status] = prev + 1
        if _trial_expired(school):
            expired_trials += 1

    total_students = (await db.execute(
        select(func.count()).select_from(Student).where(Student.status == StudentStatus.ACTIVE)
    )).scalar() or 0

    total_users = (await db.execute(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )).scalar() or 0

    active_amount = (await db.execute(
        select(func.coalesce(func.sum(Subscription.amount), 0)).where(
            Subscription.status == SubscriptionStatus.ACTIVE
        )
    )).scalar() or 0

    recent = (await db.execute(
        select(School).order_by(School.created_at.desc()).limit(5)
    )).scalars().all()

    return {
        "total_schools": len(schools),
        "active_schools": status_counts.get(SubscriptionStatus.ACTIVE.value, 0),
        "trial_schools": status_counts.get(SubscriptionStatus.TRIAL.value, 0),
        "expired_schools": status_counts.get(SubscriptionStatus.EXPIRED.value, 0)
        + status_counts.get(SubscriptionStatus.CANCELLED.value, 0),
        "expired_trials": expired_trials,
        "total_students": total_students,
        "total_users": total_users,
        "active_subscriptions_amount": str(active_amount),
        "recent_schools": [
            {
                "id": s.id,
                "name": s.name,
                "slug": s.slug,
                "subscription_status": s.subscription_status,
                "created_at": str(s.created_at),
            }
            for s in recent
        ],
        "as_of": now.isoformat(),
    }


# ── Liste des écoles ──────────────────────────────────────────────


@router.get("/schools")
async def list_schools(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Toutes les écoles avec statut d'abonnement, plan, compteurs, accès."""
    query = select(School)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(
            School.name.ilike(like),
            School.slug.ilike(like),
            School.city.ilike(like),
        )).order_by(School.created_at.desc())
    else:
        query = query.order_by(School.created_at.desc())

    schools = (await db.execute(query.offset(offset).limit(limit))).scalars().all()
    total = (await db.execute(
        select(func.count()).select_from(School)
    )).scalar() or 0

    students_by_school, users_by_school = await _school_counts(db)

    return {
        "total": total,
        "count": len(schools),
        "schools": [
            {
                "id": s.id,
                "name": s.name,
                "slug": s.slug,
                "short_name": s.short_name,
                "school_type": s.school_type,
                "city": s.city,
                "country": s.country,
                "is_active": s.is_active,
                "created_at": str(s.created_at),
                "subscription_status": s.subscription_status,
                "trial_ends_at": str(s.trial_ends_at) if s.trial_ends_at else None,
                "access_level": await _access_level(s),
                "student_count": students_by_school.get(s.id, 0),
                "user_count": users_by_school.get(s.id, 0),
                "current_plan": await _current_plan_name(db, s),
            }
            for s in schools
        ],
    }


async def _current_plan_name(db: AsyncSession, school: School) -> dict | None:
    plan = await _current_plan(db, school)
    if not plan:
        return None
    return {
        "name": plan.name,
        "code": plan.code,
        "max_students": plan.max_students,
        "price_per_student_year": str(plan.price_per_student_year),
    }


# ── Détail d'une école ────────────────────────────────────────────


@router.get("/schools/{school_id}")
async def school_detail(
    school_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Vue complète : profil, plan, historique, utilisateurs, audit récent."""
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")

    plan = await _current_plan(db, school)

    subscriptions = (await db.execute(
        select(Subscription).where(Subscription.school_id == school_id)
        .order_by(Subscription.created_at.desc())
    )).scalars().all()

    users = (await db.execute(
        select(User).where(User.school_id == school_id).order_by(User.created_at)
    )).scalars().all()

    audits = (await db.execute(
        select(AuditLog).where(AuditLog.school_id == school_id)
        .order_by(AuditLog.created_at.desc()).limit(20)
    )).scalars().all()

    student_count = (await db.execute(
        select(func.count()).select_from(Student).where(
            Student.school_id == school_id,
            Student.status == StudentStatus.ACTIVE,
        )
    )).scalar() or 0

    users_by_id = {u.id: u for u in users}

    return {
        "school": {
            "id": school.id,
            "name": school.name,
            "slug": school.slug,
            "short_name": school.short_name,
            "school_type": school.school_type,
            "email": school.email,
            "phone": school.phone,
            "city": school.city,
            "country": school.country,
            "address": school.address,
            "is_active": school.is_active,
            "created_at": str(school.created_at),
            "subscription_status": school.subscription_status,
            "trial_ends_at": str(school.trial_ends_at) if school.trial_ends_at else None,
            "access_level": await _access_level(school),
            "student_count": student_count,
            "plan": {
                "name": plan.name,
                "code": plan.code,
                "max_students": plan.max_students,
                "price_per_student_year": str(plan.price_per_student_year),
                "features": plan.features,
            } if plan else None,
        },
        "subscriptions": [
            {
                "id": sub.id,
                "status": sub.status.value if hasattr(sub.status, "value") else sub.status,
                "started_at": str(sub.started_at),
                "ends_at": str(sub.ends_at) if sub.ends_at else None,
                "amount": str(sub.amount),
                "student_count_at_billing": sub.student_count_at_billing,
                "plan_code": (await _plan_code(db, sub.plan_id)),
            }
            for sub in subscriptions
        ],
        "users": [
            {
                "id": u.id,
                "full_name": u.full_name,
                "email": u.email,
                "role_type": u.role_type.value,
                "status": u.status.value,
                "is_active": u.is_active,
                "last_login_at": str(u.last_login_at) if u.last_login_at else None,
            }
            for u in users
        ],
        "audit": [
            {
                "action": a.action,
                "resource": a.resource,
                "details": a.details,
                "created_at": str(a.created_at),
                "actor": users_by_id[a.user_id].full_name if a.user_id in users_by_id else None,
            }
            for a in audits
        ],
    }


async def _plan_code(db: AsyncSession, plan_id: int) -> str | None:
    plan = (await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )).scalar_one_or_none()
    return plan.code if plan else None


# ── Gel / dégel d'accès ───────────────────────────────────────────


@router.post("/schools/{school_id}/freeze", status_code=200)
async def freeze_school(
    school_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Couper l'accès en écriture d'une école (lecture seule).

    L'école passe en 'expired' : les écritures sont bloquées par
    require_write_access, ses données restent lisibles.
    """
    school = await _get_school(db, school_id)
    if school.subscription_status == SubscriptionStatus.EXPIRED.value:
        raise HTTPException(status_code=400, detail="Ecole déjà gelée")

    school.subscription_status = SubscriptionStatus.EXPIRED.value
    school.trial_ends_at = None

    from app.services.audit_service import log_action
    await log_action(
        db,
        school_id=school_id,
        user_id=user.id,
        action="platform.school.freeze",
        resource="school",
        resource_id=school_id,
        details={"previous_status": school.subscription_status},
    )
    await db.commit()

    return {
        "school_id": school_id,
        "status": school.subscription_status,
        "message": f"Accès en écriture de {school.name} coupé (lecture seule).",
    }


@router.post("/schools/{school_id}/unfreeze", status_code=200)
async def unfreeze_school(
    school_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rétablir l'accès en écriture d'une école (nouvel essai du plan actuel)."""
    school = await _get_school(db, school_id)
    if school.subscription_status not in (
        SubscriptionStatus.EXPIRED.value, SubscriptionStatus.CANCELLED.value
    ):
        raise HTTPException(status_code=400, detail="Ecole non gelée")

    plan = await _current_plan(db, school)
    trial_days = plan.trial_days if plan and plan.trial_days else 90

    school.subscription_status = SubscriptionStatus.TRIAL.value
    school.trial_ends_at = datetime.now(UTC) + timedelta(days=trial_days)

    from app.services.audit_service import log_action
    await log_action(
        db,
        school_id=school_id,
        user_id=user.id,
        action="platform.school.unfreeze",
        resource="school",
        resource_id=school_id,
        details={"trial_days": trial_days, "trial_ends_at": str(school.trial_ends_at)},
    )
    await db.commit()

    return {
        "school_id": school_id,
        "status": school.subscription_status,
        "trial_ends_at": str(school.trial_ends_at),
        "message": f"Accès en écriture de {school.name} rétabli (essai de {trial_days} jours).",
    }


# ── Réinitialisation du mot de passe du directeur ─────────────────


@router.post("/schools/{school_id}/reset-admin-password", status_code=200)
async def reset_admin_password(
    school_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Réinitialiser le mot de passe d'un admin d'école (déverrouille aussi).

    Retourne le mot de passe temporaire : l'éditeur le transmet à l'école.
    A la premiere connexion, l'admin devra le changer.
    """
    from app.services.student_service import generate_temp_password

    school = await _get_school(db, school_id)

    admin = (await db.execute(
        select(User).where(
            User.school_id == school_id,
            User.role_type == UserRole.ADMIN,
        ).order_by(User.created_at).limit(1)
    )).scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="Aucun compte admin pour cette ecole")

    temp_password = generate_temp_password()
    admin.password_hash = hash_password(temp_password)
    admin.must_change_password = True
    admin.temp_password_displayed = False
    admin.failed_login_count = 0
    admin.locked_until = None

    from app.services.audit_service import log_action
    await log_action(
        db,
        school_id=school_id,
        user_id=user.id,
        action="platform.admin_password_reset",
        resource="user",
        resource_id=admin.id,
        details={"admin_email": admin.email},
    )
    await db.commit()

    return {
        "school_id": school_id,
        "school_name": school.name,
        "admin_email": admin.email,
        "temp_password": temp_password,
        "message": (
            "Mot de passe temporaire généré. "
            "L'admin devra le changer à la prochaine connexion."
        ),
    }


# ── Journal d'audit global ────────────────────────────────────────


@router.get("/audit")
async def platform_audit(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=120),
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dernières actions sensibles sur toutes les écoles."""
    query = (
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(offset).limit(limit)
    )
    if q.strip():
        query = (
            select(AuditLog, School.name)
            .join(School, School.id == AuditLog.school_id)
            .where(or_(
                AuditLog.action.ilike(f"%{q.strip()}%"),
                School.name.ilike(f"%{q.strip()}%"),
            ))
            .order_by(AuditLog.created_at.desc())
            .offset(offset).limit(limit)
        )
        rows = (await db.execute(query)).all()
        items = [
            {
                "id": a.id,
                "school_id": a.school_id,
                "school_name": school_name,
                "action": a.action,
                "resource": a.resource,
                "details": a.details,
                "created_at": str(a.created_at),
                "actor_id": a.user_id,
            }
            for a, school_name in rows
        ]
    else:
        audit_logs = (await db.execute(query)).scalars().all()
        school_ids = {a.school_id for a in audit_logs}
        school_names = {}
        if school_ids:
            school_rows = (await db.execute(
                select(School.id, School.name).where(School.id.in_(school_ids))
            )).all()
            school_names = dict(school_rows)
        items = [
            {
                "id": a.id,
                "school_id": a.school_id,
                "school_name": school_names.get(a.school_id),
                "action": a.action,
                "resource": a.resource,
                "details": a.details,
                "created_at": str(a.created_at),
                "actor_id": a.user_id,
            }
            for a in audit_logs
        ]

    return {
        "count": len(items),
        "logs": items,
    }


async def _get_school(db: AsyncSession, school_id: int) -> School:
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")
    return school
