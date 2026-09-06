"""Yiriba SaaS — Subscription routes.

Gestion des forfaits (plans) et des abonnements.
Toutes les operations sont isolees par school_id.
"""

import json
import math
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_platform_admin, require_permission
from app.models.school import School
from app.models.student import Student
from app.models.enums import StudentStatus
from app.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.models.user import User

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


# ── Schemas ───────────────────────────────────────────────────────


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    max_students: int | None = None  # NULL = illimite
    trial_days: int | None = Field(default=None, ge=0)
    price_per_student_year: str | None = None  # Decimal string
    features: str | None = None  # JSON string
    is_active: bool | None = None


class SubscriptionActivate(BaseModel):
    plan_code: str  # "racine" ou "baobab"
    custom_price_per_student: str | None = None  # Pour Baobab
    custom_amount: str | None = None  # Montant forfaitaire negocie


class ChangePlanRequest(BaseModel):
    """Schema pour changer de forfait."""
    plan_code: str = Field(..., pattern="^(graine|racine|baobab)$")
    # Baobab uniquement :
    custom_price_per_student: str | None = None  # Tarif negocie par eleve
    custom_amount: str | None = None  # Montant forfaitaire negocie


# ── Routes Plans (admin YIRIBA) ──────────────────────────────────


@router.get("/plans")
async def list_plans(
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Lister tous les forfaits disponibles."""
    plans = (await db.execute(
        select(SubscriptionPlan).order_by(SubscriptionPlan.price_per_student_year)
    )).scalars().all()

    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "code": p.code,
                "max_students": p.max_students,
                "trial_days": p.trial_days,
                "price_per_student_year": str(p.price_per_student_year),
                "features": p.features,
                "is_active": p.is_active,
            }
            for p in plans
        ]
    }


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: int,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Detail d'un forfait."""
    plan = (await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Forfait introuvable")

    return {
        "id": plan.id,
        "name": plan.name,
        "code": plan.code,
        "max_students": plan.max_students,
        "trial_days": plan.trial_days,
        "price_per_student_year": str(plan.price_per_student_year),
        "features": plan.features,
        "is_active": plan.is_active,
        "created_at": str(plan.created_at),
    }


@router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: int,
    data: PlanUpdate,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Modifier un forfait (admin YIRIBA).

    Restreint aux administrateurs plateforme (settings.PLATFORM_ADMIN_EMAILS).
    Les modifications n'affectent PAS les abonnements historiques.
    """
    plan = (await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Forfait introuvable")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(plan, field, value)

    await db.flush()

    # Audit
    from app.services.audit_service import log_action
    await log_action(
        db,
        school_id=get_school_id(user),
        user_id=user.id,
        action="plan.update",
        resource="subscription_plan",
        resource_id=plan.id,
        details={"changes": update_data},
    )

    return {"id": plan.id, "name": plan.name, "message": "Forfait mis a jour"}


# ── Routes Abonnement (par ecole) ────────────────────────────────


@router.get("/school/{school_id}")
async def get_school_subscription(
    school_id: int,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Consulter l'abonnement d'une ecole."""
    # Verifier que l'utilisateur appartient a l'ecole
    caller_school = get_school_id(user)
    if caller_school != school_id:
        raise HTTPException(status_code=403, detail="Acces interdit")

    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")

    # Compter les eleves actifs
    student_count = (await db.execute(
        select(func.count()).select_from(Student).where(
            Student.school_id == school_id,
            Student.status == StudentStatus.ACTIVE,
        )
    )).scalar() or 0

    # Recuperer le plan actuel
    plan = None
    if school.current_plan_id:
        plan = (await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == school.current_plan_id)
        )).scalar_one_or_none()

    # Dernier abonnement
    last_sub = (await db.execute(
        select(Subscription).where(Subscription.school_id == school_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    return {
        "school_id": school_id,
        "subscription_status": school.subscription_status,
        "trial_ends_at": str(school.trial_ends_at) if school.trial_ends_at else None,
        "student_count": student_count,
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "code": plan.code,
            "max_students": plan.max_students,
            "price_per_student_year": str(plan.price_per_student_year),
            "features": plan.features,
        } if plan else None,
        "last_subscription": {
            "id": last_sub.id,
            "status": last_sub.status.value if hasattr(last_sub.status, 'value') else last_sub.status,
            "started_at": str(last_sub.started_at),
            "ends_at": str(last_sub.ends_at) if last_sub.ends_at else None,
            "amount": str(last_sub.amount),
            "student_count_at_billing": last_sub.student_count_at_billing,
        } if last_sub else None,
    }


@router.post("/school/{school_id}/activate")
async def activate_subscription(
    school_id: int,
    data: SubscriptionActivate,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Activer un abonnement payant pour une ecole.

    Reserve a l'editeur YIRIBA (settings.PLATFORM_ADMIN_EMAILS).
    Le directeur de l'ecole ne peut PAS activer/payer son propre plan.
    """
    # Recuperer le plan demande
    plan = (await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.code == data.plan_code)
    )).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Forfait introuvable")
    if not plan.is_active:
        raise HTTPException(status_code=400, detail="Ce forfait n'est plus disponible")

    # Recuperer l'ecole
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")

    # Verifier la limite pour downgrade
    if plan.max_students is not None:
        student_count = (await db.execute(
            select(func.count()).select_from(Student).where(
                Student.school_id == school_id,
                Student.status == StudentStatus.ACTIVE,
            )
        )).scalar() or 0
        if student_count > plan.max_students:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Impossible de passer au forfait {plan.name} : "
                    f"votre etablissement compte {student_count} eleves actifs, "
                    f"soit plus que la capacite maximale ({plan.max_students}) "
                    f"de ce forfait."
                ),
            )

    # Calculer le montant
    student_count = (await db.execute(
        select(func.count()).select_from(Student).where(
            Student.school_id == school_id,
            Student.status == StudentStatus.ACTIVE,
        )
    )).scalar() or 0

    from decimal import Decimal

    if data.custom_amount:
        amount = Decimal(data.custom_amount)
    elif data.custom_price_per_student:
        amount = Decimal(data.custom_price_per_student) * student_count
    elif plan.code == "baobab" and data.custom_price_per_student:
        amount = Decimal(data.custom_price_per_student) * student_count
    else:
        amount = plan.price_per_student_year * student_count

    # Creer l'abonnement
    subscription = Subscription(
        school_id=school_id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=datetime.now(UTC),
        ends_at=datetime.now(UTC) + timedelta(days=365),
        student_count_at_billing=student_count,
        amount=amount,
        custom_price_per_student=Decimal(data.custom_price_per_student) if data.custom_price_per_student else None,
        custom_amount=Decimal(data.custom_amount) if data.custom_amount else None,
    )
    db.add(subscription)

    # Mettre a jour l'ecole
    school.current_plan_id = plan.id
    school.subscription_status = SubscriptionStatus.ACTIVE.value
    school.student_count_at_billing = student_count

    await db.flush()

    # Audit
    from app.services.audit_service import log_action
    await log_action(
        db,
        school_id=school_id,
        user_id=user.id,
        action="subscription.activate",
        resource="subscription",
        resource_id=subscription.id,
        details={
            "plan_code": plan.code,
            "amount": str(amount),
            "student_count": student_count,
        },
    )

    return {
        "subscription_id": subscription.id,
        "plan": plan.name,
        "status": "active",
        "amount": str(amount),
        "student_count_at_billing": student_count,
        "ends_at": str(subscription.ends_at),
        "message": f"Abonnement {plan.name} active avec succes",
    }


# ── Changement de forfait ─────────────────────────────────────────


PLAN_HIERARCHY = {"graine": 0, "racine": 1, "baobab": 2}


@router.post("/school/{school_id}/change-plan")
async def change_plan(
    school_id: int,
    data: ChangePlanRequest,
    user: User = Depends(require_platform_admin()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Changer de forfait pour une ecole.

    Reserve a l'editeur YIRIBA (settings.PLATFORM_ADMIN_EMAILS).
    Le directeur de l'ecole ne peut PAS changer son propre forfait.

    Transitions autorisees :
    - trial/graine -> racine (upgrade)
    - trial/graine -> baobab (upgrade)
    - racine -> baobab (upgrade)

    Transitions interdites :
    - downgrade (ex: racine -> graine avec 350 eleves)

    La fermeture de l'ancien abonnement est automatique.
    """
    # 1. Recuperer l'ecole
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")

    # 2. Recuperer le nouveau plan
    new_plan = (await db.execute(
        select(SubscriptionPlan).where(
            SubscriptionPlan.code == data.plan_code,
            SubscriptionPlan.is_active == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not new_plan:
        raise HTTPException(status_code=404, detail="Forfait introuvable ou indisponible")

    # 3. Recuperer le plan actuel
    current_plan = None
    if school.current_plan_id:
        current_plan = (await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == school.current_plan_id)
        )).scalar_one_or_none()

    # 4. Verifier downgrade
    current_hierarchy = PLAN_HIERARCHY.get(current_plan.code, 0) if current_plan else 0
    new_hierarchy = PLAN_HIERARCHY.get(new_plan.code, 0)

    if new_hierarchy < current_hierarchy:
        # Downgrade — verifier si possible
        student_count = (await db.execute(
            select(func.count()).select_from(Student).where(
                Student.school_id == school_id,
                Student.status == StudentStatus.ACTIVE,
            )
        )).scalar() or 0

        if new_plan.max_students and student_count > new_plan.max_students:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Downgrade impossible : votre etablissement compte {student_count} eleves actifs, "
                    f"soit plus que la capacite maximale ({new_plan.max_students}) du forfait {new_plan.name}. "
                    f"Retirez des eleves ou transferez-les avant de changer de forfait."
                ),
            )

    # 5. Fermer l'ancien abonnement
    old_sub = (await db.execute(
        select(Subscription).where(
            Subscription.school_id == school_id,
            Subscription.status.in_([SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE]),
        )
    )).scalar_one_or_none()

    if old_sub:
        old_sub.status = SubscriptionStatus.CANCELLED
        old_sub.ends_at = datetime.now(UTC)

    # 6. Compter les eleves
    student_count = (await db.execute(
        select(func.count()).select_from(Student).where(
            Student.school_id == school_id,
            Student.status == StudentStatus.ACTIVE,
        )
    )).scalar() or 0

    from decimal import Decimal

    # 7. Calculer le montant
    if data.custom_amount:
        amount = Decimal(data.custom_amount)
    elif data.custom_price_per_student:
        amount = Decimal(data.custom_price_per_student) * student_count
    else:
        amount = new_plan.price_per_student_year * student_count

    # 8. Creer le nouvel abonnement
    new_sub = Subscription(
        school_id=school_id,
        plan_id=new_plan.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=datetime.now(UTC),
        ends_at=datetime.now(UTC) + timedelta(days=365),
        student_count_at_billing=student_count,
        amount=amount,
        custom_price_per_student=Decimal(data.custom_price_per_student) if data.custom_price_per_student else None,
        custom_amount=Decimal(data.custom_amount) if data.custom_amount else None,
    )
    db.add(new_sub)

    # 9. Mettre a jour l'ecole
    school.current_plan_id = new_plan.id
    school.subscription_status = SubscriptionStatus.ACTIVE.value
    school.student_count_at_billing = student_count
    school.trial_ends_at = None  # Fini l'essai

    await db.flush()

    # 10. Audit
    from app.services.audit_service import log_action
    await log_action(
        db,
        school_id=school_id,
        user_id=user.id,
        action="subscription.change_plan",
        resource="subscription",
        resource_id=new_sub.id,
        details={
            "old_plan": current_plan.code if current_plan else None,
            "new_plan": new_plan.code,
            "amount": str(amount),
            "student_count": student_count,
        },
    )

    return {
        "subscription_id": new_sub.id,
        "previous_plan": current_plan.name if current_plan else None,
        "new_plan": new_plan.name,
        "status": "active",
        "amount": str(amount),
        "student_count_at_billing": student_count,
        "ends_at": str(new_sub.ends_at),
        "message": f"Passage au forfait {new_plan.name} effectue avec succes",
    }


@router.get("/school/{school_id}/history")
async def subscription_history(
    school_id: int,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Historique des abonnements d'une ecole."""
    caller_school = get_school_id(user)
    if caller_school != school_id:
        raise HTTPException(status_code=403, detail="Acces interdit")

    subs = (await db.execute(
        select(Subscription)
        .where(Subscription.school_id == school_id)
        .order_by(Subscription.created_at.desc())
    )).scalars().all()

    return {
        "subscriptions": [
            {
                "id": s.id,
                "plan_id": s.plan_id,
                "status": s.status.value if hasattr(s.status, 'value') else s.status,
                "started_at": str(s.started_at),
                "ends_at": str(s.ends_at) if s.ends_at else None,
                "amount": str(s.amount),
                "student_count_at_billing": s.student_count_at_billing,
                "created_at": str(s.created_at),
            }
            for s in subs
        ]
    }


# ── Resume pour le dashboard ───────────────────────────────────────


@router.get("/my-summary")
async def my_subscription_summary(
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resume de l'abonnement pour l'ecole connectee.

    Accessible a tous les utilisateurs authentifies (pas juste admin).
    Utilise pour afficher le statut dans le dashboard.
    """
    from app.services.subscription_service import SubscriptionAccessService

    school_id = get_school_id(user)

    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")

    # Compter les eleves actifs
    student_count = (await db.execute(
        select(func.count()).select_from(Student).where(
            Student.school_id == school_id,
            Student.status == StudentStatus.ACTIVE,
        )
    )).scalar() or 0

    # Plan actuel
    plan = None
    if school.current_plan_id:
        plan = (await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == school.current_plan_id)
        )).scalar_one_or_none()

    # Niveau d'acces
    access_level = await SubscriptionAccessService.get_access_level(db, school_id)

    # Pourcentage d'utilisation
    usage_pct = 0
    max_s = 0
    if plan:
        if plan.max_students is None:
            max_s = 0  # Illimite
            usage_pct = 0
        else:
            max_s = plan.max_students
            usage_pct = round((student_count / max_s) * 100) if max_s > 0 else 0

    return {
        "school_id": school_id,
        "school_name": school.name,
        "subscription_status": school.subscription_status,
        "trial_ends_at": str(school.trial_ends_at) if school.trial_ends_at else None,
        "access_level": access_level,
        "student_count": student_count,
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "code": plan.code,
            "max_students": plan.max_students,
            "price_per_student_year": str(plan.price_per_student_year),
            "features": json.loads(plan.features) if plan.features else {},
        } if plan else None,
        "usage_pct": usage_pct,
        "max_students_display": max_s,
    }


# ── Contact YIRIBA (demande d'abonnement / support) ──────────────


class SupportRequestCreate(BaseModel):
    subject: str = Field(..., min_length=3, max_length=150)
    message: str = Field(..., min_length=10, max_length=2000)
    phone: str | None = Field(default=None, max_length=30)


@router.post("/support-request", status_code=201)
async def create_support_request(
    data: SupportRequestCreate,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Le directeur clique sur « Contacter YIRIBA » : ouvre une conversation
    avec le compte support YIRIBA et lui envoie une notification.

    La conversation est rattachee a l'ecole du demandeur ; le message part
    vers le premier utilisateur actif dont l'email figure dans
    settings.PLATFORM_ADMIN_EMAILS (l'equipe YIRIBA).
    """
    from app.core.config import get_settings
    from app.models.user import User as UserModel
    from app.services import message_service
    from app.services.notification_service import notify_user
    from app.services.audit_service import safe_audit

    school_id = get_school_id(user)
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")

    settings = get_settings()
    support_user = None
    for email in settings.platform_admin_emails:
        support_user = (await db.execute(
            select(UserModel).where(UserModel.email == email.lower())
        )).scalar_one_or_none()
        if support_user:
            break
    if not support_user:
        raise HTTPException(
            status_code=503,
            detail="Le support YIRIBA n'est pas configure. Contactez-nous par email.",
        )

    phone_line = f"\nTelephone : {data.phone}" if data.phone else ""
    content = (
        f"Demande de {user.first_name} {user.last_name} "
        f"({user.email}) — ecole : {school.name}.\n\n"
        f"{data.message}{phone_line}"
    )

    # Conversation directe demandeur <-> support (dans l'ecole du support)
    conv = await message_service.create_conversation(
        db, support_user.school_id, user.id, [support_user.id],
        subject=f"[{school.name}] {data.subject}",
    )
    msg = await message_service.send_message(
        db, support_user.school_id, conv.id, user.id, content
    )

    await notify_user(
        db, support_user.school_id, support_user,
        event_type="other",
        subject="Nouvelle demande d'abonnement",
        body=f"{school.name} : {data.subject}",
        related_entity_type="conversation",
        related_entity_id=conv.id,
    )

    await safe_audit(
        db, school_id=school_id, user_id=user.id,
        action="subscription.support_request", resource="conversation",
        resource_id=conv.id, details={"subject": data.subject},
    )
    await db.commit()

    return {
        "conversation_id": conv.id,
        "message": "Votre demande a ete envoyee a l'equipe YIRIBA.",
    }
