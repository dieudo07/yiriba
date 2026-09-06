"""Yiriba SaaS — Grade routes with Evaluation + Grade models.

Evaluation = un devoir donné à toute une classe (D/1, D/2, Comp.)
Grade = la note d'un élève pour cette évaluation

Moyennes calculées à la volée (pas stockées en base).
Le bulletin publié est un snapshot figé dans la table bulletins.
"""

import math
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.services.subscription_service import require_write_access
from app.models.class_ import Class, Enrollment, TeacherClass, Subject
from app.models.grade import Evaluation, Grade
from app.models.student import Student
from app.models.user import User

router = APIRouter(prefix="/api/grades", tags=["grades"])


# --- Schemas ---


class EvaluationCreate(BaseModel):
    class_id: int
    subject_id: int
    name: str = Field(..., min_length=1, max_length=100)
    assessment_type: str = Field(..., pattern="^(devoir|devoir1|devoir2|composition|controle|examen)$")
    period: str = Field(..., pattern="^(T[123]|S[12])$")
    academic_year: str = Field(default="2025-2026", max_length=10)
    academic_period_id: int | None = None  # Optional: link to AcademicPeriod
    max_grade: float = Field(default=20.0, gt=0)
    coefficient: int = Field(default=1, ge=1)
    date: str | None = None  # ISO date string


class GradeEntry(BaseModel):
    student_id: int
    grade: float | None = Field(default=None, ge=0, le=20)
    status: str = Field(default="graded", pattern="^(graded|absent|excused|empty)$")
    comment: str | None = Field(default=None, max_length=200)


class BulkGradeEntry(BaseModel):
    """Saisie de notes en grille pour toute une classe."""
    evaluation_id: int
    grades: list[GradeEntry]


class GradeUpdate(BaseModel):
    grade: float = Field(..., ge=0, le=20)
    comment: str | None = Field(default=None, max_length=200)


# --- Evaluation CRUD ---


@router.get("/evaluations")
async def list_evaluations(
    class_id: int | None = None,
    subject_id: int | None = None,
    period: str | None = None,
    academic_period_id: int | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("evaluation.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(Evaluation).where(Evaluation.school_id == school_id)

    if class_id:
        query = query.where(Evaluation.class_id == class_id)
    if subject_id:
        query = query.where(Evaluation.subject_id == subject_id)
    if period:
        query = query.where(Evaluation.period == period)
    if academic_period_id:
        query = query.where(Evaluation.academic_period_id == academic_period_id)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    evals = (await db.execute(
        query.order_by(Evaluation.date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    return {
        "evaluations": [
            {
                "id": e.id, "class_id": e.class_id, "subject_id": e.subject_id,
                "name": e.name, "assessment_type": e.assessment_type,
                "period": e.period, "max_grade": e.max_grade,
                "coefficient": e.coefficient, "date": str(e.date),
                "is_published": e.is_published, "academic_period_id": e.academic_period_id,
            }
            for e in evals
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


@router.post("/evaluations", status_code=201)
async def create_evaluation(
    data: EvaluationCreate,
    user: User = Depends(require_permission("evaluation.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create an evaluation (devoir1/devoir2/comp) for a class/subject."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Verify class and subject belong to school
    cls = (await db.execute(
        select(Class).where(Class.id == data.class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    subject = (await db.execute(
        select(Subject).where(Subject.id == data.subject_id, Subject.school_id == school_id)
    )).scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Matière introuvable")

    # Check uniqueness
    existing = (await db.execute(
        select(Evaluation).where(
            Evaluation.class_id == data.class_id,
            Evaluation.subject_id == data.subject_id,
            Evaluation.assessment_type == data.assessment_type,
            Evaluation.period == data.period,
            Evaluation.school_id == school_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Une évaluation de ce type existe déjà pour cette classe/matière/période")

    evaluation = Evaluation(
        school_id=school_id,
        class_id=data.class_id,
        subject_id=data.subject_id,
        teacher_id=user.id,
        name=data.name.strip(),
        assessment_type=data.assessment_type,
        period=data.period,
        academic_year=data.academic_year,
        academic_period_id=data.academic_period_id,
        max_grade=data.max_grade,
        coefficient=data.coefficient,
        date=date.fromisoformat(data.date) if data.date else None,
    )
    db.add(evaluation)
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="evaluation.create", resource="evaluation", resource_id=evaluation.id, details={"name": evaluation.name, "period": evaluation.period})
    return {"id": evaluation.id, "name": evaluation.name}


@router.put("/evaluations/{evaluation_id}/publish")
async def publish_evaluation(
    evaluation_id: int,
    user: User = Depends(require_permission("evaluation.update")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish an evaluation — freezes grades, prevents further modifications."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    evaluation = (await db.execute(
        select(Evaluation).where(Evaluation.id == evaluation_id, Evaluation.school_id == school_id)
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")

    evaluation.is_published = True
    evaluation.published_at = datetime.utcnow()
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="evaluation.publish", resource="evaluation", resource_id=evaluation.id)
    return {"id": evaluation.id, "is_published": True}


@router.delete("/evaluations/{evaluation_id}", status_code=204)
async def delete_evaluation(
    evaluation_id: int,
    user: User = Depends(require_permission("evaluation.delete")),

    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an evaluation and all its grades."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    evaluation = (await db.execute(
        select(Evaluation).where(Evaluation.id == evaluation_id, Evaluation.school_id == school_id)
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    if evaluation.is_published:
        raise HTTPException(status_code=400, detail="Impossible de supprimer une évaluation publiée")
    eval_id = evaluation.id
    eval_name = evaluation.name
    await db.delete(evaluation)
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="evaluation.delete", resource="evaluation", resource_id=eval_id, details={"name": eval_name})


# --- Grade CRUD ---


@router.get("")
async def list_grades(
    class_id: int | None = None,
    subject_id: int | None = None,
    student_id: int | None = None,
    evaluation_id: int | None = None,
    period: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = (
        select(Grade)
        .join(Evaluation, Evaluation.id == Grade.evaluation_id)
        .where(Grade.school_id == school_id)
    )

    if class_id:
        query = query.where(Evaluation.class_id == class_id)
    if subject_id:
        query = query.where(Evaluation.subject_id == subject_id)
    if student_id:
        query = query.where(Grade.student_id == student_id)
    if evaluation_id:
        query = query.where(Grade.evaluation_id == evaluation_id)
    if period:
        query = query.where(Evaluation.period == period)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    grades = (await db.execute(
        query.order_by(Grade.entered_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    return {
        "grades": [
            {
                "id": g.id, "evaluation_id": g.evaluation_id, "student_id": g.student_id,
                "grade": g.grade, "comment": g.comment,
            }
            for g in grades
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


@router.post("", status_code=201)
async def create_or_update_grade(
    data: BulkGradeEntry,
    user: User = Depends(require_permission("grade.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create or update grades for an evaluation (bulk entry for a class)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Verify evaluation belongs to school and is not published
    evaluation = (await db.execute(
        select(Evaluation).where(Evaluation.id == data.evaluation_id, Evaluation.school_id == school_id)
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    if evaluation.is_published:
        raise HTTPException(status_code=400, detail="Cette évaluation est publiée — notes gelées")

    created = 0
    updated = 0
    for entry in data.grades:
        # ── Vérification FK croisée : l'élève appartient-il à cette école ?
        student_ok = (await db.execute(
            select(Student.id).where(
                Student.id == entry.student_id,
                Student.school_id == school_id,
            )
        )).scalar_one_or_none()
        if student_ok is None:
            continue  # Élève d'une autre école — ignoré silencieusement

        existing = (await db.execute(
            select(Grade).where(
                Grade.evaluation_id == data.evaluation_id,
                Grade.student_id == entry.student_id,
            )
        )).scalar_one_or_none()

        if existing:
            existing.grade = entry.grade if entry.status == "graded" else None
            existing.status = entry.status
            existing.comment = entry.comment
            existing.teacher_id = user.id
            from datetime import datetime
            existing.modified_at = datetime.utcnow()
            existing.modified_by = user.id
            updated += 1
        else:
            grade = Grade(
                school_id=school_id,
                evaluation_id=data.evaluation_id,
                student_id=entry.student_id,
                teacher_id=user.id,
                grade=entry.grade if entry.status == "graded" else None,
                status=entry.status,
                comment=entry.comment,
            )
            db.add(grade)
            created += 1

    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="grade.create", resource="grade", details={"evaluation_id": data.evaluation_id, "created": created, "updated": updated})
    return {"created": created, "updated": updated}


@router.put("/{grade_id}")
async def update_grade(
    grade_id: int,
    data: GradeUpdate,
    user: User = Depends(require_permission("grade.update")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a single grade. Blocked if evaluation is published."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    grade = (await db.execute(
        select(Grade).where(Grade.id == grade_id, Grade.school_id == school_id)
    )).scalar_one_or_none()
    if not grade:
        raise HTTPException(status_code=404, detail="Note introuvable")

    # Check if evaluation is published
    evaluation = (await db.execute(
        select(Evaluation).where(Evaluation.id == grade.evaluation_id)
    )).scalar_one_or_none()
    if evaluation and evaluation.is_published:
        raise HTTPException(status_code=400, detail="Cette évaluation est publiée — notes gelées")

    grade.grade = data.grade
    grade.comment = data.comment
    grade.teacher_id = user.id
    grade.modified_at = datetime.utcnow()
    grade.modified_by = user.id
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="grade.update", resource="grade", resource_id=grade.id)
    return {"id": grade.id, "grade": grade.grade}


@router.delete("/{grade_id}", status_code=204)
async def delete_grade(
    grade_id: int,
    user: User = Depends(require_permission("grade.delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    grade = (await db.execute(
        select(Grade).where(Grade.id == grade_id, Grade.school_id == school_id)
    )).scalar_one_or_none()
    if not grade:
        raise HTTPException(status_code=404, detail="Note introuvable")
    grade_id_val = grade.id
    await db.delete(grade)
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="grade.delete", resource="grade", resource_id=grade_id_val)


# --- Averages & Rankings (calculé à la volée) ---


@router.get("/averages/{class_id}")
async def get_class_averages(
    class_id: int,
    period: str = Query(..., pattern="^(T[123]|S[12])$"),
    academic_year: str = Query("2025-2026"),
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Calculate averages and rankings for a class — à la volée."""
    school_id = get_school_id(user)

    # Get enrolled students
    student_ids = [
        e.student_id for e in (await db.execute(
            select(Enrollment).where(
                Enrollment.class_id == class_id,
                Enrollment.status == "active",
            )
        )).scalars().all()
    ]

    if not student_ids:
        return {"averages": [], "class_average": 0, "best_average": 0, "worst_average": 0}

    # Get all evaluations for this class/period
    evaluations = (await db.execute(
        select(Evaluation).where(
            Evaluation.school_id == school_id,
            Evaluation.class_id == class_id,
            Evaluation.period == period,
            Evaluation.academic_year == academic_year,
        )
    )).scalars().all()
    eval_ids = [e.id for e in evaluations]

    if not eval_ids:
        return {"averages": [], "class_average": 0, "best_average": 0, "worst_average": 0}

    # Get all grades for these evaluations
    grades = (await db.execute(
        select(Grade).where(
            Grade.school_id == school_id,
            Grade.evaluation_id.in_(eval_ids),
            Grade.student_id.in_(student_ids),
        )
    )).scalars().all()

    # Build eval lookup: evaluation_id -> (coefficient, max_grade)
    eval_coeff = {e.id: (e.coefficient, e.max_grade) for e in evaluations}

    # Calculate weighted average per student
    student_grades: dict[int, list[tuple[float, int]]] = {sid: [] for sid in student_ids}
    for g in grades:
        coeff, _ = eval_coeff.get(g.evaluation_id, (1, 20))
        student_grades[g.student_id].append((g.grade, coeff))

    averages = []
    for sid, sg in student_grades.items():
        if sg:
            total_pts = sum(grade * coef for grade, coef in sg)
            total_cfs = sum(coef for _, coef in sg)
            avg = round(total_pts / total_cfs, 2) if total_cfs > 0 else 0
        else:
            avg = 0

        student = (await db.execute(select(Student).where(Student.id == sid))).scalar_one_or_none()
        name = f"{student.first_name} {student.last_name}" if student else f"#{sid}"

        averages.append({
            "student_id": sid,
            "student_name": name,
            "average": avg,
            "total_grades": len(sg),
        })

    averages.sort(key=lambda x: x["average"], reverse=True)
    for i, a in enumerate(averages):
        a["rank"] = i + 1

    avgs = [a["average"] for a in averages if a["average"] > 0]
    return {
        "averages": averages,
        "class_average": round(sum(avgs) / len(avgs), 2) if avgs else 0,
        "best_average": max(avgs) if avgs else 0,
        "worst_average": min(avgs) if avgs else 0,
    }


# ═══════════════════════════════════════════════════════════════════
# SAISIE RAPIDE DES NOTES — Quick Entry Grid
# ═══════════════════════════════════════════════════════════════════


@router.get("/entry/{evaluation_id}")
async def get_grade_entry(
    evaluation_id: int,
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return evaluation info + all enrolled students + existing grades.

    One single call to power the entire grade entry grid.
    """
    school_id = get_school_id(user)

    # Verify evaluation belongs to school
    evaluation = (await db.execute(
        select(Evaluation).where(
            Evaluation.id == evaluation_id,
            Evaluation.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")

    # Get enrolled students for this class
    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.class_id == evaluation.class_id,
            Enrollment.school_id == school_id,
            Enrollment.status == "active",
        )
    )).scalars().all()
    student_ids = [e.student_id for e in enrollments]

    # Get existing grades for this evaluation
    existing_grades = (await db.execute(
        select(Grade).where(
            Grade.evaluation_id == evaluation_id,
            Grade.school_id == school_id,
        )
    )).scalars().all()
    grade_map = {g.student_id: g for g in existing_grades}

    # Get student info
    students = []
    for sid in student_ids:
        student = (await db.execute(select(Student).where(Student.id == sid))).scalar_one_or_none()
        if not student:
            continue
        g = grade_map.get(sid)
        students.append({
            "id": student.id,
            "name": f"{student.first_name} {student.last_name}",
            "first_name": student.first_name,
            "last_name": student.last_name,
            "matricule": student.matricule or "",
            "gender": student.gender,
            "grade": g.grade if g else None,
            "grade_id": g.id if g else None,
            "status": g.status if g else "empty",
            "comment": g.comment if g else None,
        })

    # Stats
    entered = sum(1 for s in students if s["status"] == "graded" and s["grade"] is not None)
    absent_count = sum(1 for s in students if s["status"] == "absent")
    excused_count = sum(1 for s in students if s["status"] == "excused")
    missing = sum(1 for s in students if s["status"] == "empty")

    # Subject info
    subject = (await db.execute(select(Subject).where(Subject.id == evaluation.subject_id))).scalar_one_or_none()

    return {
        "evaluation": {
            "id": evaluation.id,
            "name": evaluation.name,
            "assessment_type": evaluation.assessment_type,
            "period": evaluation.period,
            "academic_year": evaluation.academic_year,
            "max_grade": evaluation.max_grade,
            "coefficient": evaluation.coefficient,
            "date": str(evaluation.date),
            "is_published": evaluation.is_published,
            "is_finalized": evaluation.is_finalized,
            "class_id": evaluation.class_id,
            "subject_id": evaluation.subject_id,
            "subject_name": subject.name if subject else None,
        },
        "students": students,
        "stats": {
            "total": len(students),
            "entered": entered,
            "missing": missing,
            "absent": absent_count,
            "excused": excused_count,
        },
    }


# ── Schema pour saisie individuelle ─────────────────────────────


class GradePatchEntry(BaseModel):
    student_id: int
    grade: float | None = Field(default=None, ge=0, le=20)
    status: str = Field(default="graded", pattern="^(graded|absent|excused|empty)$")
    comment: str | None = Field(default=None, max_length=200)


@router.patch("/entry")
async def patch_grade_entry(
    evaluation_id: int,
    data: GradePatchEntry,
    user: User = Depends(require_permission("grade.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Save a single grade entry (auto-save from the grid)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Verify evaluation
    evaluation = (await db.execute(
        select(Evaluation).where(
            Evaluation.id == evaluation_id,
            Evaluation.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    if evaluation.is_finalized:
        raise HTTPException(status_code=400, detail="Cette évaluation est finalisée — modification impossible")

    # Verify student belongs to school
    student_ok = (await db.execute(
        select(Student.id).where(Student.id == data.student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if student_ok is None:
        raise HTTPException(status_code=404, detail="Élève introuvable")

    # Validate grade value if status is graded
    if data.status == "graded" and data.grade is not None:
        if data.grade < 0 or data.grade > evaluation.max_grade:
            raise HTTPException(
                status_code=400,
                detail=f"La note doit être comprise entre 0 et {evaluation.max_grade}"
            )

    # Upsert
    existing = (await db.execute(
        select(Grade).where(
            Grade.evaluation_id == evaluation_id,
            Grade.student_id == data.student_id,
            Grade.school_id == school_id,
        )
    )).scalar_one_or_none()

    if existing:
        existing.grade = data.grade if data.status == "graded" else None
        existing.status = data.status
        existing.comment = data.comment
        existing.teacher_id = user.id
        existing.modified_at = datetime.utcnow()
        existing.modified_by = user.id
        grade_id = existing.id
    else:
        grade = Grade(
            school_id=school_id,
            evaluation_id=evaluation_id,
            student_id=data.student_id,
            teacher_id=user.id,
            grade=data.grade if data.status == "graded" else None,
            status=data.status,
            comment=data.comment,
        )
        db.add(grade)
        await db.flush()
        grade_id = grade.id

    await db.flush()
    return {"grade_id": grade_id, "status": data.status, "grade": data.grade}


# ── Import Excel ────────────────────────────────────────────────


class GradeImportPreview(BaseModel):
    raw_text: str = Field(..., min_length=1, max_length=10000)


@router.post("/import/preview")
async def import_preview(
    evaluation_id: int,
    data: GradeImportPreview,
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Parse raw text (from Excel paste) and return preview."""
    school_id = get_school_id(user)

    evaluation = (await db.execute(
        select(Evaluation).where(
            Evaluation.id == evaluation_id,
            Evaluation.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")

    lines = [l.strip() for l in data.raw_text.replace("\r", "").split("\n") if l.strip()]
    max_grade = evaluation.max_grade
    entries = []
    valid = 0
    invalid = 0
    absents = 0
    excused = 0

    for line in lines:
        upper = line.upper().replace(" ", "")
        if upper in ("ABS", "ABSENT", "A"):
            entries.append({"raw": line, "status": "absent", "grade": None, "valid": True})
            absents += 1
        elif upper in ("DISP", "DISPENSE", "D"):
            entries.append({"raw": line, "status": "excused", "grade": None, "valid": True})
            excused += 1
        else:
            # Try to parse as number (handle comma decimal)
            cleaned = line.replace(",", ".")
            try:
                val = float(cleaned)
                if 0 <= val <= max_grade:
                    entries.append({"raw": line, "status": "graded", "grade": round(val, 2), "valid": True})
                    valid += 1
                else:
                    entries.append({"raw": line, "status": "graded", "grade": None, "valid": False, "error": f"Hors barème (0-{max_grade})"})
                    invalid += 1
            except ValueError:
                entries.append({"raw": line, "status": "graded", "grade": None, "valid": False, "error": "Valeur invalide"})
                invalid += 1

    return {
        "total": len(entries),
        "valid": valid,
        "absent": absents,
        "excused": excused,
        "invalid": invalid,
        "entries": entries,
    }


@router.post("/import/confirm")
async def import_confirm(
    evaluation_id: int,
    entries: list[GradePatchEntry],
    user: User = Depends(require_permission("grade.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply grades from Excel import (after preview confirmation)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    evaluation = (await db.execute(
        select(Evaluation).where(
            Evaluation.id == evaluation_id,
            Evaluation.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    if evaluation.is_finalized:
        raise HTTPException(status_code=400, detail="Évaluation finalisée")

    # Get enrolled students in order
    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.class_id == evaluation.class_id,
            Enrollment.school_id == school_id,
            Enrollment.status == "active",
        ).order_by(Enrollment.id)
    )).scalars().all()
    student_ids = [e.student_id for e in enrollments]

    created = 0
    updated = 0
    for i, entry in enumerate(entries):
        if i >= len(student_ids):
            break
        sid = student_ids[i]

        existing = (await db.execute(
            select(Grade).where(
                Grade.evaluation_id == evaluation_id,
                Grade.student_id == sid,
                Grade.school_id == school_id,
            )
        )).scalar_one_or_none()

        if existing:
            existing.grade = entry.grade if entry.status == "graded" else None
            existing.status = entry.status
            existing.comment = entry.comment
            existing.teacher_id = user.id
            existing.modified_at = datetime.utcnow()
            existing.modified_by = user.id
            updated += 1
        else:
            grade = Grade(
                school_id=school_id,
                evaluation_id=evaluation_id,
                student_id=sid,
                teacher_id=user.id,
                grade=entry.grade if entry.status == "graded" else None,
                status=entry.status,
                comment=entry.comment,
            )
            db.add(grade)
            created += 1

    await db.flush()
    return {"created": created, "updated": updated, "total": len(entries)}


# ── Finalisation / Réouverture ──────────────────────────────────


@router.post("/evaluations/{evaluation_id}/finalize")
async def finalize_evaluation(
    evaluation_id: int,
    user: User = Depends(require_permission("evaluation.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Finalize an evaluation — prevents further grade modifications."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    evaluation = (await db.execute(
        select(Evaluation).where(
            Evaluation.id == evaluation_id,
            Evaluation.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    if evaluation.is_finalized:
        raise HTTPException(status_code=400, detail="Déjà finalisée")

    evaluation.is_finalized = True
    evaluation.finalized_at = datetime.utcnow()
    evaluation.finalized_by = user.id
    await db.flush()
    return {"id": evaluation.id, "is_finalized": True}


@router.post("/evaluations/{evaluation_id}/reopen")
async def reopen_evaluation(
    evaluation_id: int,
    user: User = Depends(require_permission("evaluation.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reopen a finalized evaluation — allows modifications again."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    evaluation = (await db.execute(
        select(Evaluation).where(
            Evaluation.id == evaluation_id,
            Evaluation.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    if not evaluation.is_finalized:
        raise HTTPException(status_code=400, detail="Pas finalisée")

    evaluation.is_finalized = False
    evaluation.finalized_at = None
    evaluation.finalized_by = None
    await db.flush()
    return {"id": evaluation.id, "is_finalized": False}
