"""Yiriba SaaS — Academic periods management routes.

Gestion complète des périodes académiques (trimestres, semestres, personnalisé).
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_current_user, get_school_id, require_permission
from app.models.academic_year import AcademicYear, AcademicPeriod
from app.models.user import User

router = APIRouter(prefix="/api/academic-periods", tags=["Academic Periods"])


# ── Schemas ──────────────────────────────────────────────────────

class PeriodCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    period_type: str = Field(..., pattern=r"^(trimester|semester|custom)$")
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    order_index: int = Field(default=1, ge=1, le=20)
    status: str = Field(default="upcoming", pattern=r"^(upcoming|active|completed)$")


class PeriodUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    order_index: Optional[int] = None
    status: Optional[str] = Field(None, pattern=r"^(upcoming|active|completed|upcoming|active|completed)$")


class BulkPeriodsRequest(BaseModel):
    """Auto-generate periods for a school year."""
    academic_year_id: int
    period_type: str = Field(..., pattern=r"^(trimester|semester|custom)$")
    periods: list[PeriodCreate]  # List of periods to create


# ── Routes ───────────────────────────────────────────────────────

@router.get("")
async def list_periods(
    academic_year_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List academic periods for the school."""
    school_id = get_school_id(user)
    query = select(AcademicPeriod).where(
        AcademicPeriod.school_id == school_id,
        AcademicPeriod.is_active == True,  # noqa: E712
    )
    if academic_year_id:
        query = query.where(AcademicPeriod.academic_year_id == academic_year_id)
    query = query.order_by(AcademicPeriod.order_index)
    result = await db.execute(query)
    periods = result.scalars().all()
    return {
        "periods": [
            {
                "id": p.id,
                "academic_year_id": p.academic_year_id,
                "name": p.name,
                "period_type": p.period_type,
                "start_date": str(p.start_date),
                "end_date": str(p.end_date),
                "order_index": p.order_index,
                "status": p.status,
                "is_active": p.is_active,
            }
            for p in periods
        ]
    }


@router.get("/active")
async def get_active_period(
    academic_year_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the currently active period (by date or manual status)."""
    school_id = get_school_id(user)
    today = datetime.now(timezone.utc).date()

    # First, check for manually set "active" period
    query = select(AcademicPeriod).where(
        AcademicPeriod.school_id == school_id,
        AcademicPeriod.is_active == True,  # noqa: E712
        AcademicPeriod.status == "active",
    )
    if academic_year_id:
        query = query.where(AcademicPeriod.academic_year_id == academic_year_id)
    result = await db.execute(query)
    period = result.scalar_one_or_none()

    if not period:
        # Auto-detect by date
        query2 = select(AcademicPeriod).where(
            AcademicPeriod.school_id == school_id,
            AcademicPeriod.is_active == True,  # noqa: E712
            AcademicPeriod.start_date <= today,
            AcademicPeriod.end_date >= today,
        )
        if academic_year_id:
            query2 = query2.where(AcademicPeriod.academic_year_id == academic_year_id)
        result2 = await db.execute(query2)
        period = result2.scalar_one_or_none()

    if period:
        return {
            "period": {
                "id": period.id,
                "name": period.name,
                "period_type": period.period_type,
                "start_date": str(period.start_date),
                "end_date": str(period.end_date),
                "status": period.status,
            }
        }
    return {"period": None}


@router.post("")
async def create_period(
    data: PeriodCreate,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a single academic period."""
    from datetime import date as _date
    school_id = get_school_id(user)

    # Get current academic year if not specified
    ay_query = select(AcademicYear).where(
        AcademicYear.school_id == school_id,
        AcademicYear.is_current == True,  # noqa: E712
    )
    ay_result = await db.execute(ay_query)
    academic_year = ay_result.scalar_one_or_none()
    if not academic_year:
        raise HTTPException(status_code=400, detail="Aucune année scolaire active")

    # Check duplicate name
    existing = (await db.execute(
        select(AcademicPeriod).where(
            AcademicPeriod.school_id == school_id,
            AcademicPeriod.academic_year_id == academic_year.id,
            AcademicPeriod.name == data.name,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"La période '{data.name}' existe déjà")

    start = _date.fromisoformat(data.start_date)
    end = _date.fromisoformat(data.end_date)
    if end <= start:
        raise HTTPException(status_code=400, detail="La date de fin doit être après la date de début")

    period = AcademicPeriod(
        school_id=school_id,
        academic_year_id=academic_year.id,
        name=data.name.strip(),
        period_type=data.period_type,
        start_date=start,
        end_date=end,
        order_index=data.order_index,
        status=data.status,
    )
    db.add(period)
    await db.flush()

    # Audit
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id,
                     action="academic_period.create", resource="academic_period",
                     resource_id=period.id, details={"name": period.name})
    await db.commit()

    return {"id": period.id, "name": period.name, "message": "Période créée"}


@router.post("/bulk")
async def create_bulk_periods(
    data: BulkPeriodsRequest,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Auto-generate periods for an academic year (e.g., 3 trimesters at once)."""
    from datetime import date as _date
    school_id = get_school_id(user)

    academic_year = (await db.execute(
        select(AcademicYear).where(
            AcademicYear.id == data.academic_year_id,
            AcademicYear.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not academic_year:
        raise HTTPException(status_code=404, detail="Année scolaire introuvable")

    created = 0
    for p_data in data.periods:
        start = _date.fromisoformat(p_data.start_date)
        end = _date.fromisoformat(p_data.end_date)
        existing = (await db.execute(
            select(AcademicPeriod).where(
                AcademicPeriod.school_id == school_id,
                AcademicPeriod.academic_year_id == academic_year.id,
                AcademicPeriod.name == p_data.name,
            )
        )).scalar_one_or_none()
        if existing:
            continue
        period = AcademicPeriod(
            school_id=school_id,
            academic_year_id=academic_year.id,
            name=p_data.name.strip(),
            period_type=data.period_type,
            start_date=start,
            end_date=end,
            order_index=p_data.order_index,
            status=p_data.status,
        )
        db.add(period)
        created += 1

    await db.commit()
    return {"created": created, "message": f"{created} période(s) créée(s)"}


@router.put("/{period_id}")
async def update_period(
    period_id: int,
    data: PeriodUpdate,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update an academic period."""
    from datetime import date as _date
    school_id = get_school_id(user)

    period = (await db.execute(
        select(AcademicPeriod).where(
            AcademicPeriod.id == period_id,
            AcademicPeriod.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not period:
        raise HTTPException(status_code=404, detail="Période introuvable")

    if data.name is not None:
        period.name = data.name.strip()
    if data.start_date is not None:
        period.start_date = _date.fromisoformat(data.start_date)
    if data.end_date is not None:
        period.end_date = _date.fromisoformat(data.end_date)
    if data.order_index is not None:
        period.order_index = data.order_index
    if data.status is not None:
        period.status = data.status
    period.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return {"message": "Période mise à jour"}


@router.delete("/{period_id}")
async def delete_period(
    period_id: int,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a period (only if no evaluations are linked)."""
    school_id = get_school_id(user)
    period = (await db.execute(
        select(AcademicPeriod).where(
            AcademicPeriod.id == period_id,
            AcademicPeriod.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not period:
        raise HTTPException(status_code=404, detail="Période introuvable")

    # Check if evaluations are linked
    from app.models.grade import Evaluation
    eval_count = (await db.execute(
        select(func.count()).select_from(Evaluation).where(
            Evaluation.academic_period_id == period_id,
        )
    )).scalar()
    if eval_count and eval_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Impossible de supprimer : {eval_count} évaluation(s) liée(s) à cette période"
        )

    period.is_active = False
    await db.commit()
    return {"message": "Période supprimée"}
