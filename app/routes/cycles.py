"""Yiriba SaaS — Routes Configuration Académique.

Cycles, Niveaux, ClassSubjects, configuration des matières par classe.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.middleware.rbac import require_permission, get_school_id
from app.models.cycle import Cycle, Level
from app.models.class_ import Class, Subject, ClassSubject
from app.models.academic_year import AcademicYear
from app.models.user import User

router = APIRouter(prefix="/api", tags=["configuration-academique"])




# ═══════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════

class CycleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    code: str = Field(..., min_length=1, max_length=20)
    display_order: int = 0


class CycleUpdate(BaseModel):
    name: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


class LevelCreate(BaseModel):
    cycle_id: int
    name: str = Field(..., min_length=1, max_length=50)
    code: str = Field(..., min_length=1, max_length=20)
    display_order: int = 0


class LevelUpdate(BaseModel):
    name: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


class ClassSubjectCreate(BaseModel):
    class_id: int
    subject_id: int
    coefficient: int = Field(1, ge=1, le=10)
    max_score: float = Field(20.0, gt=0)
    hours_per_week: float | None = None
    is_required: bool = True


class ClassSubjectUpdate(BaseModel):
    coefficient: int | None = Field(None, ge=1, le=10)
    max_score: float | None = Field(None, gt=0)
    hours_per_week: float | None = None
    is_required: bool | None = None
    is_active: bool | None = None


class ClassSubjectCopy(BaseModel):
    source_class_id: int
    target_class_ids: list[int]


# ═══════════════════════════════════════════════════════════════════
# CYCLES
# ═══════════════════════════════════════════════════════════════════

@router.get("/cycles")
async def list_cycles(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)
    result = await db.execute(
        select(Cycle)
        .where(Cycle.school_id == school_id)
        .options(selectinload(Cycle.levels))
        .order_by(Cycle.display_order)
    )
    cycles = result.scalars().all()
    return {
        "cycles": [
            {
                "id": c.id,
                "name": c.name,
                "code": c.code,
                "display_order": c.display_order,
                "is_active": c.is_active,
                "levels": [
                    {
                        "id": l.id,
                        "name": l.name,
                        "code": l.code,
                        "display_order": l.display_order,
                        "is_active": l.is_active,
                    }
                    for l in c.levels
                ],
            }
            for c in cycles
        ]
    }


@router.post("/cycles", status_code=201)
async def create_cycle(
    body: CycleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)

    # Vérifier doublon
    existing = await db.execute(
        select(Cycle).where(Cycle.school_id == school_id, Cycle.code == body.code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Un cycle avec ce code existe déjà")

    cycle = Cycle(school_id=school_id, **body.model_dump())
    db.add(cycle)
    await db.commit()
    await db.refresh(cycle)
    return {"id": cycle.id, "name": cycle.name, "code": cycle.code}


@router.patch("/cycles/{cycle_id}")
async def update_cycle(
    cycle_id: int,
    body: CycleUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)
    result = await db.execute(
        select(Cycle).where(Cycle.id == cycle_id, Cycle.school_id == school_id)
    )
    cycle = result.scalar_one_or_none()
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle introuvable")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cycle, field, value)
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# LEVELS
# ═══════════════════════════════════════════════════════════════════

@router.get("/levels")
async def list_levels(
    cycle_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)
    query = select(Level).where(Level.school_id == school_id)
    if cycle_id:
        query = query.where(Level.cycle_id == cycle_id)
    result = await db.execute(query.order_by(Level.display_order))
    levels = result.scalars().all()
    return {
        "levels": [
            {
                "id": l.id,
                "cycle_id": l.cycle_id,
                "name": l.name,
                "code": l.code,
                "display_order": l.display_order,
                "is_active": l.is_active,
            }
            for l in levels
        ]
    }


@router.post("/levels", status_code=201)
async def create_level(
    body: LevelCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)

    # Vérifier que le cycle appartient à la même école
    cycle_result = await db.execute(
        select(Cycle).where(Cycle.id == body.cycle_id, Cycle.school_id == school_id)
    )
    if not cycle_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Cycle introuvable dans cette école")

    # Vérifier doublon
    existing = await db.execute(
        select(Level).where(
            Level.school_id == school_id,
            Level.cycle_id == body.cycle_id,
            Level.code == body.code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Un niveau avec ce code existe déjà dans ce cycle")

    level = Level(school_id=school_id, **body.model_dump())
    db.add(level)
    await db.commit()
    await db.refresh(level)
    return {"id": level.id, "name": level.name, "code": level.code}


@router.patch("/levels/{level_id}")
async def update_level(
    level_id: int,
    body: LevelUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)
    result = await db.execute(
        select(Level).where(Level.id == level_id, Level.school_id == school_id)
    )
    level = result.scalar_one_or_none()
    if not level:
        raise HTTPException(status_code=404, detail="Niveau introuvable")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(level, field, value)
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════
# CLASS-SUBJECTS (Matières par classe)
# ═══════════════════════════════════════════════════════════════════

@router.get("/class-subjects")
async def list_class_subjects(
    class_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)

    # Vérifier que la classe appartient à l'école
    class_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Classe introuvable")

    result = await db.execute(
        select(ClassSubject)
        .where(ClassSubject.school_id == school_id, ClassSubject.class_id == class_id)
        .options(selectinload(ClassSubject.subject))
        .order_by(ClassSubject.id)
    )
    class_subjects = result.scalars().all()

    return {
        "class_subjects": [
            {
                "id": cs.id,
                "subject_id": cs.subject_id,
                "subject_name": cs.subject.name if cs.subject else "?",
                "subject_code": cs.subject.code if cs.subject else None,
                "coefficient": cs.coefficient,
                "max_score": cs.max_score,
                "hours_per_week": cs.hours_per_week,
                "is_required": cs.is_required,
                "is_active": cs.is_active,
            }
            for cs in class_subjects
        ]
    }


@router.post("/class-subjects", status_code=201)
async def create_class_subject(
    body: ClassSubjectCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)

    # Vérifier que la classe et la matière appartiennent à la même école
    class_result = await db.execute(
        select(Class).where(Class.id == body.class_id, Class.school_id == school_id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Classe introuvable dans cette école")

    subject_result = await db.execute(
        select(Subject).where(Subject.id == body.subject_id, Subject.school_id == school_id)
    )
    if not subject_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Matière introuvable dans cette école")

    # Vérifier doublon
    existing = await db.execute(
        select(ClassSubject).where(
            ClassSubject.school_id == school_id,
            ClassSubject.class_id == body.class_id,
            ClassSubject.subject_id == body.subject_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Cette matière est déjà associée à cette classe")

    cs = ClassSubject(school_id=school_id, **body.model_dump())
    db.add(cs)
    await db.commit()
    await db.refresh(cs)
    return {"id": cs.id}


@router.patch("/class-subjects/{cs_id}")
async def update_class_subject(
    cs_id: int,
    body: ClassSubjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)
    result = await db.execute(
        select(ClassSubject).where(ClassSubject.id == cs_id, ClassSubject.school_id == school_id)
    )
    cs = result.scalar_one_or_none()
    if not cs:
        raise HTTPException(status_code=404, detail="Affectation introuvable")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cs, field, value)
    await db.commit()
    return {"ok": True}


@router.delete("/class-subjects/{cs_id}")
async def delete_class_subject(
    cs_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)
    result = await db.execute(
        select(ClassSubject).where(ClassSubject.id == cs_id, ClassSubject.school_id == school_id)
    )
    cs = result.scalar_one_or_none()
    if not cs:
        raise HTTPException(status_code=404, detail="Affectation introuvable")

    await db.delete(cs)
    await db.commit()
    return {"ok": True}


@router.post("/class-subjects/copy")
async def copy_class_subjects(
    body: ClassSubjectCopy,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    """Copier la configuration de matières d'une classe vers d'autres."""
    school_id = get_school_id(user)

    # Récupérer les class_subjects de la source
    source_result = await db.execute(
        select(ClassSubject).where(
            ClassSubject.school_id == school_id,
            ClassSubject.class_id == body.source_class_id,
        )
    )
    source_subjects = source_result.scalars().all()
    if not source_subjects:
        raise HTTPException(status_code=404, detail="Aucune matière configurée pour la classe source")

    # Vérifier que les classes cibles existent
    target_result = await db.execute(
        select(Class).where(
            Class.school_id == school_id,
            Class.id.in_(body.target_class_ids),
        )
    )
    target_classes = target_result.scalars().all()
    if len(target_classes) != len(body.target_class_ids):
        raise HTTPException(status_code=404, detail="Une ou plusieurs classes cibles introuvables")

    copied = 0
    for target_id in body.target_class_ids:
        for src in source_subjects:
            # Vérifier si déjà existant
            existing = await db.execute(
                select(ClassSubject).where(
                    ClassSubject.school_id == school_id,
                    ClassSubject.class_id == target_id,
                    ClassSubject.subject_id == src.subject_id,
                )
            )
            if existing.scalar_one_or_none():
                continue

            new_cs = ClassSubject(
                school_id=school_id,
                class_id=target_id,
                subject_id=src.subject_id,
                coefficient=src.coefficient,
                max_score=src.max_score,
                hours_per_week=src.hours_per_week,
                is_required=src.is_required,
            )
            db.add(new_cs)
            copied += 1

    await db.commit()
    return {"copied": copied, "targets": len(body.target_class_ids)}


# ═══════════════════════════════════════════════════════════════════
# ACADEMIC YEARS — Enrichir les routes existantes
# ═══════════════════════════════════════════════════════════════════

@router.get("/academic-years")
async def list_academic_years(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)
    result = await db.execute(
        select(AcademicYear)
        .where(AcademicYear.school_id == school_id)
        .order_by(AcademicYear.name.desc())
    )
    years = result.scalars().all()
    return {
        "academic_years": [
            {
                "id": ay.id,
                "name": ay.name,
                "start_date": str(ay.start_date),
                "end_date": str(ay.end_date),
                "status": ay.status,
                "is_current": ay.is_current,
                "is_active": ay.is_active,
            }
            for ay in years
        ]
    }


@router.post("/academic-years", status_code=201)
async def create_academic_year(
    name: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)

    # Vérifier doublon
    existing = await db.execute(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id, AcademicYear.name == name
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Cette année scolaire existe déjà")

    from datetime import date as date_type
    ay = AcademicYear(
        school_id=school_id,
        name=name,
        start_date=date_type.fromisoformat(start_date),
        end_date=date_type.fromisoformat(end_date),
        status="planned",
    )
    db.add(ay)
    await db.commit()
    await db.refresh(ay)
    return {"id": ay.id, "name": ay.name}


@router.post("/academic-years/{ay_id}/activate")
async def activate_academic_year(
    ay_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)

    # Désactiver l'année courante
    current_result = await db.execute(
        select(AcademicYear).where(
            AcademicYear.school_id == school_id,
            AcademicYear.is_current == True,  # noqa: E712
        )
    )
    for old in current_result.scalars().all():
        old.is_current = False
        old.status = "closed"

    # Activer la nouvelle année
    result = await db.execute(
        select(AcademicYear).where(
            AcademicYear.id == ay_id, AcademicYear.school_id == school_id
        )
    )
    ay = result.scalar_one_or_none()
    if not ay:
        raise HTTPException(status_code=404, detail="Année scolaire introuvable")

    ay.is_current = True
    ay.status = "active"
    await db.commit()
    return {"ok": True, "active_year": ay.name}


@router.post("/academic-years/{ay_id}/close")
async def close_academic_year(
    ay_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("class.manage")),
):
    school_id = get_school_id(user)
    result = await db.execute(
        select(AcademicYear).where(
            AcademicYear.id == ay_id, AcademicYear.school_id == school_id
        )
    )
    ay = result.scalar_one_or_none()
    if not ay:
        raise HTTPException(status_code=404, detail="Année scolaire introuvable")

    ay.status = "closed"
    ay.is_current = False
    await db.commit()
    return {"ok": True}
