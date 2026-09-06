"""Yiriba SaaS — Service de gestion des bulletins scolaires.

Workflow complet :
  draft → teacher_review → teacher_validated → admin_validated → published
  + rejected (renvoyé à l'enseignant avec motif)

Règles :
- Les périodes du bulletin proviennent de la configuration de LA CLASSE
  (Class.period_type : trimestre → T1/T2/T3, semestre → S1/S2).
  Une même école peut mélanger les deux types selon les classes.
- Moyennes calculées côté serveur à partir des Grade/Evaluation existants.
  Aucune saisie manuelle de moyenne générale.
- Coefficients pris depuis ClassSubject (config réelle de la classe),
  fallback sur Evaluation.coefficient.
- Rang calculé dans le contexte : même école + même classe + même période +
  même année. Les égalités de moyenne partagent le même rang (classement
  competition ranking : 1, 2, 2, 4).
- Anomalies détectées avant validation (matières sans note, etc.).
- Multi-tenant : toutes les requêtes filtrent par school_id.
- Chaque transition est journalisée via safe_audit.
- Bulletin publié = verrouillé (modification seulement avec bulletin.override).
"""

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bulletin import Bulletin
from app.models.class_ import Class, ClassSubject, Enrollment, Subject
from app.models.discipline import DisciplinaryRecord
from app.models.grade import Evaluation, Grade
from app.models.school import School
from app.models.student import Student
from app.services.audit_service import safe_audit
from app.services.grade_calculator import apply_discipline, get_mention

# ── Workflow ─────────────────────────────────────────────────────

STATUS_DRAFT = "draft"
STATUS_TEACHER_REVIEW = "teacher_review"
STATUS_TEACHER_VALIDATED = "teacher_validated"
STATUS_ADMIN_VALIDATED = "admin_validated"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"

_ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    STATUS_DRAFT: [STATUS_TEACHER_REVIEW],
    STATUS_TEACHER_REVIEW: [STATUS_TEACHER_VALIDATED, STATUS_DRAFT],
    STATUS_TEACHER_VALIDATED: [STATUS_ADMIN_VALIDATED, STATUS_REJECTED],
    STATUS_ADMIN_VALIDATED: [STATUS_PUBLISHED, STATUS_REJECTED],
    STATUS_PUBLISHED: [],  # verrouillé (republish via correction dédiée)
    STATUS_REJECTED: [STATUS_TEACHER_REVIEW],  # retour à la révision
}

# Codes de période par type de classe
_PERIOD_CODES = {
    "trimestre": ["T1", "T2", "T3"],
    "semestre": ["S1", "S2"],
}


def period_codes_for_class(cls: Class) -> list[str]:
    """Codes de période selon la configuration de la classe."""
    return _PERIOD_CODES.get((cls.period_type or "trimestre").lower(), _PERIOD_CODES["trimestre"])


def period_label(code: str, period_type: str = "trimestre") -> str:
    """Label humain d'un code de période selon le type de la classe."""
    try:
        n = int(code[-1])
    except (ValueError, IndexError):
        return code
    prefix = "Semestre" if (period_type or "").lower().startswith("sem") else "Trimestre"
    return f"{prefix} {n}"


# ── Calcul des moyennes ──────────────────────────────────────────


async def compute_class_results(
    db: AsyncSession,
    school_id: int,
    class_id: int,
    period: str,
    academic_year: str,
) -> dict[str, Any]:
    """Calcule les résultats de toute la classe pour une période.

    Retourne :
    {
      "class": {...}, "period_type": ..., "period_label": ...,
      "subjects": [{id, name, coefficient, max_score}...],   # config de la classe
      "anomalies": [str...],                                  # détectées globalement
      "subject_stats": {subject_id: {"class_average": float|None}},  # moy. de classe par matière
      "discipline_mode": "conduct" | "general_average",
      "results": {
         student_id: {
            "subjects": {subject_id: {"average": float|None, "grades": {...}}},
            "overall_average": float|None,
            "has_anomaly": bool,
         }
      },
      "ranking": [{student_id, average, rank, ex_aequo}...],
      "class_stats": {"average": ..., "best": ..., "effectif": ...},
    }
    """
    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable dans cette école")

    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    discipline_mode = (school.discipline_mode if school else None) or "conduct"

    # Points de discipline déduits par élève sur la période (figés dans le snapshot)
    discipline_rows = (await db.execute(
        select(
            DisciplinaryRecord.student_id,
            func.coalesce(func.sum(DisciplinaryRecord.points_deducted), 0.0),
        ).where(
            DisciplinaryRecord.school_id == school_id,
            DisciplinaryRecord.period == period,
            DisciplinaryRecord.academic_year == academic_year,
            DisciplinaryRecord.status == "active",
        ).group_by(DisciplinaryRecord.student_id)
    )).all()
    discipline_by_student = {r[0]: float(r[1] or 0.0) for r in discipline_rows}

    # Matières configurées pour la classe (source de vérité des coefficients)
    class_subjects = (await db.execute(
        select(ClassSubject, Subject)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .where(
            ClassSubject.class_id == class_id,
            ClassSubject.is_active == True,  # noqa: E712
        )
    )).all()
    subjects = [
        {
            "id": cs.subject_id,
            "name": subj.name,
            "coefficient": cs.coefficient or 1,
            "max_score": cs.max_score or 20.0,
        }
        for cs, subj in class_subjects
    ]

    # Évaluations de la période
    evaluations = (await db.execute(
        select(Evaluation).where(
            Evaluation.class_id == class_id,
            Evaluation.period == period,
            Evaluation.academic_year == academic_year,
            Evaluation.school_id == school_id,
        )
    )).scalars().all()

    # Élèves actifs de la classe
    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
    )).scalars().all()
    student_ids = [e.student_id for e in enrollments]

    # Toutes les notes de ces élèves pour ces évaluations (1 seule requête)
    grades: list[Grade] = []
    if evaluations and student_ids:
        grades = (await db.execute(
            select(Grade).where(
                Grade.evaluation_id.in_([e.id for e in evaluations]),
                Grade.student_id.in_(student_ids),
            )
        )).scalars().all()

    eval_by_id = {e.id: e for e in evaluations}

    # results[student_id][subject_id] = list[(grade_value, max_grade)]
    raw: dict[int, dict[int, list[tuple[float | None, float]]]] = {}
    for g in grades:
        ev = eval_by_id.get(g.evaluation_id)
        if not ev:
            continue
        raw.setdefault(g.student_id, {}).setdefault(ev.subject_id, []).append(
            (g.grade, ev.max_grade or 20.0)
        )

    anomalies: list[str] = []
    results: dict[int, dict[str, Any]] = {}

    for sid in student_ids:
        subj_avgs: dict[int, dict[str, Any]] = {}
        total_pts = 0.0
        total_cfs = 0
        student_missing: list[str] = []
        for s in subjects:
            entries = raw.get(sid, {}).get(s["id"], [])
            # moyenne de la matière = moyenne simple des notes ramenées sur 20
            values = [v for v, _max in entries if v is not None]
            if entries and values:
                # normaliser chaque note sur 20 puis moyenner
                normalized = []
                for v, mx in entries:
                    if v is None:
                        continue
                    normalized.append((v / mx * 20.0) if mx and mx != 20 else v)
                avg = round(sum(normalized) / len(normalized), 2)
            else:
                avg = None
            subj_avgs[s["id"]] = {
                "average": avg,
            }
            # détail des notes par type d'évaluation
            detail: dict[str, float | None] = {}
            for g in grades:
                ev = eval_by_id.get(g.evaluation_id)
                if g.student_id == sid and ev and ev.subject_id == s["id"]:
                    detail[ev.assessment_type] = g.grade
            subj_avgs[s["id"]]["grades"] = detail

            if avg is not None:
                total_pts += avg * s["coefficient"]
                total_cfs += s["coefficient"]
            else:
                if entries:  # évaluations existent mais notes manquantes
                    student_missing.append(f"{s['name']} (note manquante)")
                # matière sans aucune évaluation : anomalie globale, pas par élève

        overall = round(total_pts / total_cfs, 2) if total_cfs > 0 else None
        results[sid] = {
            "subjects": subj_avgs,
            "overall_average": overall,
            "has_anomaly": bool(student_missing),
            "missing": student_missing,
            "discipline_deductions": discipline_by_student.get(sid, 0.0),
        }

    # Moyenne de classe par matière (moyenne des moyennes des élèves notés)
    subject_stats: dict[int, float | None] = {}
    for s in subjects:
        vals = [
            results[sid]["subjects"][s["id"]]["average"]
            for sid in student_ids
            if results[sid]["subjects"][s["id"]]["average"] is not None
        ]
        subject_stats[s["id"]] = round(sum(vals) / len(vals), 2) if vals else None

    # Anomalies globales
    for s in subjects:
        has_eval = any(e.subject_id == s["id"] for e in evaluations)
        if not has_eval:
            anomalies.append(f"Matière « {s['name']} » : aucune évaluation pour cette période.")
    no_grades = [s["name"] for s in subjects
                 if any(e.subject_id == s["id"] for e in evaluations)
                 and not any(
                     g.grade is not None
                     and (ev := eval_by_id.get(g.evaluation_id)) is not None
                     and ev.subject_id == s["id"]
                     for g in grades
                 )]
    if no_grades:
        anomalies.append(f"{len(no_grades)} matière(s) sans aucune note : {', '.join(no_grades)}.")

    # Classement (mêmes règles de moyenne que ci-dessus, mutualisées)
    ranking = sorted(
        (
            {"student_id": sid, "average": results[sid]["overall_average"]}
            for sid in student_ids
            if results[sid]["overall_average"] is not None
        ),
        key=lambda x: x["average"],
        reverse=True,
    )
    # rang avec égalités (competition ranking)
    last_avg, last_rank = None, 0
    for i, entry in enumerate(ranking, start=1):
        if entry["average"] == last_avg:
            entry["rank"] = last_rank
            entry["ex_aequo"] = True
            for prev in ranking:
                if prev["average"] == entry["average"]:
                    prev["ex_aequo"] = True
        else:
            entry["rank"] = i
            entry["ex_aequo"] = False
            last_avg, last_rank = entry["average"], i

    averages = [r["average"] for r in ranking]
    class_stats = {
        "average": round(sum(averages) / len(averages), 2) if averages else None,
        "best": averages[0] if averages else None,
        "worst": averages[-1] if averages else None,
        "effectif": len(student_ids),
        "graded": len(averages),
    }

    return {
        "class": {"id": cls.id, "name": cls.name, "period_type": cls.period_type},
        "cls": cls,
        "period": period,
        "period_label": period_label(period, cls.period_type),
        "academic_year": academic_year,
        "subjects": subjects,
        "anomalies": anomalies,
        "subject_stats": subject_stats,
        "discipline_mode": discipline_mode,
        "results": results,
        "ranking": ranking,
        "class_stats": class_stats,
    }


# ── Snapshot & création ──────────────────────────────────────────


def build_snapshot(computed: dict[str, Any], sid: int, appreciations: dict[str, str] | None = None,
                   general_appreciation: str | None = None) -> dict[str, Any]:
    """Construit le snapshot figé d'un élève à partir des résultats calculés."""
    res = computed["results"][sid]
    ranking_entry = next((r for r in computed["ranking"] if r["student_id"] == sid), None)
    subjects_out = []
    subject_stats = computed.get("subject_stats", {})
    for s in computed["subjects"]:
        sa = res["subjects"].get(s["id"], {})
        avg = sa.get("average")
        subjects_out.append({
            "id": s["id"],
            "name": s["name"],
            "coefficient": s["coefficient"],
            "max_score": s["max_score"],
            "grades": sa.get("grades", {}),
            "average": avg,
            "class_average": subject_stats.get(s["id"]),
            "appreciation": (appreciations or {}).get(str(s["id"]))
                or (auto_appreciation(avg) if avg is not None else None),
        })

    overall = res["overall_average"]
    discipline_mode = computed.get("discipline_mode", "conduct")
    total_deductions = res.get("discipline_deductions", 0.0)
    discipline = apply_discipline(overall or 0.0, discipline_mode, total_deductions)
    display_average = discipline["display_average"]
    mention = get_mention(display_average)
    pt = (computed["class"].get("period_type") or "trimestre").lower()
    periods_list = {"semestre": ["S1", "S2"]}.get(pt, ["T1", "T2", "T3"])
    is_last_period = computed["period"] in periods_list and computed["period"] == periods_list[-1]
    decision = ("Admis" if display_average >= 10 else "Redouble") if is_last_period else None

    return {
        "subjects": subjects_out,
        "overall_average": overall,
        "display_average": display_average,
        "rank": ranking_entry["rank"] if ranking_entry else None,
        "ex_aequo": ranking_entry["ex_aequo"] if ranking_entry else False,
        "total_students": computed["class_stats"]["effectif"],
        "class_average": computed["class_stats"]["average"],
        "class_best": computed["class_stats"]["best"],
        "class_worst": computed["class_stats"]["worst"],
        "discipline_mode": discipline_mode,
        "total_deductions": total_deductions,
        "conduct_score": discipline["conduct_score"],
        "discipline_line": discipline["discipline_line"],
        "mention": mention,
        "decision": decision,
        "is_last_period": is_last_period,
        "period": computed["period"],
        "period_label": computed.get("period_label"),
        "anomalies": res.get("missing", []),
        "general_appreciation": general_appreciation,
        "generated_at": datetime.utcnow().isoformat(),
    }


def auto_appreciation(avg: float | None) -> str | None:
    """Suggestion d'appréciation selon la moyenne (modifiable par l'enseignant)."""
    if avg is None:
        return None
    if avg >= 16:
        return "Excellent travail, continuez ainsi."
    if avg >= 14:
        return "Très bon travail."
    if avg >= 12:
        return "Bon travail, des progrès constants."
    if avg >= 10:
        return "Travail satisfaisant, peut mieux faire."
    return "Insuffisant, des efforts sont à fournir."


# ── Accès bulletin ───────────────────────────────────────────────


async def _get_bulletin(db: AsyncSession, school_id: int, bulletin_id: int) -> Bulletin:
    b = (await db.execute(
        select(Bulletin).where(Bulletin.id == bulletin_id, Bulletin.school_id == school_id)
    )).scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Bulletin introuvable")
    return b


async def generate_bulletins(
    db: AsyncSession,
    school_id: int,
    user_id: int,
    class_id: int,
    period: str,
    academic_year: str,
) -> dict[str, Any]:
    """Génère/rafraîchit les bulletins (statut draft) pour une classe et une période.

    Ne touche pas aux bulletins déjà publiés. Retourne les compteurs + anomalies.
    """
    computed = await compute_class_results(db, school_id, class_id, period, academic_year)
    if computed["class"]["period_type"] not in _PERIOD_CODES or period not in period_codes_for_class(
        computed["cls"]
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Période {period} invalide pour une classe en {computed['class']['period_type']}",
        )

    created, updated = 0, 0
    incomplete = 0
    for sid in computed["results"]:
        snapshot = build_snapshot(computed, sid)
        if snapshot["anomalies"] or snapshot["overall_average"] is None:
            incomplete += 1
        existing = (await db.execute(
            select(Bulletin).where(
                Bulletin.school_id == school_id,
                Bulletin.student_id == sid,
                Bulletin.class_id == class_id,
                Bulletin.period == period,
                Bulletin.academic_year == academic_year,
            )
        )).scalar_one_or_none()
        if existing:
            if existing.status == STATUS_PUBLISHED:
                continue  # ne jamais écraser un bulletin publié
            existing.data_json = json.dumps(snapshot, ensure_ascii=False)
            existing.overall_average = snapshot["overall_average"] or 0
            existing.rank = snapshot["rank"]
            existing.total_students = snapshot["total_students"]
            existing.status = STATUS_DRAFT
            existing.generated_at = datetime.utcnow()
            existing.generated_by = user_id
            updated += 1
        else:
            db.add(Bulletin(
                school_id=school_id,
                student_id=sid,
                class_id=class_id,
                period=period,
                academic_year=academic_year,
                status=STATUS_DRAFT,
                data_json=json.dumps(snapshot, ensure_ascii=False),
                overall_average=snapshot["overall_average"] or 0,
                rank=snapshot["rank"],
                total_students=snapshot["total_students"],
                generated_at=datetime.utcnow(),
                generated_by=user_id,
            ))
            created += 1

    await safe_audit(
        db, school_id=school_id, user_id=user_id,
        action="bulletin.generate", resource="class", resource_id=class_id,
        details={"period": period, "year": academic_year,
                 "created": created, "updated": updated, "incomplete": incomplete},
    )
    await db.flush()
    return {
        "created": created, "updated": updated, "incomplete": incomplete,
        "anomalies": computed["anomalies"],
        "period_type": computed["class"]["period_type"],
        "period_label": computed["period_label"],
    }


async def transition_status(
    db: AsyncSession,
    school_id: int,
    user_id: int,
    bulletin_id: int,
    new_status: str,
    reason: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Change le statut d'un bulletin en respectant le workflow.

    force=True exige la permission bulletin.override (correction après publication).
    """
    b = await _get_bulletin(db, school_id, bulletin_id)
    current = b.status

    if force:
        # republication / correction après publication
        b.data_json = b.data_json  # inchangé ici : le contenu est mis à jour à part
        b.status = new_status
        if new_status == STATUS_PUBLISHED:
            b.published_at = datetime.utcnow()
        await safe_audit(
            db, school_id=school_id, user_id=user_id,
            action="bulletin.override", resource="bulletin", resource_id=bulletin_id,
            details={"from": current, "to": new_status, "reason": reason},
        )
        await db.flush()
        return {"id": bulletin_id, "status": new_status}

    allowed = _ALLOWED_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Transition « {current} » → « {new_status} » non autorisée",
        )

    b.status = new_status
    if new_status == STATUS_PUBLISHED:
        b.published_at = datetime.utcnow()
    if new_status == STATUS_REJECTED and reason:
        data = json.loads(b.data_json or "{}")
        data["rejection_reason"] = reason
        data["rejected_at"] = datetime.utcnow().isoformat()
        b.data_json = json.dumps(data, ensure_ascii=False)

    await safe_audit(
        db, school_id=school_id, user_id=user_id,
        action=f"bulletin.{new_status}", resource="bulletin", resource_id=bulletin_id,
        details={"from": current, "reason": reason},
    )
    await db.flush()
    return {"id": bulletin_id, "status": new_status}


async def update_appreciations(
    db: AsyncSession,
    school_id: int,
    user_id: int,
    bulletin_id: int,
    appreciations: dict[str, str],
    general_appreciation: str | None = None,
) -> dict[str, Any]:
    """Met à jour les appréciations d'un bulletin (enseignant).

    Interdit si le bulletin est publié (sauf via override, non géré ici).
    """
    b = await _get_bulletin(db, school_id, bulletin_id)
    if b.status == STATUS_PUBLISHED:
        raise HTTPException(
            status_code=409,
            detail="Bulletin publié : verrouillé. Une correction nécessite la permission bulletin.override.",
        )
    data = json.loads(b.data_json or "{}")
    for subj in data.get("subjects", []):
        key = str(subj.get("id"))
        if key in appreciations:
            subj["appreciation"] = appreciations[key]
    if general_appreciation is not None:
        data["general_appreciation"] = general_appreciation
    b.data_json = json.dumps(data, ensure_ascii=False)
    await safe_audit(
        db, school_id=school_id, user_id=user_id,
        action="bulletin.appreciations", resource="bulletin", resource_id=bulletin_id,
        details={"subjects_updated": list(appreciations.keys())},
    )
    await db.flush()
    return {"id": bulletin_id, "ok": True}


async def list_bulletins_detailed(
    db: AsyncSession,
    school_id: int,
    class_id: int | None = None,
    period: str | None = None,
    status: str | None = None,
    search: str | None = None,
    academic_year: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    import math

    from sqlalchemy import func

    conditions = [Bulletin.school_id == school_id]
    if class_id:
        conditions.append(Bulletin.class_id == class_id)
    if period:
        conditions.append(Bulletin.period == period)
    if status:
        conditions.append(Bulletin.status == status)
    if academic_year:
        conditions.append(Bulletin.academic_year == academic_year)

    total = (await db.execute(
        select(func.count()).select_from(Bulletin).where(*conditions)
    )).scalar()
    rows = (await db.execute(
        select(Bulletin).where(*conditions)
        .order_by(Bulletin.generated_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()

    student_ids = list({b.student_id for b in rows})
    class_ids = list({b.class_id for b in rows})
    students = {}
    if student_ids:
        for s in (await db.execute(select(Student).where(Student.id.in_(student_ids)))).scalars().all():
            students[s.id] = s
    classes = {}
    if class_ids:
        for c in (await db.execute(select(Class).where(Class.id.in_(class_ids)))).scalars().all():
            classes[c.id] = c

    out = []
    for b in rows:
        s = students.get(b.student_id)
        c = classes.get(b.class_id)
        name = f"{s.first_name} {s.last_name}" if s else "?"
        if search and search.lower() not in name.lower() and search.lower() not in (s.matricule or "").lower():
            continue
        pt = (c.period_type if c else "trimestre") or "trimestre"
        out.append({
            "id": b.id, "student_id": b.student_id,
            "student_name": name, "matricule": s.matricule if s else None,
            "class_id": b.class_id, "class_name": c.name if c else "?",
            "period": b.period, "period_label": period_label(b.period, pt),
            "academic_year": b.academic_year, "status": b.status,
            "overall_average": b.overall_average, "rank": b.rank,
            "total_students": b.total_students,
            "published_at": str(b.published_at) if b.published_at else None,
        })
    # la recherche post-filtre fausse la pagination, acceptable pour l'usage interne
    return {"bulletins": out, "total": total, "page": page, "per_page": per_page,
            "total_pages": math.ceil(total / per_page) if total else 1}
