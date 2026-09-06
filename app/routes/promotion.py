"""Yiriba SaaS — Routes de passage de classe (fin d'année scolaire)."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.models.user import User
from app.services import promotion_service
from app.services.subscription_service import require_write_access

router = APIRouter(prefix="/api/promotion", tags=["promotion"])


class PromotionDecision(BaseModel):
    student_id: int
    decision: str = Field(..., pattern="^(pass|repeat|review|unenrolled)$")
    target_class_id: int | None = None


class PromotionApply(BaseModel):
    source_class_id: int
    source_year: str = Field(..., max_length=10)
    target_year: str = Field(..., max_length=10)
    decisions: list[PromotionDecision] = Field(..., min_length=1)


@router.get("/next-year-preparation")
async def next_year_preparation(
    source_year: str = Query(..., max_length=10),
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Statistiques de préparation de l'année suivante (toutes classes)."""
    school_id = get_school_id(user)
    return await promotion_service.get_next_year_preparation(db, school_id, source_year)


@router.get("/students")
async def list_students(
    class_id: int = Query(...),
    academic_year: str = Query(..., max_length=10),
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Liste les élèves d'une classe avec moyenne annuelle et décision proposée."""
    school_id = get_school_id(user)
    return await promotion_service.list_students_for_promotion(db, school_id, class_id, academic_year)


@router.get("/destination-classes")
async def destination_classes(
    next_year: str = Query(..., max_length=10),
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Classes disponibles pour l'année suivante."""
    school_id = get_school_id(user)
    classes = await promotion_service.list_destination_classes(db, school_id, next_year)
    return {"classes": classes}


@router.post("/apply")
async def apply_promotions(
    data: PromotionApply,
    user: User = Depends(require_permission("student.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Applique les décisions de passage en masse (pass / repeat / review / unenrolled)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    return await promotion_service.apply_promotions(
        db, school_id, user.id,
        data.source_class_id, data.source_year, data.target_year,
        [d.model_dump() for d in data.decisions],
    )


@router.get("/history")
async def promotion_history(
    academic_year: str | None = Query(None, max_length=10),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Historique des passages de classe."""
    school_id = get_school_id(user)
    items = await promotion_service.list_promotion_history(db, school_id, academic_year, limit)
    return {"history": items}
