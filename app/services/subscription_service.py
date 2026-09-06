"""Yiriba SaaS — Subscription services.

- PlanLimitService : verifie si une ecole peut ajouter un eleve
- SubscriptionAccessService : determine READ_ONLY vs FULL_ACCESS
- plan_has_feature : verifie si une fonctionnalite est incluse dans le plan
- require_write_access : helper pour bloquer les ecritures si abonnement expire
"""

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import StudentStatus
from app.models.student import Student
from app.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)


# ── Verification de fonctionnalite ────────────────────────────────


def plan_has_feature(plan: SubscriptionPlan, feature_name: str) -> bool:
    """Verifie si une fonctionnalite est incluse dans le forfait.

    Centralise la logique : passe facilement a une table Feature plus tard.
    """
    try:
        features = json.loads(plan.features) if plan.features else {}
    except (json.JSONDecodeError, TypeError):
        return False
    return bool(features.get(feature_name, False))


# ── Service de limite d'eleves ────────────────────────────────────


class PlanLimitService:
    """Controle la limite d'eleves selon le forfait de l'ecole.

    Logique :
    1. Recuperer l'ecole (school_id depuis JWT)
    2. Recuperer le forfait actuel
    3. Compter les eleves actifs
    4. Comparer a max_students
    5. Autoriser ou refuser
    """

    @staticmethod
    async def check_can_add_student(
        db: AsyncSession,
        school_id: int,
    ) -> None:
        """Verifie si l'ecole peut ajouter un eleve.

        Raises HTTPException 403 si limite atteinte.
        """
        from app.models.school import School

        # 1. Recuperer l'ecole
        school = (await db.execute(
            select(School).where(School.id == school_id)
        )).scalar_one_or_none()
        if not school:
            raise HTTPException(status_code=404, detail="Ecole introuvable")

        # 2. Verifier le statut d'abonnement
        if school.subscription_status == SubscriptionStatus.EXPIRED.value:
            raise HTTPException(
                status_code=403,
                detail="Votre abonnement a expire. Consultez vos donnees en lecture seule et choisissez un forfait pour reactiver la gestion.",
            )

        if school.subscription_status == SubscriptionStatus.CANCELLED.value:
            raise HTTPException(
                status_code=403,
                detail="Votre abonnement a ete annule. Choisissez un forfait pour reactiver la gestion.",
            )

        # 3. Recuperer le forfait
        if school.current_plan_id is None:
            raise HTTPException(
                status_code=403,
                detail="Aucun forfait assigne. Contactez le support YIRIBA.",
            )

        plan = (await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == school.current_plan_id)
        )).scalar_one_or_none()
        if not plan:
            raise HTTPException(
                status_code=403,
                detail="Forfait introuvable. Contactez le support YIRIBA.",
            )

        # 4. Baobab = illimite
        if plan.max_students is None:
            return  # Pas de limite

        # 5. Compter les eleves actifs
        active_count = (await db.execute(
            select(func.count()).select_from(Student).where(
                Student.school_id == school_id,
                Student.status == StudentStatus.ACTIVE,
            )
        )).scalar() or 0

        # 6. Comparer
        if active_count >= plan.max_students:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Limite du forfait {plan.name} atteinte. "
                    f"Votre etablissement compte deja {active_count} eleves, "
                    f"soit la capacite maximale de votre forfait actuel. "
                    f"Passez au forfait superieur pour continuer a ajouter des eleves."
                ),
            )

    @staticmethod
    async def get_student_count(db: AsyncSession, school_id: int) -> int:
        """Retourne le nombre d'eleves actifs de l'ecole."""
        return (await db.execute(
            select(func.count()).select_from(Student).where(
                Student.school_id == school_id,
                Student.status == StudentStatus.ACTIVE,
            )
        )).scalar() or 0


# ── Service d'acces centre ────────────────────────────────────────


class SubscriptionAccessService:
    """Determine si une ecole a acces complet ou en lecture seule.

    Centralise la logique pour ne pas repeter if/expired partout.
    """

    @staticmethod
    async def get_access_level(db: AsyncSession, school_id: int) -> str:
        """Retourne 'full_access' ou 'read_only'."""
        from app.models.school import School

        school = (await db.execute(
            select(School).where(School.id == school_id)
        )).scalar_one_or_none()
        if not school:
            return "read_only"

        status = school.subscription_status

        # Trial actif = acces complet
        if status == SubscriptionStatus.TRIAL.value:
            if school.trial_ends_at and school.trial_ends_at.replace(tzinfo=UTC) < datetime.now(UTC):
                return "read_only"
            return "full_access"

        # Abonnement actif = acces complet
        if status == SubscriptionStatus.ACTIVE.value:
            return "full_access"

        # Expire ou annule = lecture seule
        return "read_only"

    @staticmethod
    async def require_full_access(db: AsyncSession, school_id: int) -> None:
        """Raise 403 si l'ecole est en lecture seule."""
        access = await SubscriptionAccessService.get_access_level(db, school_id)
        if access == "read_only":
            raise HTTPException(
                status_code=403,
                detail=(
                    "Votre abonnement a expire ou n'est pas actif. "
                    "Vos donnees sont accessibles en lecture seule. "
                    "Choisissez un forfait pour reactiver la gestion complete."
                ),
            )


# ── Helper pour routes d'ecriture ─────────────────────────────────


async def require_write_access(db: AsyncSession, school_id: int) -> None:
    """Verifie que l'ecole a acces en ecriture (abonnement actif).

    A appeler explicitement dans les routes qui effectuent des ecritures :
    await require_write_access(db, school_id)

    Ne verifie PAS la permission RBAC — c'est fait separement.
    """
    await SubscriptionAccessService.require_full_access(db, school_id)
