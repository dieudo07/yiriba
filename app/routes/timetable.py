"""Yiriba SaaS — Timetable routes: TimeSlot CRUD + schedule CRUD + conflict detection."""

from datetime import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.models.timetable import Timetable, TimeSlot
from app.models.class_ import Class, ClassSubject, TeacherClass
from app.models.user import User
from app.services.audit_service import safe_audit

router = APIRouter(prefix="/api/timetable", tags=["timetable"])

DAYS = {0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi", 4: "Vendredi", 5: "Samedi", 6: "Dimanche"}


# ---------------------------------------------------------------------------
# TimeSlot schemas
# ---------------------------------------------------------------------------
class TimeSlotCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=50)
    start_time: str  # "08:00"
    end_time: str    # "09:00"
    display_order: int = 0


class TimeSlotUpdate(BaseModel):
    label: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Timetable schemas
# ---------------------------------------------------------------------------
class TimetableCreate(BaseModel):
    class_id: int
    subject_id: int
    teacher_id: int | None = None
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str  # "08:00"
    end_time: str    # "09:00"
    room: str | None = None


class TimetableUpdate(BaseModel):
    class_id: int | None = None
    subject_id: int | None = None
    teacher_id: int | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: str | None = None
    end_time: str | None = None
    room: str | None = None
    is_active: bool | None = None


def _parse_time(t: str) -> time:
    parts = t.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


# ---------------------------------------------------------------------------
# TimeSlot CRUD
# ---------------------------------------------------------------------------
@router.get("/slots")
async def list_time_slots(
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    result = await db.execute(
        select(TimeSlot)
        .where(TimeSlot.school_id == school_id, TimeSlot.is_active == True)  # noqa: E712
        .order_by(TimeSlot.display_order, TimeSlot.start_time)
    )
    slots = result.scalars().all()
    return {
        "time_slots": [
            {
                "id": s.id,
                "label": s.label,
                "start_time": s.start_time.strftime("%H:%M") if s.start_time else "",
                "end_time": s.end_time.strftime("%H:%M") if s.end_time else "",
                "display_order": s.display_order,
                "is_active": s.is_active,
            }
            for s in slots
        ]
    }


@router.post("/slots", status_code=201)
async def create_time_slot(
    data: TimeSlotCreate,
    user: User = Depends(require_permission("class.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    slot = TimeSlot(
        school_id=school_id,
        label=data.label,
        start_time=_parse_time(data.start_time),
        end_time=_parse_time(data.end_time),
        display_order=data.display_order,
    )
    db.add(slot)
    await db.flush()
    await safe_audit(db, school_id=school_id, user_id=user.id, action="timetable.slot.create", resource="time_slot", resource_id=slot.id)
    return {"id": slot.id, "message": "Creneau horaire cree"}


@router.patch("/slots/{slot_id}")
async def update_time_slot(
    slot_id: int,
    data: TimeSlotUpdate,
    user: User = Depends(require_permission("class.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    slot = (await db.execute(
        select(TimeSlot).where(TimeSlot.id == slot_id, TimeSlot.school_id == school_id)
    )).scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=404, detail="Creneau introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in ("start_time", "end_time") and value:
            setattr(slot, field, _parse_time(value))
        else:
            setattr(slot, field, value)
    await db.flush()
    await safe_audit(db, school_id=school_id, user_id=user.id, action="timetable.slot.update", resource="time_slot", resource_id=slot.id)
    return {"id": slot.id, "message": "Mis a jour"}


@router.delete("/slots/{slot_id}", status_code=204)
async def delete_time_slot(
    slot_id: int,
    user: User = Depends(require_permission("class.update")),
    db: AsyncSession = Depends(get_db),
) -> None:
    school_id = get_school_id(user)
    slot = (await db.execute(
        select(TimeSlot).where(TimeSlot.id == slot_id, TimeSlot.school_id == school_id)
    )).scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=404, detail="Creneau introuvable")
    slot.is_active = False
    await db.flush()
    await safe_audit(db, school_id=school_id, user_id=user.id, action="timetable.slot.delete", resource="time_slot", resource_id=slot.id)


# ---------------------------------------------------------------------------
# Conflict detection helper
# ---------------------------------------------------------------------------
async def _check_conflicts(
    db: AsyncSession,
    school_id: int,
    day_of_week: int,
    start_time: time,
    end_time: time,
    class_id: int,
    teacher_id: int | None,
    room: str | None,
    exclude_id: int | None = None,
) -> str | None:
    """Return error message if a conflict exists, else None."""
    # Build overlap condition: existing.start < new.end AND existing.end > new.start
    overlap = and_(
        Timetable.school_id == school_id,
        Timetable.is_active == True,  # noqa: E712
        Timetable.day_of_week == day_of_week,
        Timetable.start_time < end_time,
        Timetable.end_time > start_time,
    )
    if exclude_id:
        overlap = and_(overlap, Timetable.id != exclude_id)

    result = await db.execute(select(Timetable).where(overlap))
    conflicts = result.scalars().all()

    for c in conflicts:
        # Class conflict
        if c.class_id == class_id:
            return f"La classe a deja un cours de {c.start_time.strftime('%H:%M')} a {c.end_time.strftime('%H:%M')} ce jour."
        # Teacher conflict
        if teacher_id and c.teacher_id == teacher_id:
            # Fetch teacher name
            teacher_result = await db.execute(select(User).where(User.id == teacher_id))
            teacher = teacher_result.scalar_one_or_none()
            name = f"{teacher.first_name} {teacher.last_name}" if teacher else f"Enseignant #{teacher_id}"
            return f"{name} a deja un cours de {c.start_time.strftime('%H:%M')} a {c.end_time.strftime('%H:%M')} ce jour."
        # Room conflict
        if room and c.room and c.room == room:
            return f"La salle {room} est deja reservee de {c.start_time.strftime('%H:%M')} a {c.end_time.strftime('%H:%M')} ce jour."

    return None


# ---------------------------------------------------------------------------
# Timetable CRUD
# ---------------------------------------------------------------------------
@router.get("")
async def list_timetable(
    class_id: int | None = None,
    day_of_week: int | None = None,
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(Timetable).where(Timetable.school_id == school_id, Timetable.is_active == True)  # noqa: E712
    if class_id:
        query = query.where(Timetable.class_id == class_id)
    if day_of_week is not None:
        query = query.where(Timetable.day_of_week == day_of_week)
    query = query.order_by(Timetable.day_of_week, Timetable.start_time)

    result = await db.execute(query)
    entries = result.scalars().all()
    return {
        "timetable": [
            {
                "id": e.id,
                "class_id": e.class_id,
                "subject_id": e.subject_id,
                "teacher_id": e.teacher_id,
                "day_of_week": e.day_of_week,
                "day_name": DAYS.get(e.day_of_week, ""),
                "start_time": e.start_time.strftime("%H:%M") if e.start_time else "",
                "end_time": e.end_time.strftime("%H:%M") if e.end_time else "",
                "room": e.room,
            }
            for e in entries
        ]
    }


@router.post("", status_code=201)
async def create_timetable(
    data: TimetableCreate,
    user: User = Depends(require_permission("class.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    st = _parse_time(data.start_time)
    et = _parse_time(data.end_time)

    # Conflict check
    err = await _check_conflicts(db, school_id, data.day_of_week, st, et, data.class_id, data.teacher_id, data.room)
    if err:
        raise HTTPException(status_code=409, detail=err)

    # Get active academic year
    ay_result = await db.execute(
        select(Class).where(Class.id == data.class_id, Class.school_id == school_id)
    )
    cls = ay_result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    entry = Timetable(
        school_id=school_id,
        class_id=data.class_id,
        subject_id=data.subject_id,
        teacher_id=data.teacher_id,
        day_of_week=data.day_of_week,
        start_time=st,
        end_time=et,
        room=data.room,
        academic_year_id=cls.academic_year_id,
    )
    db.add(entry)
    await db.flush()
    await safe_audit(db, school_id=school_id, user_id=user.id, action="timetable.create", resource="timetable", resource_id=entry.id)
    return {"id": entry.id, "message": "Cours ajoute"}


@router.patch("/{entry_id}")
async def update_timetable(
    entry_id: int,
    data: TimetableUpdate,
    user: User = Depends(require_permission("class.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    entry = (await db.execute(
        select(Timetable).where(Timetable.id == entry_id, Timetable.school_id == school_id)
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Creneau introuvable")

    # Apply updates
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in ("start_time", "end_time") and value:
            setattr(entry, field, _parse_time(value))
        else:
            setattr(entry, field, value)

    # Conflict check with updated values
    err = await _check_conflicts(
        db, school_id,
        entry.day_of_week, entry.start_time, entry.end_time,
        entry.class_id, entry.teacher_id, entry.room,
        exclude_id=entry_id,
    )
    if err:
        raise HTTPException(status_code=409, detail=err)

    await db.flush()
    await safe_audit(db, school_id=school_id, user_id=user.id, action="timetable.update", resource="timetable", resource_id=entry.id)
    return {"id": entry.id, "message": "Mis a jour"}


@router.delete("/{entry_id}", status_code=204)
async def delete_timetable(
    entry_id: int,
    user: User = Depends(require_permission("class.update")),
    db: AsyncSession = Depends(get_db),
) -> None:
    school_id = get_school_id(user)
    entry = (await db.execute(
        select(Timetable).where(Timetable.id == entry_id, Timetable.school_id == school_id)
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Creneau introuvable")
    entry.is_active = False
    await db.flush()
    await safe_audit(db, school_id=school_id, user_id=user.id, action="timetable.delete", resource="timetable", resource_id=entry.id)
