"""Yiriba SaaS — Class and Subject routes: CRUD, enrollment management."""

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.services.subscription_service import require_write_access
from app.models.class_ import Class, ClassSubject, Enrollment, Subject
from app.models.student import Student
from app.models.user import User

router = APIRouter(prefix="/api", tags=["classes", "subjects"])


# ── Schemas ───────────────────────────────────────────────────────


class ClassCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    level: str | None = Field(default=None, max_length=50)
    capacity: int = Field(default=50, ge=1, le=200)
    academic_year: str = Field(default="2025-2026", max_length=10)
    period_type: str = Field(default="trimestre", pattern="^(trimestre|semestre)$")
    enrollment_fee: float | None = Field(default=None, ge=0)  # Montant inscription
    annual_tuition: float | None = Field(default=None, ge=0)  # Scolarité annuelle


class ClassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    level: str | None = Field(default=None, max_length=50)
    capacity: int | None = Field(default=None, ge=1, le=200)
    period_type: str | None = Field(default=None, pattern="^(trimestre|semestre)$")
    enrollment_fee: float | None = None
    annual_tuition: float | None = None


class SubjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=20)
    coefficient: int = Field(default=1, ge=1, le=10)
    max_grade: int = Field(default=20, ge=1, le=100)
    description: str | None = None


class EnrollmentCreate(BaseModel):
    student_id: int
    class_id: int
    is_repeater: bool = False


# ── Classes ───────────────────────────────────────────────────────


@router.get("/classes")
async def list_classes(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(Class).where(Class.school_id == school_id, Class.is_active == True)  # noqa: E712

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar()

    classes = (await db.execute(
        query.order_by(Class.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    return {
        "classes": [
            {
                "id": c.id, "name": c.name, "level": c.level,
                "capacity": c.capacity, "period_type": c.period_type,
                "academic_year": c.academic_year,
                "enrollment_fee": str(c.enrollment_fee) if c.enrollment_fee else None,
                "annual_tuition": str(c.annual_tuition) if c.annual_tuition else None,
            }
            for c in classes
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


@router.get("/classes/{class_id}")
async def get_class(
    class_id: int,
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single class by ID."""
    school_id = get_school_id(user)
    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")
    enrolled = (await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.class_id == class_id,
            Enrollment.status == 'active',
        )
    )).scalar() or 0
    return {
        "id": cls.id, "name": cls.name, "level": cls.level,
        "capacity": cls.capacity, "period_type": cls.period_type,
        "academic_year": cls.academic_year,
        "enrollment_fee": str(cls.enrollment_fee) if cls.enrollment_fee else None,
        "annual_tuition": str(cls.annual_tuition) if cls.annual_tuition else None,
        "level_id": cls.level_id, "academic_year_id": cls.academic_year_id,
        "enrolled_count": enrolled,
    }


@router.post("/classes", status_code=201)
async def create_class(
    data: ClassCreate,
    user: User = Depends(require_permission("class.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    cls = Class(
        school_id=school_id,
        name=data.name.strip(),
        level=data.level,
        capacity=data.capacity,
        academic_year=data.academic_year,
        period_type=data.period_type,
        enrollment_fee=data.enrollment_fee,
        annual_tuition=data.annual_tuition,
    )
    db.add(cls)
    await db.flush()
    await db.refresh(cls)
    return {
        "id": cls.id, "name": cls.name, "level": cls.level, "capacity": cls.capacity,
        "period_type": cls.period_type,
        "enrollment_fee": str(cls.enrollment_fee) if cls.enrollment_fee else None,
        "annual_tuition": str(cls.annual_tuition) if cls.annual_tuition else None,
    }


@router.put("/classes/{class_id}")
async def update_class(
    class_id: int,
    data: ClassUpdate,
    user: User = Depends(require_permission("class.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    result = await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )
    cls = result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    update_data = data.model_dump(exclude_unset=True)

    # ── period_type immutability ──────────────────────────────────
    if "period_type" in update_data and update_data["period_type"] != cls.period_type:
        # Check if this class has any evaluations (grades or assessments)
        from app.models.grade import Evaluation
        eval_count = (
            await db.execute(
                select(func.count()).select_from(Evaluation).where(
                    Evaluation.class_id == class_id,
                    Evaluation.school_id == school_id,
                )
            )
        ).scalar() or 0
        if eval_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de modifier la periode : cette classe possede deja {eval_count} evaluation(s). "
                       "Le type de periode (trimestre/semestre) est definitif des qu'une evaluation existe.",
            )

    for field, value in update_data.items():
        setattr(cls, field, value)
    await db.flush()
    await db.refresh(cls)
    return {"id": cls.id, "name": cls.name, "level": cls.level, "capacity": cls.capacity, "period_type": cls.period_type}


@router.delete("/classes/{class_id}", status_code=204)
async def delete_class(
    class_id: int,
    user: User = Depends(require_permission("class.delete")),

    db: AsyncSession = Depends(get_db),
) -> None:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    result = await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )
    cls = result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")
    cls.is_active = False
    await db.flush()


# ── Subjects ──────────────────────────────────────────────────────


@router.get("/subjects")
async def list_subjects(
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    result = await db.execute(
        select(Subject).where(Subject.school_id == school_id, Subject.is_active == True)  # noqa: E712
    )
    subjects = result.scalars().all()
    return {
        "subjects": [
            {"id": s.id, "name": s.name, "code": s.code, "coefficient": s.coefficient, "max_grade": s.max_grade}
            for s in subjects
        ]
    }


@router.post("/subjects", status_code=201)
async def create_subject(
    data: SubjectCreate,
    user: User = Depends(require_permission("class.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    subject = Subject(
        school_id=school_id,
        name=data.name.strip(),
        code=data.code,
        coefficient=data.coefficient,
        max_grade=data.max_grade,
        description=data.description,
    )
    db.add(subject)
    await db.flush()
    await db.refresh(subject)
    return {"id": subject.id, "name": subject.name, "coefficient": subject.coefficient}


@router.put("/subjects/{subject_id}")
async def update_subject(
    subject_id: int,
    data: SubjectCreate,
    user: User = Depends(require_permission("class.update")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    result = await db.execute(
        select(Subject).where(Subject.id == subject_id, Subject.school_id == school_id)
    )
    subject = result.scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Matière introuvable")

    subject.name = data.name.strip()
    subject.code = data.code
    subject.coefficient = data.coefficient
    subject.max_grade = data.max_grade
    subject.description = data.description
    await db.flush()
    await db.refresh(subject)
    return {"id": subject.id, "name": subject.name, "coefficient": subject.coefficient}


@router.delete("/subjects/{subject_id}", status_code=204)
async def delete_subject(
    subject_id: int,
    user: User = Depends(require_permission("class.delete")),

    db: AsyncSession = Depends(get_db),
) -> None:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    result = await db.execute(
        select(Subject).where(Subject.id == subject_id, Subject.school_id == school_id)
    )
    subject = result.scalar_one_or_none()
    if not subject:
        raise HTTPException(status_code=404, detail="Matière introuvable")
    subject.is_active = False
    await db.flush()


# ── Enrollments ───────────────────────────────────────────────────


@router.get("/enrollments")
async def list_enrollments(
    class_id: int | None = None,
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(Enrollment).where(
        Enrollment.school_id == school_id,
        Enrollment.status == "active",
    )
    if class_id:
        query = query.where(Enrollment.class_id == class_id)

    result = await db.execute(query)
    enrollments = result.scalars().all()
    return {"enrollments": [{"id": e.id, "student_id": e.student_id, "class_id": e.class_id} for e in enrollments]}


@router.post("/enrollments", status_code=201)
async def create_enrollment(
    data: EnrollmentCreate,
    user: User = Depends(require_permission("student.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Check class capacity
    class_result = await db.execute(
        select(Class).where(Class.id == data.class_id, Class.school_id == school_id)
    )
    cls = class_result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    # Count current enrollments
    count_result = await db.execute(
        select(func.count()).select_from(Enrollment).where(
            Enrollment.class_id == data.class_id,
            Enrollment.status == "active",
        )
    )
    current_count = count_result.scalar()

    if current_count >= cls.capacity:
        raise HTTPException(
            status_code=409,
            detail=f"Classe complète ({current_count}/{cls.capacity}). Souhaitez-vous inscrire quand même ?",
        )

    # Check student exists and belongs to school
    student_result = await db.execute(
        select(Student).where(Student.id == data.student_id, Student.school_id == school_id)
    )
    student = student_result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Élève introuvable")

    enrollment = Enrollment(
        school_id=school_id,
        student_id=data.student_id,
        class_id=data.class_id,
        is_repeater=data.is_repeater,
    )
    db.add(enrollment)
    await db.flush()
    return {"id": enrollment.id, "student_id": enrollment.student_id, "class_id": enrollment.class_id}
