"""Yiriba SaaS — Discipline routes: records, rules, cancellation."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.models.discipline import DisciplinaryRecord, DisciplinaryRuleSet
from app.models.user import User

router = APIRouter(prefix="/api/discipline", tags=["discipline"])


# ── Schemas ─────────────────────────────────────────────────────

class ManualRecordCreate(BaseModel):
    student_id: int
    period: str = Field(..., pattern="^(T[123]|S[12])$")
    academic_year: str = Field(default="2025-2026", max_length=10)
    incident_type: str = Field(..., min_length=1, max_length=30)
    date: str  # ISO date string
    note: str | None = None


class RuleUpdate(BaseModel):
    incident_type: str = Field(..., min_length=1, max_length=30)
    points_deducted: float = Field(..., ge=0, le=10)
    description: str | None = None
    is_active: bool | None = None


class CancelRecord(BaseModel):
    reason: str = Field(..., min_length=1, max_length=200)


class DisciplineModeUpdate(BaseModel):
    mode: str = Field(..., pattern="^(conduct|general_average)$")


# ── Rules ───────────────────────────────────────────────────────

@router.get("/rules")
async def list_rules(
    user: User = Depends(require_permission("discipline.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List disciplinary rules for the school."""
    from app.services.discipline_service import get_school_rules
    school_id = get_school_id(user)
    rules = await get_school_rules(db, school_id)
    return {
        "rules": [
            {
                "id": r.id,
                "incident_type": r.incident_type,
                "points_deducted": r.points_deducted,
                "description": r.description,
                "is_active": r.is_active,
            }
            for r in rules
        ]
    }


@router.put("/rules")
async def update_rule(
    data: RuleUpdate,
    user: User = Depends(require_permission("discipline.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create or update a disciplinary rule."""
    from app.services.discipline_service import upsert_rule
    school_id = get_school_id(user)
    rule = await upsert_rule(
        db, school_id, data.incident_type,
        data.points_deducted, data.description,
        data.is_active,
    )
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="discipline.rule.update", resource="disciplinary_rule", resource_id=rule.id, details={"incident_type": rule.incident_type, "points": rule.points_deducted, "active": rule.is_active})
    return {
        "id": rule.id,
        "incident_type": rule.incident_type,
        "points_deducted": rule.points_deducted,
        "description": rule.description,
        "is_active": rule.is_active,
    }


# ── Records ─────────────────────────────────────────────────────

@router.get("/records")
async def list_records(
    student_id: int | None = None,
    period: str | None = None,
    academic_year: str = Query("2025-2026"),
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("discipline.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List disciplinary records with filters."""
    school_id = get_school_id(user)
    query = select(DisciplinaryRecord).where(
        DisciplinaryRecord.school_id == school_id,
        DisciplinaryRecord.academic_year == academic_year,
    )
    if student_id:
        query = query.where(DisciplinaryRecord.student_id == student_id)
    if period:
        query = query.where(DisciplinaryRecord.period == period)
    if status:
        query = query.where(DisciplinaryRecord.status == status)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    query = query.order_by(DisciplinaryRecord.date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    records = (await db.execute(query)).scalars().all()

    return {
        "records": [
            {
                "id": r.id,
                "student_id": r.student_id,
                "period": r.period,
                "incident_type": r.incident_type,
                "points_deducted": r.points_deducted,
                "source": r.source,
                "recorded_by": r.recorded_by,
                "date": r.date.isoformat() if r.date else None,
                "note": r.note,
                "status": r.status,
                "cancelled_at": r.cancelled_at.isoformat() if r.cancelled_at else None,
                "cancel_reason": r.cancel_reason,
            }
            for r in records
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("/records", status_code=201)
async def create_record(
    data: ManualRecordCreate,
    user: User = Depends(require_permission("discipline.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a disciplinary record manually.

    Teacher scope: teachers can only create records for students
    in their assigned classes (via ClassSubject).
    Admins can create for any student in the school.
    """
    from app.services.discipline_service import create_manual_record
    from app.services.audit_service import log_action
    from datetime import date as date_type
    from app.models.student import Student
    from app.models.class_ import ClassSubject, Enrollment

    school_id = get_school_id(user)

    # Verify student exists in this school
    student = (await db.execute(
        select(Student).where(Student.id == data.student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Eleve introuvable dans cet etablissement")

    # Teacher scope: verify student is in one of the teacher's classes
    # Admins (directeur) can create for any student; teachers only for their classes
    if user.role_type.value != "admin":
        # Teacher: check if student is enrolled in one of their classes
        teacher_class_ids = (await db.execute(
            select(ClassSubject.class_id).where(
                ClassSubject.teacher_id == user.id,
                ClassSubject.school_id == school_id,
            )
        )).scalars().all()
        student_class_ids = (await db.execute(
            select(Enrollment.class_id).where(
                Enrollment.student_id == data.student_id,
                Enrollment.status == "active",
                Enrollment.school_id == school_id,
            )
        )).scalars().all()
        if not set(student_class_ids).intersection(set(teacher_class_ids)):
            raise HTTPException(
                status_code=403,
                detail="Cet eleve n'est pas dans une de vos classes",
            )

    try:
        record = await create_manual_record(
            db, school_id, data.student_id,
            data.period, data.academic_year,
            data.incident_type, user.id,
            date_type.fromisoformat(data.date),
            data.note,
        )
        await db.flush()

        # AuditLog
        await log_action(
            db,
            school_id=school_id,
            user_id=user.id,
            action="discipline.record.create",
            resource="disciplinary_record",
            resource_id=record.id,
            details={
                "student_id": data.student_id,
                "incident_type": data.incident_type,
                "points_deducted": record.points_deducted,
                "source": "manual",
            },
        )
        await db.flush()

        return {
            "id": record.id,
            "student_id": record.student_id,
            "incident_type": record.incident_type,
            "points_deducted": record.points_deducted,
            "status": record.status,
            "message": f"{record.points_deducted} point(s) deduit(s)",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/records/{record_id}/cancel")
async def cancel_record_endpoint(
    record_id: int,
    data: CancelRecord,
    user: User = Depends(require_permission("discipline.delete")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel a disciplinary record (soft delete)."""
    from app.services.discipline_service import cancel_record
    school_id = get_school_id(user)

    try:
        record = await cancel_record(
            db, record_id, school_id, user.id, data.reason
        )
        await db.flush()
        return {
            "id": record.id,
            "status": record.status,
            "cancelled_at": record.cancelled_at.isoformat() if record.cancelled_at else None,
            "cancel_reason": record.cancel_reason,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Student summary ─────────────────────────────────────────────

@router.get("/student/{student_id}/summary")
async def student_summary(
    student_id: int,
    period: str = Query(..., pattern="^(T[123]|S[12])$"),
    academic_year: str = Query("2025-2026"),
    user: User = Depends(require_permission("discipline.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get discipline summary for a student: total deductions + records."""
    from app.services.discipline_service import get_total_deductions, get_student_records
    school_id = get_school_id(user)

    total = await get_total_deductions(db, school_id, student_id, period, academic_year)
    records = await get_student_records(db, school_id, student_id, period, academic_year)

    return {
        "student_id": student_id,
        "period": period,
        "total_deductions": total,
        "records": [
            {
                "id": r.id,
                "incident_type": r.incident_type,
                "points_deducted": r.points_deducted,
                "source": r.source,
                "date": r.date.isoformat() if r.date else None,
                "note": r.note,
                "status": r.status,
            }
            for r in records
        ],
    }


# ── Discipline mode ─────────────────────────────────────────────

@router.get("/mode")
async def get_discipline_mode(
    user: User = Depends(require_permission("discipline.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the school's discipline mode."""
    from app.models.school import School
    school_id = get_school_id(user)
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    return {"mode": school.discipline_mode if school else "conduct"}


@router.put("/mode")
async def set_discipline_mode(
    data: DisciplineModeUpdate,
    user: User = Depends(require_permission("discipline.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set the school's discipline mode."""
    from app.models.school import School
    school_id = get_school_id(user)
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    school.discipline_mode = data.mode
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="discipline.mode.update", resource="school", resource_id=school_id, details={"mode": data.mode})
    return {"mode": school.discipline_mode}
