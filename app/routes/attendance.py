"""Yiriba SaaS — Attendance routes with StatutPresence enum and slot_index.

Granularite par creneau horaire (slot_index).
"""

import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.services.subscription_service import require_write_access
from app.models.attendance import Attendance, StatutPresence
from app.models.class_ import Class, Enrollment
from app.models.student import Student
from app.models.user import User

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


# --- Schemas ---


class AttendanceMark(BaseModel):
    student_id: int
    class_id: int
    date: date
    status: StatutPresence
    slot_index: int = Field(default=0, ge=0)
    minutes_late: int | None = None
    justification: str | None = None
    period: str = Field(..., pattern="^(T[123]|S[12])$")


class BulkAttendance(BaseModel):
    class_id: int
    date: date
    period: str = Field(..., pattern="^(T[123]|S[12])$")
    slot_index: int = Field(default=0, ge=0)
    entries: list[dict]  # [{"student_id": 1, "status": "present"}, ...]


# --- Routes ---


@router.get("")
async def list_attendance(
    class_id: int | None = None,
    student_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: StatutPresence | None = None,
    period: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    user: User = Depends(require_permission("attendance.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(Attendance).where(Attendance.school_id == school_id)

    if class_id:
        query = query.where(Attendance.class_id == class_id)
    if student_id:
        query = query.where(Attendance.student_id == student_id)
    if status:
        query = query.where(Attendance.status == status)
    if period:
        query = query.where(Attendance.period == period)
    if date_from:
        query = query.where(Attendance.date >= date.fromisoformat(date_from))
    if date_to:
        query = query.where(Attendance.date <= date.fromisoformat(date_to))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    records = (await db.execute(
        query.order_by(Attendance.date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    # Resolve student and class names in batch (avoid N+1)
    student_ids = list({a.student_id for a in records})
    class_ids = list({a.class_id for a in records})
    students_map = {}
    classes_map = {}
    if student_ids:
        studs = (await db.execute(
            select(Student.id, Student.first_name, Student.last_name, Student.matricule)
            .where(Student.id.in_(student_ids))
        )).all()
        students_map = {s.id: {"first_name": s.first_name, "last_name": s.last_name, "matricule": s.matricule} for s in studs}
    if class_ids:
        cls = (await db.execute(
            select(Class.id, Class.name).where(Class.id.in_(class_ids))
        )).all()
        classes_map = {c.id: c.name for c in cls}

    return {
        "attendance": [
            {
                "id": a.id, "student_id": a.student_id, "class_id": a.class_id,
                "student_name": (students_map.get(a.student_id, {}).get('last_name', '') + ' ' + students_map.get(a.student_id, {}).get('first_name', '')).strip() if a.student_id in students_map else None,
                "student_matricule": students_map.get(a.student_id, {}).get('matricule', '') if a.student_id in students_map else None,
                "class_name": classes_map.get(a.class_id, ''),
                "date": str(a.date), "status": a.status.value,
                "slot_index": a.slot_index,
                "is_justified": a.is_justified,
                "minutes_late": a.minutes_late, "justification": a.justification,
            }
            for a in records
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


@router.delete("/{attendance_id}", status_code=200)
async def delete_attendance(
    attendance_id: int,
    user: User = Depends(require_permission("attendance.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Supprime un pointage de présence (multi-tenant strict)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    att = (await db.execute(
        select(Attendance).where(Attendance.id == attendance_id, Attendance.school_id == school_id)
    )).scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Pointage introuvable")

    await db.delete(att)
    from app.services.audit_service import safe_audit
    await safe_audit(
        db, school_id=school_id, user_id=user.id, action="attendance.delete",
        resource="attendance", resource_id=attendance_id,
        details={"student_id": att.student_id, "date": str(att.date), "status": att.status.value if hasattr(att.status, 'value') else str(att.status)},
    )
    return {"deleted": True, "id": attendance_id}


@router.post("", status_code=201)
async def mark_attendance(
    data: AttendanceMark,
    user: User = Depends(require_permission("attendance.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # ── Vérification FK croisée : l'élève appartient-il à cette école ?
    student_ok = (await db.execute(
        select(Student.id).where(
            Student.id == data.student_id,
            Student.school_id == school_id,
        )
    )).scalar_one_or_none()
    if student_ok is None:
        raise HTTPException(status_code=404, detail="Élève introuvable dans cette école")

    # Upsert — same student, date, period, slot_index
    existing = (await db.execute(
        select(Attendance).where(
            Attendance.student_id == data.student_id,
            Attendance.date == data.date,
            Attendance.period == data.period,
            Attendance.slot_index == data.slot_index,
        )
    )).scalar_one_or_none()

    if existing:
        existing.status = data.status
        existing.minutes_late = data.minutes_late
        existing.justification = data.justification
        existing.is_justified = bool(data.justification)
        existing.recorded_by = user.id
        record = existing
    else:
        record = Attendance(
            school_id=school_id,
            student_id=data.student_id,
            class_id=data.class_id,
            recorded_by=user.id,
            date=data.date,
            status=data.status,
            slot_index=data.slot_index,
            minutes_late=data.minutes_late,
            justification=data.justification,
            is_justified=bool(data.justification),
            period=data.period,
        )
        db.add(record)

    await db.flush()

    # ── Discipline auto-record + justification cancellation ───────
    from app.services.discipline_service import (
        create_record_from_attendance, cancel_record_on_justification,
    )
    from app.models.school import School
    from app.models.academic_year import AcademicYear

    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    academic_year = "2025-2026"
    if school:
        ay = (await db.execute(
            select(AcademicYear).where(
                AcademicYear.school_id == school_id,
                AcademicYear.is_current == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if ay:
            academic_year = ay.name

    # If justified after the fact, cancel existing auto-records
    if record.status in (StatutPresence.ABSENT, StatutPresence.RETARD, StatutPresence.INCIVISME):
        if record.is_justified:
            await cancel_record_on_justification(
                db, school_id, data.student_id, data.date, user.id
            )
        else:
            await create_record_from_attendance(
                db, school_id, data.student_id,
                data.period, academic_year,
                record.status, record.is_justified,
                user.id, data.date,
            )
    await db.flush()

    # ── Notification parent en cas d'absence non justifiée ────────
    notifications_sent = 0
    if record.status == StatutPresence.ABSENT and not record.is_justified:
        try:
            from app.services.notification_service import notify_absence_recorded
            notifications_sent = await notify_absence_recorded(
                db, school_id, data.student_id, str(data.date), record.id,
            )
        except Exception:  # ne pas bloquer l'appel
            pass

    return {"id": record.id, "status": record.status.value, "notifications_sent": notifications_sent}


@router.post("/bulk", status_code=201)
async def bulk_mark_attendance(
    data: BulkAttendance,
    user: User = Depends(require_permission("attendance.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark attendance for a whole class at once."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # ── Vérification FK croisée : la classe appartient-elle à cette école ?
    from app.models.class_ import Class
    class_ok = (await db.execute(
        select(Class.id).where(
            Class.id == data.class_id,
            Class.school_id == school_id,
        )
    )).scalar_one_or_none()
    if class_ok is None:
        raise HTTPException(status_code=404, detail="Classe introuvable dans cette école")

    created = 0
    updated = 0

    for entry in data.entries:
        # ── Vérification FK croisée : l'élève appartient-il à cette école ?
        student_ok = (await db.execute(
            select(Student.id).where(
                Student.id == entry["student_id"],
                Student.school_id == school_id,
            )
        )).scalar_one_or_none()
        if student_ok is None:
            continue  # Élève d'une autre école — ignoré silencieusement

        existing = (await db.execute(
            select(Attendance).where(
                Attendance.student_id == entry["student_id"],
                Attendance.date == data.date,
                Attendance.period == data.period,
                Attendance.slot_index == data.slot_index,
            )
        )).scalar_one_or_none()

        if existing:
            existing.status = StatutPresence(entry["status"])
            existing.minutes_late = entry.get("minutes_late")
            existing.recorded_by = user.id
            updated += 1
        else:
            record = Attendance(
                school_id=school_id,
                student_id=entry["student_id"],
                class_id=data.class_id,
                recorded_by=user.id,
                date=data.date,
                status=StatutPresence(entry["status"]),
                slot_index=data.slot_index,
                minutes_late=entry.get("minutes_late"),
                period=data.period,
            )
            db.add(record)
            created += 1

    await db.flush()

    # ── Discipline auto-records ──────────────────────────────────
    from app.services.discipline_service import create_record_from_attendance
    discipline_created = 0

    # Get academic year from school
    from app.models.school import School
    from app.models.academic_year import AcademicYear
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    academic_year = "2025-2026"  # fallback
    if school:
        ay = (await db.execute(
            select(AcademicYear).where(
                AcademicYear.school_id == school_id,
                AcademicYear.is_current == True,  # noqa: E712
            )
        )).scalar_one_or_none()
        if ay:
            academic_year = ay.name

    for entry in data.entries:
        status_val = StatutPresence(entry["status"])
        if status_val in (StatutPresence.ABSENT, StatutPresence.RETARD, StatutPresence.INCIVISME):
            is_just = bool(entry.get("is_justified", False))
            # For existing records, check if already justified
            existing_att = (await db.execute(
                select(Attendance).where(
                    Attendance.student_id == entry["student_id"],
                    Attendance.date == data.date,
                    Attendance.period == data.period,
                )
            )).scalar_one_or_none()
            if existing_att and existing_att.is_justified:
                is_just = True

            rec = await create_record_from_attendance(
                db, school_id, entry["student_id"],
                data.period, academic_year,
                status_val, is_just,
                user.id, data.date,
            )
            if rec:
                discipline_created += 1

    await db.flush()

    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="attendance.mark", resource="attendance", details={"class_id": data.class_id, "date": data.date, "created": created, "updated": updated})

    # ── Notifications parents pour les absences non justifiées ────
    notifications_sent = 0
    try:
        from app.services.notification_service import notify_absence_recorded
        for entry in data.entries:
            if entry["status"] == "absent" and not entry.get("is_justified", False):
                notifications_sent += await notify_absence_recorded(
                    db, school_id, entry["student_id"], str(data.date),
                )
    except Exception:
        pass

    return {"created": created, "updated": updated, "discipline_records": discipline_created,
            "notifications_sent": notifications_sent}


@router.get("/stats/{class_id}")
async def attendance_stats(
    class_id: int,
    period: str = Query(..., pattern="^(T[123]|S[12])$"),
    user: User = Depends(require_permission("attendance.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get attendance statistics for a class."""
    school_id = get_school_id(user)

    # Vérifier que la classe appartient à l'école de l'appelant
    cls = (await db.execute(
        select(Class).where(
            Class.id == class_id,
            Class.school_id == school_id,
        )
    )).scalar_one_or_none()
    if cls is None:
        raise HTTPException(status_code=404, detail="Classe introuvable dans cette école")

    student_ids = [
        e.student_id for e in (await db.execute(
            select(Enrollment).where(
                Enrollment.class_id == class_id,
                Enrollment.status == "active",
            )
        )).scalars().all()
    ]

    stats = []
    for sid in student_ids:
        counts = (await db.execute(
            select(
                Attendance.status,
                func.count(Attendance.id),
            ).where(
                Attendance.student_id == sid,
                Attendance.period == period,
                Attendance.school_id == school_id,
            ).group_by(Attendance.status)
        )).all()

        status_counts = {row[0].value if hasattr(row[0], 'value') else row[0]: row[1] for row in counts}
        student = (await db.execute(
            select(Student).where(
                Student.id == sid, Student.school_id == school_id
            )
        )).scalar_one_or_none()
        name = f"{student.first_name} {student.last_name}" if student else f"#{sid}"

        absences = status_counts.get("absent", 0)
        retards = status_counts.get("late", 0)
        incivismes = status_counts.get("incivisme", 0)

        conduite = 20.0 - (absences * 0.5) - (retards * 0.25) - (incivismes * 1.0)
        conduite = max(0, conduite)

        stats.append({
            "student_id": sid,
            "student_name": name,
            "total_days": sum(status_counts.values()),
            "presences": status_counts.get("present", 0),
            "absences": absences,
            "retards": retards,
            "incivismes": incivismes,
            "conduite": round(conduite, 1),
        })

    return {"stats": stats}


# ==============================================================
# Module complet — roster, justification, validation, stats, rapports
# ==============================================================

from app.services import attendance_service as att_svc  # noqa: E402


class JustifyRequest(BaseModel):
    """Demande de justification d'une absence."""
    justification: str = Field(..., min_length=3)


class JustifyDecision(BaseModel):
    decision: str = Field(..., pattern="^(accept|refuse)$")
    comment: str | None = None


@router.get("/roster")
async def attendance_roster(
    class_id: int,
    date_str: str | None = None,
    period: str = "T1",
    slot_index: int = 0,
    user: User = Depends(require_permission("attendance.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Liste d'appel d'une classe pour une date/période — statuts existants pré-remplis."""
    from datetime import date as _date
    school_id = get_school_id(user)
    on_date = _date.fromisoformat(date_str) if date_str else _date.today()
    roster = await att_svc.get_roster(db, school_id, class_id, on_date, period, slot_index)
    if roster is None:
        raise HTTPException(status_code=404, detail="Classe introuvable dans cette école")
    return roster


@router.get("/justifications/pending")
async def list_pending_justifications(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("attendance.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Absences à justifier (workflow admin)."""
    school_id = get_school_id(user)
    return await att_svc.pending_justifications(db, school_id, page, per_page)


@router.post("/{attendance_id}/justify", status_code=200)
async def request_justification(
    attendance_id: int,
    data: JustifyRequest,
    user: User = Depends(require_permission("attendance.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Un enseignant/admin soumet une justification → statut 'en attente'."""
    school_id = get_school_id(user)
    att = (await db.execute(
        select(Attendance).where(
            Attendance.id == attendance_id, Attendance.school_id == school_id
        )
    )).scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="Présence introuvable dans cette école")
    att.justification = data.justification
    att.justification_status = "pending"
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="attendance.justify_request",
                     resource="attendance", details={"attendance_id": attendance_id})
    return {"id": att.id, "justification_status": "pending"}


@router.post("/{attendance_id}/justify/decision", status_code=200)
async def decide_justification(
    attendance_id: int,
    data: JustifyDecision,
    user: User = Depends(require_permission("attendance.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin : accepter ou refuser une justification (→ notifie le parent si accepté)."""
    school_id = get_school_id(user)
    att = await att_svc.decide_justification(
        db, school_id, attendance_id, data.decision, data.comment, user.id
    )
    if att is None:
        raise HTTPException(status_code=404, detail="Présence introuvable dans cette école")
    await db.flush()

    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="attendance.justify_decision",
                     resource="attendance", details={"attendance_id": attendance_id, "decision": data.decision})

    # Notifier le parent si la justification est acceptée
    if data.decision == "accept":
        try:
            from app.services.notification_service import notify_absence_justified
            await notify_absence_justified(db, school_id, att.student_id, str(att.date))
        except Exception:
            pass

    return {"id": att.id, "justification_status": att.justification_status,
            "is_justified": att.is_justified}


@router.post("/{attendance_id}/validate", status_code=200)
async def validate_attendance(
    attendance_id: int,
    user: User = Depends(require_permission("attendance.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Valider (verrouiller) un enregistrement de présence."""
    school_id = get_school_id(user)
    att = (await db.execute(
        select(Attendance).where(
            Attendance.id == attendance_id, Attendance.school_id == school_id
        )
    )).scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="Présence introuvable dans cette école")
    from datetime import datetime as _dt
    att.validated = True
    att.validated_by = user.id
    att.validated_at = _dt.utcnow()
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="attendance.validate",
                     resource="attendance", details={"attendance_id": attendance_id})
    return {"id": att.id, "validated": True}


@router.get("/dashboard/today")
async def admin_dashboard_today(
    date_str: str | None = None,
    user: User = Depends(require_permission("attendance.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Tableau de bord admin : stats du jour + anomalies (absences répétées, classes à risque)."""
    from datetime import date as _date
    school_id = get_school_id(user)
    on_date = _date.fromisoformat(date_str) if date_str else _date.today()
    return await att_svc.admin_dashboard(db, school_id, on_date)


@router.get("/reports/monthly")
async def monthly_attendance_report(
    year: int,
    month: int = Query(..., ge=1, le=12),
    class_id: int | None = None,
    user: User = Depends(require_permission("attendance.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rapport mensuel par élève, filtrable par classe."""
    school_id = get_school_id(user)
    if class_id:
        cls_ok = (await db.execute(
            select(Class.id).where(Class.id == class_id, Class.school_id == school_id)
        )).scalar_one_or_none()
        if cls_ok is None:
            raise HTTPException(status_code=404, detail="Classe introuvable dans cette école")
    return await att_svc.monthly_report(db, school_id, year, month, class_id)
