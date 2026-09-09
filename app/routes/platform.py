"""Yiriba SaaS — Back-office éditeur (plateforme YIRIBA).

Toutes les routes sont réservées à l'éditeur (settings.PLATFORM_ADMIN_EMAILS).
Donne à l'éditeur la vue et le contrôle sur TOUTES les écoles :
résumé global, liste des écoles, détail, gel/dégel de l'accès,
réinitialisation du mot de passe directeur, journal d'audit global.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import hash_password
from app.middleware.rbac import require_platform_admin
from app.models.audit import AuditLog
from app.models.enums import StudentStatus
from app.models.platform import SubscriptionPayment, SupportRequest
from app.models.school import School
from app.models.student import Student
from app.models.subscription import Subscription, SubscriptionPlan, SubscriptionStatus
from app.models.user import User, UserRole, UserStatus
from app.services.platform_service import get_all_settings, get_setting, set_setting

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

    from app.models.class_ import Class as _Class
    class_count = (await db.execute(
        select(func.count()).select_from(_Class).where(_Class.school_id == school_id)
    )).scalar() or 0

    role_counts: dict[str, int] = {}
    for u in users:
        if u.is_active and u.status == UserStatus.ACTIVE:
            role_counts[u.role_type.value] = role_counts.get(u.role_type.value, 0) + 1

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
            "teacher_count": role_counts.get(UserRole.TEACHER.value, 0),
            "parent_count": role_counts.get(UserRole.PARENT.value, 0),
            "active_user_count": sum(role_counts.values()),
            "class_count": class_count,
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
    """GELER une école : plus AUCUN accès (login + sessions invalidées).

    - school.is_active = False → get_current_user et /auth/login renvoient 423
      à CHAQUE requête → les sessions actives sont coupées immédiatement.
    - Les données de l'école restent 100% conservées et visibles ici.
    """
    school = await _get_school(db, school_id)
    if not school.is_active:
        raise HTTPException(status_code=400, detail="Ecole déjà gelée")

    previous_status = school.subscription_status
    school.is_active = False

    from app.services.audit_service import log_action
    await log_action(
        db,
        school_id=school_id,
        user_id=user.id,
        action="platform.school.freeze",
        resource="school",
        resource_id=school_id,
        details={"previous_status": previous_status},
    )
    await db.commit()

    return {
        "school_id": school_id,
        "is_active": school.is_active,
        "message": (
            f"Accès de {school.name} gelé. Aucune donnée supprimée : "
            "l'école peut être réactivée à tout moment."
        ),
    }


@router.post("/schools/{school_id}/unfreeze", status_code=200)
async def unfreeze_school(
    school_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """RÉACTIVER une école gelée : l'accès est rétabli immédiatement,
    données intactes, statut d'abonnement conservé."""
    school = await _get_school(db, school_id)
    if school.is_active:
        raise HTTPException(status_code=400, detail="Ecole non gelée")

    school.is_active = True

    from app.services.audit_service import log_action
    await log_action(
        db,
        school_id=school_id,
        user_id=user.id,
        action="platform.school.unfreeze",
        resource="school",
        resource_id=school_id,
        details={},
    )
    await db.commit()

    return {
        "school_id": school_id,
        "is_active": school.is_active,
        "message": f"Accès de {school.name} rétabli. Les utilisateurs peuvent se reconnecter.",
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


# ── Gestion des données d'une école (interface admin dédiée) ─────


@router.get("/schools/{school_id}/data")
async def school_data_overview(
    school_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Comptage de TOUTES les données métier de l'école, table par table."""
    school = await _get_school(db, school_id)

    from app.models.attendance import Attendance
    from app.models.class_ import Class, Enrollment
    from app.models.grade import Grade
    from app.models.payment import FeeObligation, Payment

    async def count(model, *filters):
        q = select(func.count()).select_from(model).where(model.school_id == school_id)
        for f in filters:
            q = q.where(f)
        return (await db.execute(q)).scalar() or 0

    return {
        "school": {"id": school.id, "name": school.name, "slug": school.slug},
        "counts": {
            "students": await count(Student),
            "users": await count(User),
            "classes": await count(Class),
            "enrollments": await count(Enrollment),
            "grades": await count(Grade),
            "attendance": await count(Attendance),
            "obligations": await count(FeeObligation),
            "payments": await count(Payment),
        },
    }


@router.get("/schools/{school_id}/data/students")
async def school_data_students(
    school_id: int,
    q: str = Query(default="", max_length=120),
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Liste paginée des élèves de l'école (lecture seule, plateforme)."""
    await _get_school(db, school_id)

    query = select(Student).where(Student.school_id == school_id)
    total_q = select(func.count()).select_from(Student).where(Student.school_id == school_id)
    if q.strip():
        like = f"%{q.strip()}%"
        cond = or_(Student.first_name.ilike(like), Student.last_name.ilike(like), Student.matricule.ilike(like))
        query = query.where(cond)
        total_q = total_q.where(cond)
    if status:
        try:
            query = query.where(Student.status == StudentStatus(status))
            total_q = total_q.where(Student.status == StudentStatus(status))
        except ValueError:
            raise HTTPException(status_code=422, detail="Statut invalide")

    total = (await db.execute(total_q)).scalar() or 0
    rows = (await db.execute(
        query.order_by(Student.id).offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "students": [
            {
                "id": s.id,
                "first_name": s.first_name,
                "last_name": s.last_name,
                "matricule": s.matricule,
                "gender": s.gender,
                "birth_date": str(s.birth_date) if s.birth_date else None,
                "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                "created_at": str(s.created_at),
            }
            for s in rows
        ],
    }


@router.get("/schools/{school_id}/data/export")
async def school_data_export(
    school_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Export JSON complet des données de l'école (backup plateforme)."""
    import json

    from fastapi.responses import Response

    from app.models.attendance import Attendance
    from app.models.class_ import Class, Enrollment
    from app.models.grade import Grade
    from app.models.payment import FeeObligation, Payment

    school = await _get_school(db, school_id)

    def rows(model, fields):
        out = []
        # exécution synchrone impossible ici : on passe par une sous-fonction async
        return out

    async def fetch(model, fields):
        data = (await db.execute(
            select(model).where(model.school_id == school_id).order_by(model.id)
        )).scalars().all()
        return [
            {f: (str(getattr(r, f)) if getattr(r, f) is not None else None) for f in fields}
            for r in data
        ]

    payload = {
        "school": {
            "id": school.id, "name": school.name, "slug": school.slug,
            "short_name": school.short_name, "exported_at": datetime.now(UTC).isoformat(),
        },
        "students": await fetch(Student, ["id", "first_name", "last_name", "matricule", "gender", "birth_date", "status", "created_at"]),
        "users": await fetch(User, ["id", "email", "username", "first_name", "last_name", "role_type", "status", "created_at"]),
        "classes": await fetch(Class, ["id", "name", "level", "capacity", "created_at"]),
        "enrollments": await fetch(Enrollment, ["id", "student_id", "class_id", "academic_year", "status"]),
        "grades": await fetch(Grade, ["id", "student_id", "evaluation_id", "grade", "status", "entered_at"]),
        "attendance": await fetch(Attendance, ["id", "student_id", "class_id", "date", "status"]),
        "payments": await fetch(Payment, ["id", "student_id", "amount", "payment_method", "status", "paid_at"]),
        "obligations": await fetch(FeeObligation, ["id", "name", "amount", "category", "class_id"]),
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="platform.data_export", resource="school", resource_id=school_id, details={"format": "json"})
    await db.commit()
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=yiriba_export_ecole_{school_id}.json"},
    )


# ── Utilisateurs globaux (toutes écoles) ──────────────────────────


@router.get("/users")
async def platform_users(
    school_id: int | None = None,
    role: str | None = None,
    status: str | None = None,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Tous les utilisateurs de toutes les écoles, avec filtres."""
    query = select(User, School.name).join(School, School.id == User.school_id)
    count_q = select(func.count()).select_from(User)
    conds = []
    if school_id:
        conds.append(User.school_id == school_id)
    if role:
        try:
            conds.append(User.role_type == UserRole(role))
        except ValueError:
            raise HTTPException(status_code=422, detail="Rôle invalide")
    if status:
        try:
            conds.append(User.status == UserStatus(status))
        except ValueError:
            raise HTTPException(status_code=422, detail="Statut invalide")
    if q.strip():
        like = f"%{q.strip()}%"
        conds.append(or_(User.full_name.ilike(like), User.email.ilike(like), User.username.ilike(like)))
    for c in conds:
        query = query.where(c)
        count_q = count_q.where(c)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (await db.execute(
        query.order_by(User.created_at.desc()).offset(offset).limit(limit)
    )).all()

    return {
        "total": total,
        "count": len(rows),
        "users": [
            {
                "id": u.id,
                "full_name": u.full_name,
                "email": u.email,
                "username": u.username,
                "school_id": u.school_id,
                "school_name": school_name,
                "role_type": u.role_type.value,
                "status": u.status.value,
                "is_active": u.is_active,
                "last_login_at": str(u.last_login_at) if u.last_login_at else None,
            }
            for u, school_name in rows
        ],
    }


@router.post("/users/{user_id}/suspend", status_code=200)
async def platform_suspend_user(
    user_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Suspendre un utilisateur : plus de login, données conservées."""
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    settings = get_settings()
    if target.email and target.email.lower() in settings.platform_admin_emails:
        raise HTTPException(status_code=400, detail="Impossible de suspendre un compte YIRIBA")
    if target.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=400, detail="Utilisateur déjà suspendu")

    target.status = UserStatus.SUSPENDED
    from app.services.audit_service import log_action
    await log_action(db, school_id=target.school_id, user_id=user.id,
                     action="platform.user.suspend", resource="user", resource_id=target.id,
                     details={"email": target.email})
    await db.commit()
    return {"user_id": target.id, "status": target.status.value, "message": "Utilisateur suspendu."}


@router.post("/users/{user_id}/activate", status_code=200)
async def platform_activate_user(
    user_id: int,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Activer / réactiver un utilisateur (pending, suspended, rejected)."""
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if target.status == UserStatus.ACTIVE and target.is_active:
        raise HTTPException(status_code=400, detail="Utilisateur déjà actif")

    previous = target.status.value
    target.status = UserStatus.ACTIVE
    target.is_active = True
    target.failed_login_count = 0
    target.locked_until = None
    from app.services.audit_service import log_action
    await log_action(db, school_id=target.school_id, user_id=user.id,
                     action="platform.user.activate", resource="user", resource_id=target.id,
                     details={"previous_status": previous, "email": target.email})
    await db.commit()
    return {"user_id": target.id, "status": target.status.value, "message": "Utilisateur activé."}


# ── Abonnements (toutes écoles) ───────────────────────────────────


@router.get("/subscriptions")
async def platform_subscriptions(
    status: str | None = None,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Vue abonnements : ligne par école (forfait courant + statut)."""
    query = select(School).order_by(School.created_at.desc())
    count_q = select(func.count()).select_from(School)
    if q.strip():
        like = f"%{q.strip()}%"
        cond = or_(School.name.ilike(like), School.slug.ilike(like))
        query = query.where(cond)
        count_q = count_q.where(cond)

    total = (await db.execute(count_q)).scalar() or 0
    schools = (await db.execute(query.offset(offset).limit(limit))).scalars().all()

    now = datetime.now(UTC)
    soon = now + timedelta(days=30)
    items = []
    for s in schools:
        if status and s.subscription_status != status:
            continue
        st = s.subscription_status
        if st == SubscriptionStatus.ACTIVE.value and s.trial_ends_at \
                and s.trial_ends_at.replace(tzinfo=UTC) < soon:
            st = "expiring_soon"
        plan = await _current_plan(db, s)
        items.append({
            "school_id": s.id,
            "school_name": s.name,
            "plan_name": plan.name if plan else None,
            "plan_code": plan.code if plan else None,
            "status": st,
            "subscription_status": s.subscription_status,
            "started_at": str(s.created_at),
            "ends_at": str(s.trial_ends_at) if s.trial_ends_at else None,
            "amount": str(plan.price_per_student_year) if plan else "0",
            "is_frozen": not s.is_active,
        })

    return {"total": total, "count": len(items), "subscriptions": items}


@router.post("/schools/{school_id}/extend-subscription", status_code=200)
async def platform_extend_subscription(
    school_id: int,
    days: int = Query(..., ge=1, le=3650),
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Prolonger l'abonnement d'une école de N jours."""
    school = await _get_school(db, school_id)
    now = datetime.now(UTC)
    base = school.trial_ends_at.replace(tzinfo=UTC) if school.trial_ends_at \
        and school.trial_ends_at.replace(tzinfo=UTC) > now else now
    school.trial_ends_at = base + timedelta(days=days)
    if school.subscription_status in (
        SubscriptionStatus.EXPIRED.value, SubscriptionStatus.CANCELLED.value
    ):
        school.subscription_status = SubscriptionStatus.ACTIVE.value

    from app.services.audit_service import log_action
    await log_action(db, school_id=school_id, user_id=user.id,
                     action="platform.subscription.extend", resource="school",
                     resource_id=school_id, details={"days": days, "new_end": str(school.trial_ends_at)})
    await db.commit()
    return {
        "school_id": school_id,
        "ends_at": str(school.trial_ends_at),
        "message": f"Abonnement prolongé de {days} jours (jusqu'au {school.trial_ends_at.date()}).",
    }


# ── Paiements d'abonnement (école → YIRIBA) ───────────────────────


@router.get("/payments")
async def platform_payments(
    school_id: int | None = None,
    status: str | None = None,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Paiements d'abonnement des écoles à YIRIBA (pas la scolarité)."""
    query = select(SubscriptionPayment, School.name).join(
        School, School.id == SubscriptionPayment.school_id
    )
    count_q = select(func.count()).select_from(SubscriptionPayment)
    conds = []
    if school_id:
        conds.append(SubscriptionPayment.school_id == school_id)
    if status:
        if status not in ("paid", "pending", "failed", "refunded"):
            raise HTTPException(status_code=422, detail="Statut invalide")
        conds.append(SubscriptionPayment.status == status)
    if q.strip():
        like = f"%{q.strip()}%"
        conds.append(SubscriptionPayment.reference.ilike(like))
    for c in conds:
        query = query.where(c)
        count_q = count_q.where(c)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (await db.execute(
        query.order_by(SubscriptionPayment.created_at.desc())
        .offset(offset).limit(limit)
    )).all()
    return {
        "total": total,
        "count": len(rows),
        "payments": [
            {
                "id": p.id,
                "school_id": p.school_id,
                "school_name": school_name,
                "reference": p.reference,
                "amount": str(p.amount),
                "currency": p.currency,
                "method": p.method,
                "status": p.status,
                "paid_at": str(p.paid_at) if p.paid_at else None,
                "note": p.note,
            }
            for p, school_name in rows
        ],
    }


@router.post("/payments", status_code=201)
async def platform_create_payment(
    payload: dict,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Enregistrer manuellement un paiement d'abonnement d'une école."""
    school_id = payload.get("school_id")
    try:
        amount = Decimal(str(payload.get("amount")))
        assert amount > 0
    except Exception:
        raise HTTPException(status_code=422, detail="Montant invalide")
    school = await _get_school(db, school_id)
    status = payload.get("status", "paid")
    if status not in ("paid", "pending", "failed", "refunded"):
        raise HTTPException(status_code=422, detail="Statut invalide")
    method = payload.get("method", "transfer")
    if method not in ("cash", "transfer", "mobile_money", "check", "other"):
        raise HTTPException(status_code=422, detail="Moyen de paiement invalide")

    ref = (payload.get("reference") or "").strip() or \
        f"SUB-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    if (await db.execute(
        select(SubscriptionPayment).where(SubscriptionPayment.reference == ref)
    )).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Référence déjà utilisée")

    pay = SubscriptionPayment(
        school_id=school.id,
        reference=ref,
        amount=amount,
        currency=payload.get("currency", "XOF"),
        method=method,
        status=status,
        paid_at=datetime.now(UTC) if status == "paid" else None,
        note=payload.get("note"),
        recorded_by=user.id,
    )
    db.add(pay)
    from app.services.audit_service import log_action
    await log_action(db, school_id=school.id, user_id=user.id,
                     action="platform.payment.create", resource="subscription_payment",
                     resource_id=None, details={"reference": ref, "amount": str(amount)})
    await db.commit()
    return {"id": pay.id, "reference": ref, "message": "Paiement enregistré."}


# ── Support (demandes des écoles) ─────────────────────────────────


@router.get("/support")
async def platform_support(
    status: str | None = None,
    school_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = select(SupportRequest, School.name).join(
        School, School.id == SupportRequest.school_id
    )
    count_q = select(func.count()).select_from(SupportRequest)
    conds = []
    if status:
        if status not in ("new", "in_progress", "resolved"):
            raise HTTPException(status_code=422, detail="Statut invalide")
        conds.append(SupportRequest.status == status)
    if school_id:
        conds.append(SupportRequest.school_id == school_id)
    for c in conds:
        query = query.where(c)
        count_q = count_q.where(c)
    total = (await db.execute(count_q)).scalar() or 0
    rows = (await db.execute(
        query.order_by(SupportRequest.created_at.desc()).offset(offset).limit(limit)
    )).all()
    return {
        "total": total,
        "count": len(rows),
        "requests": [
            {
                "id": r.id,
                "school_id": r.school_id,
                "school_name": school_name,
                "subject": r.subject,
                "message": r.message,
                "phone": r.phone,
                "priority": r.priority,
                "status": r.status,
                "response": r.response,
                "is_read": r.is_read,
                "created_at": str(r.created_at),
            }
            for r, school_name in rows
        ],
    }


@router.patch("/support/{request_id}", status_code=200)
async def platform_update_support(
    request_id: int,
    payload: dict,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mettre à jour une demande : statut, réponse, marquer lue."""
    req = (await db.execute(
        select(SupportRequest).where(SupportRequest.id == request_id)
    )).scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Demande introuvable")

    if "status" in payload:
        if payload["status"] not in ("new", "in_progress", "resolved"):
            raise HTTPException(status_code=422, detail="Statut invalide")
        req.status = payload["status"]
    if "response" in payload:
        req.response = payload["response"]
        req.responded_by = user.id
        req.responded_at = datetime.now(UTC)
        req.status = "in_progress" if req.status == "new" else req.status
    if "is_read" in payload:
        req.is_read = bool(payload["is_read"])

    from app.services.audit_service import log_action
    await log_action(db, school_id=req.school_id, user_id=user.id,
                     action="platform.support.update", resource="support_request",
                     resource_id=req.id, details={"status": req.status})
    await db.commit()
    return {"id": req.id, "status": req.status, "is_read": req.is_read}


# ── Notifications Super Admin ─────────────────────────────────────


def _parse_dt(value: str) -> datetime:
    """Parse une date ISO générée par str()/isoformat(), tolérant."""
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=UTC)


async def _platform_notifications(db: AsyncSession) -> list[dict]:
    """Construit les alertes plateforme à partir des données réelles."""
    now = datetime.now(UTC)
    soon = now + timedelta(days=15)
    items: list[dict] = []

    # Demandes de support non lues
    unread = (await db.execute(
        select(SupportRequest).where(SupportRequest.is_read.is_(False))
    )).scalars().all()
    for r in unread:
        items.append({
            "type": "support",
            "title": f"Demande de support : {r.subject}",
            "created_at": str(r.created_at),
            "link": f"support:{r.id}",
        })

    # Abonnements expirant bientôt
    expiring = (await db.execute(
        select(School).where(
            School.is_active.is_(True),
            School.subscription_status == SubscriptionStatus.ACTIVE.value,
            School.trial_ends_at.is_not(None),
            School.trial_ends_at < soon,
        )
    )).scalars().all()
    for s in expiring:
        days = max(0, (s.trial_ends_at.replace(tzinfo=UTC) - now).days)
        items.append({
            "type": "subscription_expiring",
            "title": f"Abonnement expirant : {s.name} ({days} j)",
            "created_at": str(s.trial_ends_at),
            "link": f"school:{s.id}",
        })

    # Écoles gelées
    frozen = (await db.execute(
        select(School).where(School.is_active.is_(False))
    )).scalars().all()
    for s in frozen:
        items.append({
            "type": "school_frozen",
            "title": f"École gelée : {s.name}",
            "created_at": str(s.updated_at) if s.updated_at else None,
            "link": f"school:{s.id}",
        })
    return items


@router.get("/notifications")
async def platform_notifications(
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items = await _platform_notifications(db)
    read_at_s = await get_setting(db, "notifications_read_at", None)
    read_at = datetime.fromisoformat(read_at_s) if read_at_s else None
    out = []
    for it in items:
        it["is_read"] = bool(
            read_at and it.get("created_at")
            and _parse_dt(it["created_at"]) <= read_at
        )
        out.append(it)
    unread_count = sum(1 for it in out if not it["is_read"])
    return {"count": len(out), "unread": unread_count, "notifications": out}


@router.post("/notifications/mark-read", status_code=200)
async def platform_notifications_read(
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await set_setting(db, "notifications_read_at", datetime.now(UTC).isoformat(), user.id)
    await db.commit()
    return {"message": "Notifications marquées comme lues."}


# ── Paramètres Super Admin (mode maintenance inclus) ─────────────


@router.get("/settings")
async def platform_get_settings(
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = await get_all_settings(db)
    return {
        "platform_name": settings.get("platform_name") or "YIRIBA",
        "contact_email": settings.get("contact_email") or "contact@yiriba.com",
        "maintenance_mode": (settings.get("maintenance_mode") or "false").lower() == "true",
    }


@router.patch("/settings", status_code=200)
async def platform_update_settings(
    payload: dict,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Modifier nom plateforme, email contact, mode maintenance."""
    if "platform_name" in payload:
        name = (payload["platform_name"] or "YIRIBA").strip()
        if not (1 <= len(name) <= 100):
            raise HTTPException(status_code=422, detail="Nom de plateforme invalide")
        await set_setting(db, "platform_name", name, user.id)
    if "contact_email" in payload:
        email = (payload["contact_email"] or "").strip().lower()
        if email and "@" not in email:
            raise HTTPException(status_code=422, detail="Email de contact invalide")
        await set_setting(db, "contact_email", email or None, user.id)
    if "maintenance_mode" in payload:
        val = "true" if payload["maintenance_mode"] else "false"
        await set_setting(db, "maintenance_mode", val, user.id)
        if user.school_id is not None:
            from app.services.audit_service import log_action
            await log_action(db, school_id=user.school_id, user_id=user.id,
                             action="platform.maintenance.set", resource="platform_setting",
                             resource_id=None, details={"maintenance_mode": val})
    await db.commit()
    return await platform_get_settings(user=user, db=db)
