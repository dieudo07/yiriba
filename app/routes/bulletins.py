"""Yiriba SaaS — Bulletin routes: PDF generation, bulletin listing, snapshot management."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.services.subscription_service import require_write_access
from app.models.bulletin import Bulletin
from app.models.class_ import Class, Enrollment, Subject
from app.models.grade import Evaluation, Grade
from app.models.student import Student
from app.models.user import User
from app.services.pdf_service import generate_bulletin_pdf, generate_bulletins_for_class

router = APIRouter(prefix="/api/bulletins", tags=["bulletins"])


@router.get("")
async def list_bulletins(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    class_id: int | None = None,
    period: str | None = None,
    status: str | None = None,
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List bulletins for the school."""
    import math
    school_id = get_school_id(user)
    query = select(Bulletin).where(Bulletin.school_id == school_id)
    if class_id:
        query = query.where(Bulletin.class_id == class_id)
    if period:
        query = query.where(Bulletin.period == period)
    if status:
        query = query.where(Bulletin.status == status)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    bulletins = (await db.execute(
        query.order_by(Bulletin.generated_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()
    result = []
    for b in bulletins:
        student = (await db.execute(select(Student).where(Student.id == b.student_id))).scalar_one_or_none()
        cls = (await db.execute(select(Class).where(Class.id == b.class_id))).scalar_one_or_none()
        result.append({
            "id": b.id, "student_id": b.student_id,
            "student_name": f"{student.first_name} {student.last_name}" if student else "?",
            "class_id": b.class_id, "class_name": cls.name if cls else "?",
            "period": b.period, "academic_year": b.academic_year,
            "status": b.status, "overall_average": b.overall_average,
            "rank": b.rank, "total_students": b.total_students,
            "generated_at": str(b.generated_at) if b.generated_at else None,
        })
    return {"bulletins": result, "total": total, "page": page,
            "per_page": per_page, "total_pages": math.ceil(total / per_page) if total else 1}


@router.get("/generate/{student_id}/{class_id}")
async def get_bulletin_pdf(
    student_id: int,
    class_id: int,
    period: str = Query(..., pattern="^(T[123]|S[12])$"),
    academic_year: str = Query("2025-2026"),
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate and return a bulletin PDF for a student."""
    school_id = get_school_id(user)

    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    # L'élève doit appartenir à la même école (anti-IDOR) : boycotter tout
    # student_id cross-école même si la classe elle-même est valide.
    student = (await db.execute(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Élève introuvable")

    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.class_id == class_id,
            Enrollment.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not enrollment:
        raise HTTPException(
            status_code=404, detail="L'élève n'est pas inscrit dans cette classe"
        )

    try:
        pdf_bytes = await generate_bulletin_pdf(
            db, student_id, class_id, period, academic_year
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    filename = f"bulletin_{student_id}_{class_id}_{period}_{academic_year}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@router.get("/class/{class_id}")
async def list_class_bulletins(
    class_id: int,
    period: str = Query(..., pattern="^(T[123]|S[12])$"),
    academic_year: str = Query("2025-2026"),
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all bulletins available for a class in a given period."""
    school_id = get_school_id(user)

    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
    )).scalars().all()

    # Get evaluations for this class/period
    evaluations = (await db.execute(
        select(Evaluation).where(
            Evaluation.class_id == class_id,
            Evaluation.period == period,
            Evaluation.academic_year == academic_year,
            Evaluation.school_id == school_id,
        )
    )).scalars().all()
    eval_ids = [e.id for e in evaluations]
    eval_lookup = {e.id: e for e in evaluations}

    bulletins = []
    for e in enrollments:
        student = (await db.execute(
            select(Student).where(Student.id == e.student_id)
        )).scalar_one_or_none()
        if not student:
            continue

        grades = (await db.execute(
            select(Grade).where(
                Grade.student_id == e.student_id,
                Grade.evaluation_id.in_(eval_ids),
            )
        )).scalars().all() if eval_ids else []

        # Calculate average using Evaluation coefficients
        total_pts = 0
        total_cfs = 0
        for g in grades:
            ev = eval_lookup.get(g.evaluation_id)
            if ev:
                total_pts += g.grade * ev.coefficient
                total_cfs += ev.coefficient
        avg = round(total_pts / total_cfs, 2) if total_cfs > 0 else 0

        bulletins.append({
            "student_id": student.id,
            "student_name": f"{student.first_name} {student.last_name}",
            "matricule": student.matricule,
            "average": avg,
            "grade_count": len(grades),
        })

    bulletins.sort(key=lambda x: x["average"], reverse=True)
    for i, b in enumerate(bulletins):
        b["rank"] = i + 1

    return {
        "class": {"id": cls.id, "name": cls.name},
        "period": period,
        "academic_year": academic_year,
        "effectif": len(bulletins),
        "bulletins": bulletins,
    }


@router.post("/generate/{class_id}/{period}")
async def generate_bulletins_snapshot(
    class_id: int,
    period: str,
    academic_year: str = Query("2025-2026"),
    user: User = Depends(require_permission("bulletin.generate")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate and store bulletin snapshots for all students in a class.

    Creates Bulletin records with data_json (frozen snapshot).
    """
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
    )).scalars().all()

    # Get evaluations for this class/period
    evaluations = (await db.execute(
        select(Evaluation).where(
            Evaluation.class_id == class_id,
            Evaluation.period == period,
            Evaluation.academic_year == academic_year,
            Evaluation.school_id == school_id,
        )
    )).scalars().all()
    eval_ids = [e.id for e in evaluations]
    eval_lookup = {e.id: e for e in evaluations}

    created = 0
    updated = 0

    for enrollment in enrollments:
        student = (await db.execute(
            select(Student).where(Student.id == enrollment.student_id)
        )).scalar_one_or_none()
        if not student:
            continue

        grades = (await db.execute(
            select(Grade).where(
                Grade.student_id == enrollment.student_id,
                Grade.evaluation_id.in_(eval_ids),
            )
        )).scalars().all() if eval_ids else []

        # Build subject data for snapshot
        subjects_data = []
        total_pts = 0
        total_cfs = 0
        for e in evaluations:
            subj = (await db.execute(
                select(Subject).where(Subject.id == e.subject_id)
            )).scalar_one_or_none()

            # Find grade for this evaluation
            grade_val = None
            for g in grades:
                if g.evaluation_id == e.id:
                    grade_val = g.grade
                    break

            avg = grade_val if grade_val is not None else None
            if avg is not None:
                total_pts += avg * e.coefficient
                total_cfs += e.coefficient

            subjects_data.append({
                "name": subj.name if subj else "?",
                "coeff": e.coefficient,
                "grades": {e.assessment_type: grade_val},
                "average": avg,
            })

        overall_avg = round(total_pts / total_cfs, 2) if total_cfs > 0 else 0

        # Calculate rank (need all students' averages)
        all_student_avgs = []
        for enr in enrollments:
            sg = (await db.execute(
                select(Grade).where(
                    Grade.student_id == enr.student_id,
                    Grade.evaluation_id.in_(eval_ids),
                )
            )).scalars().all() if eval_ids else []

            st_pts = sum(g.grade * eval_lookup[g.evaluation_id].coefficient
                        for g in sg if g.evaluation_id in eval_lookup)
            st_cfs = sum(eval_lookup[g.evaluation_id].coefficient
                        for g in sg if g.evaluation_id in eval_lookup)
            st_avg = round(st_pts / st_cfs, 2) if st_cfs > 0 else 0
            all_student_avgs.append({"id": enr.student_id, "avg": st_avg})

        all_student_avgs.sort(key=lambda x: x["avg"], reverse=True)
        rank = next((i + 1 for i, sa in enumerate(all_student_avgs) if sa["id"] == enrollment.student_id), len(all_student_avgs))

        # Decision (only on last period)
        is_trimestre = period.startswith("T")
        periods_list = ["T1", "T2", "T3"] if is_trimestre else ["S1", "S2"]
        is_last_period = period == periods_list[-1]
        decision = None
        if is_last_period:
            decision = "Redouble" if overall_avg < 10 else "Passe"

        data_json = json.dumps({
            "subjects": subjects_data,
            "overall_average": overall_avg,
            "rank": rank,
            "total_students": len(all_student_avgs),
            "decision": decision,
        })

        # Upsert bulletin
        existing = (await db.execute(
            select(Bulletin).where(
                Bulletin.student_id == enrollment.student_id,
                Bulletin.period == period,
                Bulletin.academic_year == academic_year,
            )
        )).scalar_one_or_none()

        if existing:
            existing.data_json = data_json
            existing.overall_average = overall_avg
            existing.rank = rank
            existing.total_students = len(all_student_avgs)
            existing.decision = decision
            existing.generated_by = user.id
            from datetime import datetime
            existing.generated_at = datetime.utcnow()
            updated += 1
        else:
            from datetime import datetime
            bulletin = Bulletin(
                school_id=school_id,
                student_id=enrollment.student_id,
                class_id=class_id,
                period=period,
                academic_year=academic_year,
                status="generated",
                data_json=data_json,
                overall_average=overall_avg,
                rank=rank,
                total_students=len(all_student_avgs),
                decision=decision,
                generated_at=datetime.utcnow(),
                generated_by=user.id,
            )
            db.add(bulletin)
            created += 1

    await db.flush()
    return {"created": created, "updated": updated}


@router.post("/publish/{class_id}/{period}")
async def publish_bulletins(
    class_id: int,
    period: str,
    academic_year: str = Query("2025-2026"),
    user: User = Depends(require_permission("bulletin.generate")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish all generated bulletins for a class (freezes them)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    bulletins = (await db.execute(
        select(Bulletin).where(
            Bulletin.class_id == class_id,
            Bulletin.period == period,
            Bulletin.academic_year == academic_year,
            Bulletin.school_id == school_id,
            Bulletin.status == "generated",
        )
    )).scalars().all()

    from datetime import datetime
    count = 0
    for b in bulletins:
        b.status = "published"
        b.published_at = datetime.utcnow()
        count += 1

    await db.flush()
    return {"published": count}


# ── Batch PDF Generation ────────────────────────────────────────

@router.get("/pdf-class/{class_id}/{period}")
async def generate_class_bulletins_pdf(
    class_id: int,
    period: str,
    academic_year: str = Query("2025-2026"),
    user: User = Depends(require_permission("bulletin.generate")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate PDF bulletins for all students in a class.

    Returns a list of {student_id, student_name, pdf_base64, error}.
    """
    import base64

    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    results = await generate_bulletins_for_class(
        db, class_id, period, academic_year
    )

    # Convert PDFs to base64 for JSON response
    output = []
    for r in results:
        entry = {
            "student_id": r["student_id"],
            "student_name": r["student_name"],
            "error": r["error"],
        }
        if r["pdf"]:
            entry["pdf_base64"] = base64.b64encode(r["pdf"]).decode("ascii")
        output.append(entry)

    return {"bulletins": output, "total": len(output)}
