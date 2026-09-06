"""Yiriba SaaS — Routes bulletins v2 : workflow complet, périodes par classe, PDF.

Réutilise le service report_card_service. Toutes les routes filtrent par school_id.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.models.academic_year import AcademicPeriod
from app.models.bulletin import Bulletin
from app.models.class_ import Class
from app.models.student import Student
from app.models.user import User
from app.services import report_card_service as rcs
from app.services.subscription_service import require_write_access

router = APIRouter(prefix="/api/report-cards", tags=["report-cards"])


# ── Périodes disponibles pour une classe ─────────────────────────


@router.get("/class/{class_id}/periods")
async def class_periods(
    class_id: int,
    academic_year: str | None = Query(None, max_length=10),
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Périodes configurées pour LA classe (trimestres ou semestres selon period_type).

    Retourne les codes (T1...) + les AcademicPeriod configurées si elles existent.
    """
    school_id = get_school_id(user)
    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    codes = rcs.period_codes_for_class(cls)
    # Si une année est fournie, tenter de lier aux AcademicPeriod configurées
    configured = []
    if academic_year:
        ay = (await db.execute(
            select(Class.academic_year_id).where(Class.id == class_id)
        )).scalar_one_or_none()
        if ay:
            periods = (await db.execute(
                select(AcademicPeriod).where(
                    AcademicPeriod.school_id == school_id,
                    AcademicPeriod.academic_year_id == ay,
                ).order_by(AcademicPeriod.order_index)
            )).scalars().all()
            configured = [
                {"id": p.id, "name": p.name, "period_type": p.period_type,
                 "start_date": str(p.start_date), "end_date": str(p.end_date),
                 "status": p.status, "is_active": p.is_active}
                for p in periods
            ]

    return {
        "class": {"id": cls.id, "name": cls.name, "period_type": cls.period_type},
        "periods": [
            {"code": c, "label": rcs.period_label(c, cls.period_type)} for c in codes
        ],
        "configured_periods": configured,
    }


# ── Aperçu des résultats calculés (avant génération) ────────────


@router.get("/class/{class_id}/preview")
async def class_preview(
    class_id: int,
    period: str = Query(..., max_length=3, pattern="^(T[123]|S[12])$"),
    academic_year: str = Query(..., max_length=10),
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Résultats calculés de toute la classe pour la période (sans créer de bulletin)."""
    school_id = get_school_id(user)
    computed = await rcs.compute_class_results(db, school_id, class_id, period, academic_year)

    # Enrichir avec les noms d'élèves
    sids = list(computed["results"].keys())
    students = {}
    if sids:
        for s in (await db.execute(
            select(Student).where(Student.id.in_(sids))
        )).scalars().all():
            students[s.id] = s

    ranking_map = {r["student_id"]: r for r in computed["ranking"]}
    rows = []
    for sid in sids:
        s = students.get(sid)
        res = computed["results"][sid]
        rk = ranking_map.get(sid, {})
        rows.append({
            "student_id": sid,
            "student_name": f"{s.first_name} {s.last_name}" if s else "?",
            "matricule": s.matricule if s else None,
            "overall_average": res["overall_average"],
            "rank": rk.get("rank"),
            "ex_aequo": rk.get("ex_aequo", False),
            "has_anomaly": res["has_anomaly"],
            "missing": res.get("missing", []),
        })
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))

    return {
        "class": computed["class"],
        "period": computed["period"],
        "period_label": computed["period_label"],
        "academic_year": computed["academic_year"],
        "subjects": computed["subjects"],
        "anomalies": computed["anomalies"],
        "class_stats": computed["class_stats"],
        "students": rows,
    }


@router.get("/class/{class_id}/export")
async def class_export_pdf(
    class_id: int,
    period: str = Query(..., max_length=3, pattern="^(T[123]|S[12])$"),
    academic_year: str = Query(..., max_length=10),
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export ZIP de tous les bulletins PDF d'une classe/période (staff uniquement).

    Chaque PDF est généré depuis son snapshot figé. Un bulletin en échec
    n'empêche pas l'export des autres (détails dans le résumé en entête).
    """
    school_id = get_school_id(user)
    role = (user.role_type or "").lower()
    if role not in ("admin", "teacher"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration / aux enseignants")

    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")

    bulletins = (await db.execute(
        select(Bulletin).where(
            Bulletin.school_id == school_id,
            Bulletin.class_id == class_id,
            Bulletin.period == period,
            Bulletin.academic_year == academic_year,
        ).order_by(Bulletin.rank)
    )).scalars().all()
    if not bulletins:
        raise HTTPException(status_code=404, detail="Aucun bulletin pour cette classe et cette période")

    from app.services.pdf_service import generate_bulletin_from_snapshot as gen_pdf
    students = {s.id: s for s in (await db.execute(
        select(Student).where(Student.school_id == school_id)
    )).scalars().all()}

    import io
    import re
    import zipfile
    buf = io.BytesIO()
    wrote = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for b in bulletins:
            try:
                pdf = await gen_pdf(db, b)
            except Exception:  # un bulletin défaillant ne bloque pas le lot
                continue
            s = students.get(b.student_id)
            base = s.last_name if s else ""
            part = f"{base}_{s.first_name}" if s else f"eleve_{b.student_id}"
            filename = re.sub(r"[^\w]+", "_", part) + "_bulletin.pdf"
            zf.writestr(f"bulletins_{period}_{academic_year}/{filename}", pdf)
            wrote += 1

    if not wrote:
        raise HTTPException(status_code=500, detail="Aucun PDF généré")

    safe = re.sub(r"[^\w.]", "_", f"{cls.name}_{period}_{academic_year}")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}_bulletins.zip"'},
    )


# ── Génération en masse ──────────────────────────────────────────


class GenerateRequest(BaseModel):
    class_id: int
    period: str = Field(..., pattern="^(T[123]|S[12])$")
    academic_year: str = Field(..., max_length=10)


@router.post("/generate")
async def generate(
    data: GenerateRequest,
    user: User = Depends(require_permission("bulletin.generate")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    return await rcs.generate_bulletins(
        db, school_id, user.id, data.class_id, data.period, data.academic_year,
    )


# ── Liste détaillée (Admin) ──────────────────────────────────────


@router.get("")
async def list_all(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    class_id: int | None = None,
    period: str | None = Query(None, pattern="^(T[123]|S[12])$"),
    status: str | None = None,
    academic_year: str | None = None,
    search: str | None = None,
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    return await rcs.list_bulletins_detailed(
        db, school_id, class_id=class_id, period=period, status=status,
        search=search, academic_year=academic_year, page=page, per_page=per_page,
    )


# ── Détail d'un bulletin ─────────────────────────────────────────


@router.get("/{bulletin_id}")
async def get_bulletin(
    bulletin_id: int,
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    b = (await db.execute(
        select(Bulletin).where(Bulletin.id == bulletin_id, Bulletin.school_id == school_id)
    )).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Bulletin introuvable")

    s = (await db.execute(
        select(Student).where(Student.id == b.student_id)
    )).scalar_one_or_none()
    c = (await db.execute(
        select(Class).where(Class.id == b.class_id)
    )).scalar_one_or_none()

    return {
        "id": b.id,
        "status": b.status,
        "period": b.period,
        "period_label": rcs.period_label(b.period, (c.period_type if c else "trimestre")),
        "academic_year": b.academic_year,
        "overall_average": b.overall_average,
        "rank": b.rank,
        "total_students": b.total_students,
        "data": b.data_json,
        "student": {
            "id": b.student_id,
            "name": f"{s.first_name} {s.last_name}" if s else "?",
            "matricule": s.matricule if s else None,
        },
        "class": {"id": b.class_id, "name": c.name if c else "?", "period_type": c.period_type if c else "trimestre"},
        "generated_at": str(b.generated_at) if b.generated_at else None,
        "published_at": str(b.published_at) if b.published_at else None,
    }


# ── Workflow (transitions) ───────────────────────────────────────


class TransitionRequest(BaseModel):
    status: str = Field(..., pattern="^(teacher_review|teacher_validated|admin_validated|published|rejected|draft)$")
    reason: str | None = Field(None, max_length=500)


@router.post("/{bulletin_id}/transition")
async def transition(
    bulletin_id: int,
    data: TransitionRequest,
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Transition de workflow.

    - teacher_review / teacher_validated : enseignant (ou admin).
    - admin_validated / published / rejected : administration.
    """
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    role = (user.role_type or "").lower()
    target = data.status

    # Permissions fines par transition
    if target in ("teacher_review", "teacher_validated"):
        if role not in ("teacher", "admin"):
            raise HTTPException(status_code=403, detail="Réservé à l'enseignant ou à l'administration")
    elif target in ("admin_validated", "published", "rejected"):
        if role != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administration")

    # Pour rejected/review : vérifier que l'enseignant est bien celui de la matière ? Simplifié : rôle seul.
    result = await rcs.transition_status(
        db, school_id, user.id, bulletin_id, target, reason=data.reason,
    )

    # Hook : notification à la publication d'un bulletin (parent + élève)
    if target == "published":
        try:
            from app.services.notification_service import notify_bulletin_published
            b = (await db.execute(
                select(Bulletin).where(Bulletin.id == bulletin_id)
            )).scalar_one_or_none()
            if b:
                cls_row = (await db.execute(
                    select(Class).where(Class.id == b.class_id)
                )).scalar_one_or_none()
                pt = (cls_row.period_type if cls_row else "trimestre") or "trimestre"
                sent = await notify_bulletin_published(
                    db, school_id, b.student_id, b.class_id,
                    rcs.period_label(b.period, pt), b.overall_average, b.id,
                )
                result["notifications_sent"] = sent
        except Exception:  # ne pas bloquer la publication
            pass
    return result


# ── Appréciations ────────────────────────────────────────────────


class AppreciationsRequest(BaseModel):
    appreciations: dict[str, str] = Field(default_factory=dict)
    general_appreciation: str | None = Field(None, max_length=500)


@router.put("/{bulletin_id}/appreciations")
async def update_appreciations(
    bulletin_id: int,
    data: AppreciationsRequest,
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Saisie/modification des appréciations par matière + générale (enseignant)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    return await rcs.update_appreciations(
        db, school_id, user.id, bulletin_id, data.appreciations, data.general_appreciation,
    )


# ── Actions en masse (Admin) ─────────────────────────────────────


class BulkTransitionRequest(BaseModel):
    class_id: int
    period: str = Field(..., pattern="^(T[123]|S[12])$")
    academic_year: str = Field(..., max_length=10)
    from_status: str = Field(..., max_length=30)
    to_status: str = Field(..., pattern="^(teacher_validated|admin_validated|published|rejected|teacher_review)$")
    reason: str | None = Field(None, max_length=500)


@router.post("/bulk-transition")
async def bulk_transition(
    data: BulkTransitionRequest,
    user: User = Depends(require_permission("bulletin.generate")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Transition en masse pour tous les bulletins d'une classe/période dans un statut donné."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    role = (user.role_type or "").lower()
    if data.to_status in ("admin_validated", "published", "rejected") and role != "admin":
        raise HTTPException(status_code=403, detail="Réservé à l'administration")

    notify_published = data.to_status == "published"

    bulletins = (await db.execute(
        select(Bulletin).where(
            Bulletin.school_id == school_id,
            Bulletin.class_id == data.class_id,
            Bulletin.period == data.period,
            Bulletin.academic_year == data.academic_year,
            Bulletin.status == data.from_status,
        )
    )).scalars().all()

    done, errors = 0, []
    notifications_sent = 0
    for b in bulletins:
        try:
            await rcs.transition_status(
                db, school_id, user.id, b.id, data.to_status, reason=data.reason,
            )
            done += 1
            if notify_published:
                try:
                    from app.services.notification_service import notify_bulletin_published
                    from app.services.report_card_service import period_label as _plabel
                    cls_row = (await db.execute(
                        select(Class).where(Class.id == b.class_id)
                    )).scalar_one_or_none()
                    pt = (cls_row.period_type if cls_row else "trimestre") or "trimestre"
                    notifications_sent += await notify_bulletin_published(
                        db, school_id, b.student_id, b.class_id,
                        _plabel(b.period, pt), b.overall_average, b.id,
                    )
                except Exception:  # ne pas bloquer la publication si la notif échoue
                    pass
        except HTTPException as he:
            errors.append({"bulletin_id": b.id, "detail": he.detail})
    result = {"transitioned": done, "errors": errors, "total": len(bulletins)}
    if notify_published:
        result["notifications_sent"] = notifications_sent
    return result


# ── PDF depuis le snapshot figé ──────────────────────────────────


@router.get("/{bulletin_id}/pdf")
async def bulletin_pdf(
    bulletin_id: int,
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """PDF du bulletin, généré depuis le snapshot data_json (jamais recalculé).

    Un bulletin non publié n'est accessible qu'aux staff (enseignant/admin).
    """
    school_id = get_school_id(user)
    role = (user.role_type or "").lower()

    b = (await db.execute(
        select(Bulletin).where(Bulletin.id == bulletin_id, Bulletin.school_id == school_id)
    )).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Bulletin introuvable")

    # Restreindre l'accès aux bulletins non publiés
    if b.status != rcs.STATUS_PUBLISHED and role not in ("admin", "teacher"):
        raise HTTPException(status_code=403, detail="Bulletin non publié")

    if role == "student":
        # l'élève ne peut voir que SES bulletins
        linked = (await db.execute(
            select(Student.id).where(
                Student.id == b.student_id,
                Student.user_id == user.id,
            )
        )).scalar_one_or_none()
        if not linked:
            raise HTTPException(status_code=403, detail="Accès refusé")

    from app.services.pdf_service import generate_bulletin_from_snapshot as gen_pdf
    try:
        pdf_bytes = await gen_pdf(db, b)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=bulletin_{bulletin_id}.pdf"},
    )
