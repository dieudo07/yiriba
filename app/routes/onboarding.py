"""Yiriba SaaS — Routes d'onboarding.

Configuration initiale d'une école après inscription :
- Année scolaire
- Classes initiales
- Matières de base
- Profil école (logo, motto)
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.seeds import seed_school_roles
from app.middleware.rbac import get_school_id, require_permission
from app.models.academic_year import AcademicYear
from app.models.class_ import Class, Subject
from app.models.school import School
from app.models.user import User

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# ── Schemas ───────────────────────────────────────────────────────


class AcademicYearCreate(BaseModel):
    name: str = Field(..., pattern=r"^\d{4}-\d{4}$", max_length=10)  # "2025-2026"
    start_date: str  # ISO date
    end_date: str  # ISO date


class ClassCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    level: str | None = Field(default=None, max_length=50)
    capacity: int = Field(default=50, ge=1, le=200)


class SubjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=20)
    coefficient: int = Field(default=1, ge=1, le=10)
    max_grade: int = Field(default=20, ge=1, le=100)


class BulkClasses(BaseModel):
    classes: list[ClassCreate]


class BulkSubjects(BaseModel):
    subjects: list[SubjectCreate]


class SchoolProfileUpdate(BaseModel):
    logo_url: str | None = None
    motto: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = None
    website: str | None = Field(default=None, max_length=200)

    @field_validator("logo_url")
    @classmethod
    def _sanitize_logo_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        # Uniquement un fichier déjà uploadé sous uploads/logos/ (anti-LFI)
        if not v.startswith("/uploads/logos/") or ".." in v or "\\" in v:
            raise ValueError("URL de logo invalide : utilisez l'upload de logo dédié")
        return v


# ── Étape 1 : Année scolaire ──────────────────────────────────────


@router.post("/academic-year", status_code=201)
async def create_academic_year(
    data: AcademicYearCreate,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Créer ou mettre à jour l'année scolaire active."""
    school_id = get_school_id(user)

    # Vérifier si une année avec ce nom existe déjà
    existing = (await db.execute(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.name == data.name,
        )
    )).scalar_one_or_none()

    if existing:
        # Mettre à jour les dates si nécessaire
        existing.start_date = date.fromisoformat(data.start_date)
        existing.end_date = date.fromisoformat(data.end_date)
        existing.is_current = True
        existing.is_active = True
        await db.flush()
        return {"id": existing.id, "name": existing.name, "message": "Année scolaire mise à jour"}

    # Désactiver les autres années courantes
    current = (await db.execute(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.is_current == True,  # noqa: E712
        )
    )).scalars().all()
    for ay in current:
        ay.is_current = False

    # Créer la nouvelle année
    academic_year = AcademicYear(
        school_id=school_id,
        name=data.name,
        start_date=date.fromisoformat(data.start_date),
        end_date=date.fromisoformat(data.end_date),
        is_current=True,
        is_active=True,
    )
    db.add(academic_year)
    await db.flush()

    return {"id": academic_year.id, "name": academic_year.name, "message": "Année scolaire créée"}


@router.get("/academic-year")
async def get_current_academic_year(
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Récupérer l'année scolaire en cours."""
    school_id = get_school_id(user)
    result = await db.execute(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.is_current == True,  # noqa: E712
        )
    )
    ay = result.scalar_one_or_none()
    if not ay:
        return {"academic_year": None}
    return {
        "academic_year": {
            "id": ay.id, "name": ay.name,
            "start_date": str(ay.start_date), "end_date": str(ay.end_date),
            "is_current": ay.is_current,
        }
    }


# ── Étape 2 : Classes initiales ───────────────────────────────────


@router.post("/classes", status_code=201)
async def create_initial_classes(
    data: BulkClasses,
    user: User = Depends(require_permission("class.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Créer les classes initiales de l'école (batch)."""
    school_id = get_school_id(user)

    # Récupérer l'année courante
    ay = (await db.execute(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.is_current == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    academic_year_name = ay.name if ay else f"{date.today().year}-{date.today().year + 1}"

    created = 0
    for c in data.classes:
        # Vérifier doublon
        existing = (await db.execute(
            select(Class).where(
                Class.school_id == school_id,
                Class.name == c.name,
                Class.academic_year == academic_year_name,
            )
        )).scalar_one_or_none()
        if existing:
            continue

        cls = Class(
            school_id=school_id,
            name=c.name.strip(),
            level=c.level,
            capacity=c.capacity,
            academic_year=academic_year_name,
        )
        db.add(cls)
        created += 1

    await db.flush()
    return {"created": created, "message": f"{created} classe(s) créée(s)"}


# ── Étape 3 : Matières de base ────────────────────────────────────


@router.post("/subjects", status_code=201)
async def create_initial_subjects(
    data: BulkSubjects,
    user: User = Depends(require_permission("class.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Créer les matières initiales de l'école (batch)."""
    school_id = get_school_id(user)

    created = 0
    for s in data.subjects:
        existing = (await db.execute(
            select(Subject).where(
                Subject.school_id == school_id,
                Subject.name == s.name,
            )
        )).scalar_one_or_none()
        if existing:
            continue

        subject = Subject(
            school_id=school_id,
            name=s.name.strip(),
            code=s.code,
            coefficient=s.coefficient,
            max_grade=s.max_grade,
        )
        db.add(subject)
        created += 1

    await db.flush()
    return {"created": created, "message": f"{created} matière(s) créée(s)"}


# ── Étape 4 : Profil école ────────────────────────────────────────


@router.put("/school-profile")
async def update_school_profile(
    data: SchoolProfileUpdate,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mettre à jour le profil de l'école (logo, motto, etc.)."""
    school_id = get_school_id(user)
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="École introuvable")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(school, field, value)

    await db.flush()
    return {"message": "Profil mis à jour", "school": {"id": school.id, "name": school.name}}


# ── Statut onboarding ─────────────────────────────────────────────


@router.get("/status")
async def onboarding_status(
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Vérifier l'état d'avancement de l'onboarding."""
    school_id = get_school_id(user)

    # Classes
    class_count = (await db.execute(
        select(Class).where(Class.school_id == school_id)
    )).scalars().all()

    # Matières
    subject_count = (await db.execute(
        select(Subject).where(Subject.school_id == school_id)
    )).scalars().all()

    # Année scolaire
    ay = (await db.execute(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.is_current == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    # Profil
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()

    steps = {
        "academic_year": ay is not None,
        "classes": len(class_count) > 0,
        "subjects": len(subject_count) > 0,
        "profile": school is not None and (school.logo_url is not None or school.motto is not None),
    }

    completed = sum(steps.values())
    total = len(steps)

    return {
        "steps": steps,
        "completed": completed,
        "total": total,
        "is_complete": completed == total,
        "classes_count": len(class_count),
        "subjects_count": len(subject_count),
    }
