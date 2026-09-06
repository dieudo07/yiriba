"""Yiriba SaaS — Teacher Portal routes.

L'enseignant ne voit QUE ses classes/matières assignées via TeacherClass.
Filtrage par ownership : teacher_id vérifié sur chaque requête.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.models.attendance import Attendance, StatutPresence
from app.models.class_ import Class, Enrollment, Subject, TeacherClass
from app.models.grade import Evaluation, Grade
from app.models.student import Student
from app.models.user import User, UserRole

router = APIRouter(prefix="/api/teacher", tags=["teacher_portal"])


# --- Schemas ---


class TeacherGradeEntry(BaseModel):
    student_id: int
    grade: float = Field(..., ge=0, le=20)
    comment: str | None = None


class TeacherBulkGrades(BaseModel):
    evaluation_id: int
    grades: list[TeacherGradeEntry]


class TeacherAttendanceEntry(BaseModel):
    student_id: int
    status: StatutPresence
    minutes_late: int | None = None


class TeacherBulkAttendance(BaseModel):
    class_id: int
    date: date
    period: str = Field(..., pattern="^(T[123]|S[12])$")
    slot_index: int = Field(default=0, ge=0)
    entries: list[TeacherAttendanceEntry]


# --- Helper: verify teacher owns the class/subject ---


async def _verify_teacher_class(
    db: AsyncSession, teacher_id: int, class_id: int, subject_id: int | None = None
) -> TeacherClass:
    """Verify that the teacher is assigned to this class (and optionally subject)."""
    query = select(TeacherClass).where(
        TeacherClass.teacher_id == teacher_id,
        TeacherClass.class_id == class_id,
    )
    if subject_id:
        query = query.where(TeacherClass.subject_id == subject_id)

    tc = (await db.execute(query)).scalar_one_or_none()
    if not tc:
        raise HTTPException(
            status_code=403,
            detail="Vous n'êtes pas assigné à cette classe/matière"
        )
    return tc


# --- My Classes ---


@router.get("/my-classes")
async def my_classes(
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List classes assigned to this teacher."""
    school_id = get_school_id(user)

    teacher_classes = (await db.execute(
        select(TeacherClass).where(
            TeacherClass.teacher_id == user.id,
            TeacherClass.school_id == school_id,
        )
    )).scalars().all()

    # Deduplicate classes (teacher may have multiple subjects in same class)
    class_map: dict[int, dict] = {}
    for tc in teacher_classes:
        if tc.class_id not in class_map:
            cls = (await db.execute(
                select(Class).where(Class.id == tc.class_id)
            )).scalar_one_or_none()
            class_map[tc.class_id] = {
                "id": cls.id if cls else tc.class_id,
                "name": cls.name if cls else "?",
                "level": cls.level if cls else None,
                "subjects": [],
            }
        subj = (await db.execute(
            select(Subject).where(Subject.id == tc.subject_id)
        )).scalar_one_or_none()
        class_map[tc.class_id]["subjects"].append({
            "id": tc.subject_id,
            "name": subj.name if subj else "?",
            "is_primary": tc.is_primary,
        })

    return {"classes": list(class_map.values())}


# --- My Students ---


@router.get("/my-students/{class_id}")
async def my_students(
    class_id: int,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List students in a class — only if teacher is assigned to it."""
    school_id = get_school_id(user)
    await _verify_teacher_class(db, user.id, class_id)

    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
    )).scalars().all()

    students = []
    for e in enrollments:
        student = (await db.execute(
            select(Student).where(Student.id == e.student_id, Student.school_id == school_id)
        )).scalar_one_or_none()
        if student:
            students.append({
                "id": student.id,
                "matricule": student.matricule,
                "first_name": student.first_name,
                "last_name": student.last_name,
                "gender": student.gender,
            })

    return {"students": students, "total": len(students)}


# --- My Evaluations ---


@router.get("/my-evaluations")
async def my_evaluations(
    class_id: int | None = None,
    user: User = Depends(require_permission("evaluation.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List evaluations created by this teacher."""
    school_id = get_school_id(user)

    query = select(Evaluation).where(
        Evaluation.teacher_id == user.id,
        Evaluation.school_id == school_id,
    )
    if class_id:
        query = query.where(Evaluation.class_id == class_id)

    evals = (await db.execute(query.order_by(Evaluation.date.desc()))).scalars().all()

    return {
        "evaluations": [
            {
                "id": e.id, "name": e.name, "class_id": e.class_id,
                "subject_id": e.subject_id, "assessment_type": e.assessment_type,
                "period": e.period, "date": str(e.date),
                "is_published": e.is_published,
            }
            for e in evals
        ]
    }


# --- Grade Entry (filtered by TeacherClass) ---


@router.post("/grades/bulk", status_code=201)
async def teacher_bulk_grades(
    data: TeacherBulkGrades,
    user: User = Depends(require_permission("grade.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Saisie de notes en grille — vérifie que l'enseignant est assigné."""
    school_id = get_school_id(user)

    # Verify evaluation exists and belongs to school
    evaluation = (await db.execute(
        select(Evaluation).where(
            Evaluation.id == data.evaluation_id,
            Evaluation.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    if evaluation.is_published:
        raise HTTPException(status_code=400, detail="Évaluation publiée — notes gelées")

    # Verify teacher is assigned to this class/subject
    await _verify_teacher_class(db, user.id, evaluation.class_id, evaluation.subject_id)

    # Validate that every student_id belongs to the school and is enroled
    # in the evaluation's class (interdit les enregistrements orphelins /
    # cross-école).
    valid_student_ids = set((await db.execute(
        select(Enrollment.student_id).where(
            Enrollment.class_id == evaluation.class_id,
            Enrollment.school_id == school_id,
            Enrollment.status == "active",
        )
    )).scalars().all())
    invalid_ids = [e.student_id for e in data.grades if e.student_id not in valid_student_ids]
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Élève(s) non inscrit(s) dans cette classe : {invalid_ids}",
        )

    created = 0
    updated = 0
    for entry in data.grades:
        existing = (await db.execute(
            select(Grade).where(
                Grade.evaluation_id == data.evaluation_id,
                Grade.student_id == entry.student_id,
            )
        )).scalar_one_or_none()

        if existing:
            existing.grade = entry.grade
            existing.comment = entry.comment
            existing.teacher_id = user.id
            existing.modified_at = datetime.utcnow()
            existing.modified_by = user.id
            updated += 1
        else:
            grade = Grade(
                school_id=school_id,
                evaluation_id=data.evaluation_id,
                student_id=entry.student_id,
                teacher_id=user.id,
                grade=entry.grade,
                comment=entry.comment,
            )
            db.add(grade)
            created += 1

    await db.flush()
    return {"created": created, "updated": updated}


# --- Attendance Entry (filtered by TeacherClass) ---


@router.post("/attendance/bulk", status_code=201)
async def teacher_bulk_attendance(
    data: TeacherBulkAttendance,
    user: User = Depends(require_permission("attendance.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pointage de présences — vérifie que l'enseignant est assigné à la classe."""
    school_id = get_school_id(user)
    await _verify_teacher_class(db, user.id, data.class_id)

    # Validate that every student_id is enroled in this class (even across
    # the school boundary when a stale ID is submitted).
    valid_student_ids = set((await db.execute(
        select(Enrollment.student_id).where(
            Enrollment.class_id == data.class_id,
            Enrollment.school_id == school_id,
            Enrollment.status == "active",
        )
    )).scalars().all())
    invalid_ids = [e.student_id for e in data.entries if e.student_id not in valid_student_ids]
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Élève(s) non inscrit(s) dans cette classe : {invalid_ids}",
        )

    created = 0
    updated = 0
    for entry in data.entries:
        existing = (await db.execute(
            select(Attendance).where(
                Attendance.student_id == entry.student_id,
                Attendance.date == data.date,
                Attendance.period == data.period,
                Attendance.slot_index == data.slot_index,
            )
        )).scalar_one_or_none()

        if existing:
            existing.status = entry.status
            existing.minutes_late = entry.minutes_late
            existing.recorded_by = user.id
            updated += 1
        else:
            record = Attendance(
                school_id=school_id,
                student_id=entry.student_id,
                class_id=data.class_id,
                recorded_by=user.id,
                date=data.date,
                status=entry.status,
                slot_index=data.slot_index,
                minutes_late=entry.minutes_late,
                period=data.period,
            )
            db.add(record)
            created += 1

    await db.flush()
    return {"created": created, "updated": updated}


# --- Timetable (from TeacherClass assignments) ---


@router.get("/timetable")
async def my_timetable(
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get teacher's timetable from TeacherClass assignments."""
    school_id = get_school_id(user)

    teacher_classes = (await db.execute(
        select(TeacherClass).where(
            TeacherClass.teacher_id == user.id,
            TeacherClass.school_id == school_id,
        )
    )).scalars().all()

    timetable = []
    for tc in teacher_classes:
        cls = (await db.execute(
            select(Class).where(Class.id == tc.class_id)
        )).scalar_one_or_none()
        subj = (await db.execute(
            select(Subject).where(Subject.id == tc.subject_id)
        )).scalar_one_or_none()

        timetable.append({
            "class_id": tc.class_id,
            "class_name": cls.name if cls else "?",
            "subject_id": tc.subject_id,
            "subject_name": subj.name if subj else "?",
            "is_primary": tc.is_primary,
        })

    return {"timetable": timetable}
