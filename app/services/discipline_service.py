"""Yiriba SaaS — Discipline service.

Handles:
- Auto-creating DisciplinaryRecords from attendance events
- Manual record creation (incivilities)
- Cancellation (soft delete) with audit trail
- Total deduction calculation per student/period
- Rule management (CRUD)
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import Attendance, StatutPresence
from app.models.discipline import DisciplinaryRecord, DisciplinaryRuleSet
from app.models.school import School


# ── Incident type mapping ───────────────────────────────────────

ATTENDANCE_TO_INCIDENT = {
    StatutPresence.ABSENT: "absence_non_justifiee",
    StatutPresence.RETARD: "retard",
    StatutPresence.INCIVISME: "incivilite",
}


# ── Auto-record from attendance ─────────────────────────────────

async def create_record_from_attendance(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    period: str,
    academic_year: str,
    status: StatutPresence,
    is_justified: bool,
    recorded_by: Optional[int],
    attendance_date: date,
) -> Optional[DisciplinaryRecord]:
    """Create a DisciplinaryRecord automatically from an attendance event.

    Returns the created record, or None if no rule applies
    (e.g., justified absence, or no matching rule).
    """
    # Justified absences don't trigger disciplinary records
    if status == StatutPresence.ABSENT and is_justified:
        return None

    # Only ABSENT, RETARD, INCIVISME trigger records
    incident_type = ATTENDANCE_TO_INCIDENT.get(status)
    if not incident_type:
        return None

    # Find the rule for this incident type
    rule = (await db.execute(
        select(DisciplinaryRuleSet).where(
            DisciplinaryRuleSet.school_id == school_id,
            DisciplinaryRuleSet.incident_type == incident_type,
            DisciplinaryRuleSet.is_active == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    if not rule or rule.points_deducted <= 0:
        return None

    # Check for duplicate (same student, same date, same type, active)
    existing = (await db.execute(
        select(DisciplinaryRecord).where(
            DisciplinaryRecord.school_id == school_id,
            DisciplinaryRecord.student_id == student_id,
            DisciplinaryRecord.date == attendance_date,
            DisciplinaryRecord.incident_type == incident_type,
            DisciplinaryRecord.status == "active",
        )
    )).scalar_one_or_none()

    if existing:
        return None  # Already recorded

    record = DisciplinaryRecord(
        school_id=school_id,
        student_id=student_id,
        period=period,
        academic_year=academic_year,
        incident_type=incident_type,
        points_deducted=rule.points_deducted,
        source="auto",
        recorded_by=recorded_by,
        date=attendance_date,
    )
    db.add(record)
    return record


async def cancel_record_on_justification(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    attendance_date: date,
    cancelled_by: Optional[int],
) -> int:
    """Cancel auto-created DisciplinaryRecords when an absence is justified.

    Returns the number of records cancelled.
    """
    records = (await db.execute(
        select(DisciplinaryRecord).where(
            DisciplinaryRecord.school_id == school_id,
            DisciplinaryRecord.student_id == student_id,
            DisciplinaryRecord.date == attendance_date,
            DisciplinaryRecord.incident_type == "absence_non_justifiee",
            DisciplinaryRecord.source == "auto",
            DisciplinaryRecord.status == "active",
        )
    )).scalars().all()

    count = 0
    for record in records:
        record.status = "cancelled"
        record.cancelled_at = datetime.utcnow()
        record.cancelled_by = cancelled_by
        record.cancel_reason = "Absence justifiée"
        count += 1

    return count


# ── Manual record ───────────────────────────────────────────────

async def create_manual_record(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    period: str,
    academic_year: str,
    incident_type: str,
    recorded_by: int,
    incident_date: date,
    note: Optional[str] = None,
) -> DisciplinaryRecord:
    """Create a disciplinary record manually (e.g., incivility by teacher)."""
    # Find the rule to get points
    rule = (await db.execute(
        select(DisciplinaryRuleSet).where(
            DisciplinaryRuleSet.school_id == school_id,
            DisciplinaryRuleSet.incident_type == incident_type,
            DisciplinaryRuleSet.is_active == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    if not rule:
        raise ValueError(f"No active rule for incident type: {incident_type}")

    record = DisciplinaryRecord(
        school_id=school_id,
        student_id=student_id,
        period=period,
        academic_year=academic_year,
        incident_type=incident_type,
        points_deducted=rule.points_deducted,
        source="manual",
        recorded_by=recorded_by,
        date=incident_date,
        note=note,
    )
    db.add(record)
    return record


# ── Cancellation ────────────────────────────────────────────────

async def cancel_record(
    db: AsyncSession,
    record_id: int,
    school_id: int,
    cancelled_by: int,
    reason: str,
) -> DisciplinaryRecord:
    """Cancel a disciplinary record (soft delete with audit trail)."""
    record = (await db.execute(
        select(DisciplinaryRecord).where(
            DisciplinaryRecord.id == record_id,
            DisciplinaryRecord.school_id == school_id,
        )
    )).scalar_one_or_none()

    if not record:
        raise ValueError("Record not found")

    if record.status == "cancelled":
        raise ValueError("Record is already cancelled")

    record.status = "cancelled"
    record.cancelled_at = datetime.utcnow()
    record.cancelled_by = cancelled_by
    record.cancel_reason = reason

    return record


# ── Total deductions ────────────────────────────────────────────

async def get_total_deductions(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    period: str,
    academic_year: str,
) -> float:
    """Get total active disciplinary deductions for a student in a period."""
    result = (await db.execute(
        select(func.sum(DisciplinaryRecord.points_deducted)).where(
            DisciplinaryRecord.school_id == school_id,
            DisciplinaryRecord.student_id == student_id,
            DisciplinaryRecord.period == period,
            DisciplinaryRecord.academic_year == academic_year,
            DisciplinaryRecord.status == "active",
        )
    )).scalar()
    return result or 0.0


async def get_student_records(
    db: AsyncSession,
    school_id: int,
    student_id: int,
    period: str,
    academic_year: str,
) -> list[DisciplinaryRecord]:
    """Get all disciplinary records for a student in a period."""
    return (await db.execute(
        select(DisciplinaryRecord).where(
            DisciplinaryRecord.school_id == school_id,
            DisciplinaryRecord.student_id == student_id,
            DisciplinaryRecord.period == period,
            DisciplinaryRecord.academic_year == academic_year,
        ).order_by(DisciplinaryRecord.date.desc())
    )).scalars().all()


# ── Rule management ─────────────────────────────────────────────

async def get_school_rules(db: AsyncSession, school_id: int) -> list[DisciplinaryRuleSet]:
    """Get all disciplinary rules for a school."""
    return (await db.execute(
        select(DisciplinaryRuleSet).where(
            DisciplinaryRuleSet.school_id == school_id,
        ).order_by(DisciplinaryRuleSet.incident_type)
    )).scalars().all()


async def upsert_rule(
    db: AsyncSession,
    school_id: int,
    incident_type: str,
    points_deducted: float,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> DisciplinaryRuleSet:
    """Create or update a disciplinary rule for a school."""
    existing = (await db.execute(
        select(DisciplinaryRuleSet).where(
            DisciplinaryRuleSet.school_id == school_id,
            DisciplinaryRuleSet.incident_type == incident_type,
        )
    )).scalar_one_or_none()

    if existing:
        existing.points_deducted = points_deducted
        if description is not None:
            existing.description = description
        if is_active is not None:
            existing.is_active = is_active
        return existing

    rule = DisciplinaryRuleSet(
        school_id=school_id,
        incident_type=incident_type,
        points_deducted=points_deducted,
        description=description,
        is_active=is_active if is_active is not None else True,
    )
    db.add(rule)
    return rule


async def seed_default_rules(db: AsyncSession, school_id: int) -> None:
    """Create default disciplinary rules for a new school."""
    defaults = [
        ("absence_non_justifiee", 0.5, "Absence non justifiée — 0.5 point déduit"),
        ("retard", 0.25, "Retard à l'arrivée — 0.25 point déduit"),
        ("incivilite", 1.0, "Incivilité en classe — 1 point déduit"),
    ]
    for itype, pts, desc in defaults:
        existing = (await db.execute(
            select(DisciplinaryRuleSet).where(
                DisciplinaryRuleSet.school_id == school_id,
                DisciplinaryRuleSet.incident_type == itype,
            )
        )).scalar_one_or_none()
        if not existing:
            db.add(DisciplinaryRuleSet(
                school_id=school_id,
                incident_type=itype,
                points_deducted=pts,
                description=desc,
            ))
