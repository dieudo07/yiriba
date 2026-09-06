"""Yiriba SaaS — Service présences : appel rapide, justifications, statistiques.

Réutilise le modèle Attendance existant (étendu par attendance_ext).
Toutes les opérations filtrent par school_id (multi-tenant).
"""
import math
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import Attendance, StatutPresence
from app.models.class_ import Class, Enrollment
from app.models.student import Student


def _str(v) -> str:
    """Convertit en str (les colonnes ajoutées dynamiquement retournent des types SQLAlchemy)."""
    return v if isinstance(v, str) else (v.value if hasattr(v, "value") else str(v))


def _bool(v) -> bool:
    return bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "t", "yes")


async def get_roster(
    db: AsyncSession, school_id: int, class_id: int, on_date: date, period: str, slot_index: int = 0
) -> dict:
    """Liste d'appel : tous les élèves inscrits + leur statut existant (upsert-friendly)."""
    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if cls is None:
        return None

    students = (await db.execute(
        select(Student.id, Student.first_name, Student.last_name, Student.matricule)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
            Student.school_id == school_id,
        )
        .order_by(Student.last_name, Student.first_name)
    )).all()

    records = (await db.execute(
        select(Attendance).where(
            Attendance.class_id == class_id,
            Attendance.school_id == school_id,
            Attendance.date == on_date,
            Attendance.period == period,
            Attendance.slot_index == slot_index,
        )
    )).scalars().all()
    by_student = {a.student_id: a for a in records}

    roster = []
    for s in students:
        a = by_student.get(s.id)
        roster.append({
            "student_id": s.id,
            "first_name": s.first_name,
            "last_name": s.last_name,
            "matricule": s.matricule,
            "status": a.status.value if a else "present",
            "minutes_late": a.minutes_late if a else None,
            "justification": a.justification if a else None,
            "justification_status": _str(a.justification_status) if a else "none",
            "comment": _str(a.comment) if a and a.comment is not None else None,
            "attendance_id": a.id if a else None,
            "validated": _bool(a.validated) if a else False,
        })

    return {
        "class_id": class_id,
        "class_name": cls.name,
        "date": str(on_date),
        "period": period,
        "slot_index": slot_index,
        "count": len(roster),
        "students": roster,
        "already_recorded": len(records) > 0,
    }


async def decide_justification(
    db: AsyncSession, school_id: int, attendance_id: int, decision: str,
    reviewer_comment: str | None, reviewer_id: int,
) -> Attendance | None:
    """Accepte ou refuse une justification (workflow : pending → accepted/refused)."""
    att = (await db.execute(
        select(Attendance).where(
            Attendance.id == attendance_id, Attendance.school_id == school_id
        )
    )).scalar_one_or_none()
    if att is None:
        return None

    if decision == "accept":
        att.is_justified = True
        att.justification_status = "accepted"
    else:
        att.is_justified = False
        att.justification_status = "refused"
    if reviewer_comment:
        att.comment = reviewer_comment
    await db.flush()
    return att


async def pending_justifications(
    db: AsyncSession, school_id: int, page: int = 1, per_page: int = 50
) -> dict:
    """Absences/retards dont la justification est en attente."""
    query = select(Attendance).where(
        Attendance.school_id == school_id,
        Attendance.justification_status == "pending",
    )
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    records = (await db.execute(
        query.order_by(Attendance.date.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()

    student_ids = list({a.student_id for a in records})
    studs = {}
    if student_ids:
        rows = (await db.execute(
            select(Student.id, Student.first_name, Student.last_name, Student.matricule)
            .where(Student.id.in_(student_ids))
        )).all()
        studs = {s.id: s for s in rows}

    return {
        "total": total,
        "items": [{
            "id": a.id,
            "student_id": a.student_id,
            "student_name": f"{studs[a.student_id].last_name} {studs[a.student_id].first_name}" if a.student_id in studs else f"#{a.student_id}",
            "matricule": studs[a.student_id].matricule if a.student_id in studs else None,
            "date": str(a.date),
            "period": a.period,
            "status": a.status.value,
            "justification": a.justification,
        } for a in records],
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


async def admin_dashboard(db: AsyncSession, school_id: int, on_date: date) -> dict:
    """Tableau de bord admin : aujourd'hui + classes les plus absentes + absences répétées."""
    today_rows = (await db.execute(
        select(Attendance.status, func.count(Attendance.id)).where(
            Attendance.school_id == school_id, Attendance.date == on_date
        ).group_by(Attendance.status)
    )).all()
    by_status = {r[0].value if hasattr(r[0], "value") else r[0]: r[1] for r in today_rows}

    # Classes avec le plus d'absences (30 derniers jours)
    since = on_date - timedelta(days=30)
    class_abs = (await db.execute(
        select(Attendance.class_id, func.count(Attendance.id))
        .where(
            Attendance.school_id == school_id,
            Attendance.status == StatutPresence.ABSENT,
            Attendance.date >= since,
        )
        .group_by(Attendance.class_id)
        .order_by(func.count(Attendance.id).desc())
        .limit(5)
    )).all()
    class_ids = [r[0] for r in class_abs]
    classes_names = {}
    if class_ids:
        rows = (await db.execute(select(Class.id, Class.name).where(Class.id.in_(class_ids)))).all()
        classes_names = {r[0]: r[1] for r in rows}

    # Élèves avec absences répétées (>= 3 sur 30 jours)
    repeat_rows = (await db.execute(
        select(Attendance.student_id, func.count(Attendance.id))
        .where(
            Attendance.school_id == school_id,
            Attendance.status == StatutPresence.ABSENT,
            Attendance.date >= since,
        )
        .group_by(Attendance.student_id)
        .having(func.count(Attendance.id) >= 3)
        .order_by(func.count(Attendance.id).desc())
        .limit(10)
    )).all()
    repeat_ids = [r[0] for r in repeat_rows]
    studs = {}
    if repeat_ids:
        rows = (await db.execute(
            select(Student.id, Student.first_name, Student.last_name).where(Student.id.in_(repeat_ids))
        )).all()
        studs = {r[0]: r for r in rows}

    return {
        "date": str(on_date),
        "today": {
            "present": by_status.get("present", 0),
            "absent": by_status.get("absent", 0),
            "late": by_status.get("late", 0),
            "excused": by_status.get("excused", 0),
            "total": sum(by_status.values()),
        },
        "classes_most_absent": [
            {"class_id": cid, "class_name": classes_names.get(cid, f"#{cid}"), "absences": n}
            for cid, n in class_abs
        ],
        "repeat_absentees": [
            {"student_id": sid,
             "student_name": f"{studs[sid].last_name} {studs[sid].first_name}" if sid in studs else f"#{sid}",
             "absences": n}
            for sid, n in repeat_rows
        ],
    }


async def monthly_report(
    db: AsyncSession, school_id: int, year: int, month: int,
    class_id: int | None = None,
) -> dict:
    """Rapport mensuel : stats par élève (ou par classe) sur le mois."""
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    query = select(Attendance).where(
        Attendance.school_id == school_id,
        Attendance.date >= start,
        Attendance.date < end,
    )
    if class_id:
        query = query.where(Attendance.class_id == class_id)
    records = (await db.execute(query)).scalars().all()

    per_student: dict[int, dict] = {}
    for a in records:
        d = per_student.setdefault(a.student_id, {
            "present": 0, "absent": 0, "late": 0, "excused": 0,
        })
        key = a.status.value if hasattr(a.status, "value") else a.status
        if key in d:
            d[key] += 1

    student_ids = list(per_student.keys())
    studs = {}
    if student_ids:
        rows = (await db.execute(
            select(Student.id, Student.first_name, Student.last_name, Student.matricule)
            .where(Student.id.in_(student_ids))
        )).all()
        studs = {r[0]: r for r in rows}

    items = []
    for sid, counts in per_student.items():
        total = sum(counts.values())
        s = studs.get(sid)
        items.append({
            "student_id": sid,
            "student_name": f"{s.last_name} {s.first_name}" if s else f"#{sid}",
            "matricule": s.matricule if s else None,
            **counts,
            "total": total,
            "rate": round(counts["present"] / total * 100, 1) if total else 0,
        })
    items.sort(key=lambda x: x["student_name"])
    return {"year": year, "month": month, "class_id": class_id, "items": items}
