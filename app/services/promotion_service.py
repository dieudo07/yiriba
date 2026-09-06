"""Yiriba SaaS — Service de passage de classe (fin d'année scolaire).

Gère le passage en masse des élèves d'une classe vers une classe de l'année
scolaire suivante : admis (passage), redoublants, à revoir.

Règles :
- Jamais de suppression de données : on marque l'inscription actuelle
  ("passed" | "repeated" | "to_review") et on crée la nouvelle inscription.
- Le compte utilisateur, le matricule, les notes, absences, bulletins et
  paiements restent intacts.
- Un élève ne peut avoir qu'UNE inscription active par année scolaire
  (contrôle anti-doublon).
- Chaque action est journalisée dans audit_logs via safe_audit.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db  # noqa: F401  (cohérence imports)
from app.models.academic_year import AcademicYear
from app.models.bulletin import Bulletin
from app.models.class_ import Class, Enrollment
from app.models.student import Student
from app.services.audit_service import safe_audit

DECISION_PASS = "pass"
DECISION_REPEAT = "repeat"
DECISION_REVIEW = "review"
DECISION_UNENROLLED = "unenrolled"  # Non réinscrit

_DECISION_TO_STATUS = {
    DECISION_PASS: "passed",
    DECISION_REPEAT: "repeated",
    DECISION_REVIEW: "to_review",
    DECISION_UNENROLLED: "not_reenrolled",
}


async def _get_class(db: AsyncSession, class_id: int, school_id: int) -> Class:
    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable dans cette école")
    return cls


async def _get_year_by_name(db: AsyncSession, school_id: int, name: str) -> AcademicYear:
    year = (await db.execute(
        select(AcademicYear).where(AcademicYear.school_id == school_id, AcademicYear.name == name)
    )).scalar_one_or_none()
    if not year:
        raise HTTPException(status_code=404, detail=f"Année scolaire '{name}' introuvable pour cette école")
    return year


async def compute_annual_averages(
    db: AsyncSession,
    school_id: int,
    class_id: int,
    academic_year: str,
) -> dict[int, float]:
    """Moyenne annuelle par élève (moyenne des moyennes publiées T1..T3/S1..S2).

    Utilise les bulletins (snapshot) si disponibles, sinon retourne un dict vide.
    """
    bulletins = (await db.execute(
        select(Bulletin).where(
            Bulletin.school_id == school_id,
            Bulletin.class_id == class_id,
            Bulletin.academic_year == academic_year,
        )
    )).scalars().all()

    by_student: dict[int, list[float]] = {}
    for b in bulletins:
        if b.overall_average is None:
            continue
        by_student.setdefault(b.student_id, []).append(float(b.overall_average))

    return {
        sid: round(sum(avgs) / len(avgs), 2)
        for sid, avgs in by_student.items()
        if avgs
    }


async def list_students_for_promotion(
    db: AsyncSession,
    school_id: int,
    class_id: int,
    academic_year: str,
) -> dict[str, Any]:
    """Liste les élèves d'une classe avec moyenne annuelle et décision proposée.

    Ne modifie aucune donnée : simple lecture pour la page de passage.
    """
    cls = await _get_class(db, class_id, school_id)

    # Année suivante suggérée (nom + 1)
    try:
        start = int(academic_year.split("-")[0])
        next_year = f"{start + 1}-{start + 2}"
    except (ValueError, IndexError):
        next_year = academic_year

    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year == academic_year,
            Enrollment.status.in_(["active", "passed", "repeated", "to_review"]),
        )
    )).scalars().all()

    student_ids = [e.student_id for e in enrollments]
    students = {}
    if student_ids:
        rows = (await db.execute(
            select(Student).where(Student.id.in_(student_ids))
        )).scalars().all()
        students = {s.id: s for s in rows}

    averages = await compute_annual_averages(db, school_id, class_id, academic_year)

    out = []
    for e in enrollments:
        s = students.get(e.student_id)
        if not s:
            continue
        avg = averages.get(s.id)
        # Proposition automatique (modifiable par l'admin) : >= 10 → Passe
        if e.status in ("passed", "repeated", "to_review"):
            decision = {
                "passed": DECISION_PASS,
                "repeated": DECISION_REPEAT,
                "to_review": DECISION_REVIEW,
            }[e.status]
        else:
            decision = None
        out.append({
            "student_id": s.id,
            "matricule": s.matricule,
            "first_name": s.first_name,
            "last_name": s.last_name,
            "gender": s.gender,
            "status": (s.status.value if hasattr(s.status, "value") else s.status),
            "enrollment_status": e.status,
            "current_decision": decision,
            "annual_average": avg,
            "suggested_decision": (
                DECISION_PASS if (avg is not None and avg >= 10)
                else DECISION_REPEAT if avg is not None
                else None
            ),
            "is_repeater": e.is_repeater,
        })

    return {
        "class": {"id": cls.id, "name": cls.name, "academic_year": cls.academic_year},
        "academic_year": academic_year,
        "next_year": next_year,
        "students": out,
    }


async def list_destination_classes(
    db: AsyncSession,
    school_id: int,
    next_year: str,
) -> list[dict[str, Any]]:
    """Classes disponibles pour l'année suivante (toutes, l'admin filtre visuellement)."""
    classes = (await db.execute(
        select(Class).where(
            Class.school_id == school_id,
            Class.academic_year == next_year,
            Class.is_active == True,  # noqa: E712
        ).order_by(Class.name)
    )).scalars().all()
    return [{"id": c.id, "name": c.name, "academic_year": c.academic_year} for c in classes]


async def _ensure_no_duplicate_active(
    db: AsyncSession,
    student_id: int,
    academic_year: str,
) -> None:
    """Lève une erreur si l'élève a déjà une inscription active pour l'année cible."""
    dup = (await db.execute(
        select(Enrollment.id).where(
            Enrollment.student_id == student_id,
            Enrollment.academic_year == academic_year,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"L'élève {student_id} a déjà une inscription active pour {academic_year}",
        )


async def apply_promotions(
    db: AsyncSession,
    school_id: int,
    user_id: int,
    source_class_id: int,
    source_year: str,
    target_year: str,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Applique les décisions de passage en masse.

    decisions: [{student_id, decision: pass|repeat|review, target_class_id?}]
    - pass  → inscription actuelle marquée "passed", nouvelle inscription
              active dans target_class_id (année cible).
    - repeat→ inscription actuelle marquée "repeated", nouvelle inscription
              active dans target_class_id (même niveau, nouvelle année).
    - review→ inscription actuelle marquée "to_review" uniquement,
              aucune nouvelle inscription.
    """
    if not decisions:
        raise HTTPException(status_code=400, detail="Aucune décision fournie")

    src_cls = await _get_class(db, source_class_id, school_id)
    target_year_obj = await _get_year_by_name(db, school_id, target_year)

    results = {"passed": 0, "repeated": 0, "review": 0, "unenrolled": 0, "errors": []}
    details_log = []

    for d in decisions:
        sid = d.get("student_id")
        decision = (d.get("decision") or "").lower()
        target_class_id = d.get("target_class_id")

        try:
            student = (await db.execute(
                select(Student).where(Student.id == sid, Student.school_id == school_id)
            )).scalar_one_or_none()
            if not student:
                raise HTTPException(status_code=404, detail=f"Élève {sid} introuvable")

            enr = (await db.execute(
                select(Enrollment).where(
                    Enrollment.student_id == sid,
                    Enrollment.class_id == source_class_id,
                    Enrollment.academic_year == source_year,
                    Enrollment.status.in_(["active", "passed", "repeated", "to_review"]),
                )
            )).scalar_one_or_none()
            if not enr:
                raise HTTPException(status_code=404, detail=f"Inscription introuvable pour l'élève {sid}")

            if decision == DECISION_REVIEW:
                enr.status = "to_review"
                results["review"] += 1
                details_log.append({"student": sid, "decision": "review"})
                continue

            if decision == DECISION_UNENROLLED:
                enr.status = "not_reenrolled"
                results["unenrolled"] += 1
                details_log.append({"student": sid, "decision": "unenrolled"})
                continue

            if not target_class_id:
                raise HTTPException(status_code=400, detail=f"Classe de destination manquante pour l'élève {sid}")

            tgt_cls = await _get_class(db, target_class_id, school_id)
            if tgt_cls.academic_year != target_year:
                raise HTTPException(
                    status_code=400,
                    detail=f"La classe {tgt_cls.name} n'appartient pas à l'année {target_year}",
                )

            # Anti-doublon : pas déjà actif dans l'année cible
            await _ensure_no_duplicate_active(db, sid, target_year)

            # Marquer l'ancienne inscription
            enr.status = _DECISION_TO_STATUS[decision]

            # Capacité
            count_q = select(func.count()).select_from(Enrollment).where(
                Enrollment.class_id == tgt_cls.id,
                Enrollment.status == "active",
            )
            current = (await db.execute(count_q)).scalar()
            if current >= tgt_cls.capacity:
                raise HTTPException(status_code=409, detail=f"Classe {tgt_cls.name} complète")

            new_enr = Enrollment(
                school_id=school_id,
                student_id=sid,
                class_id=tgt_cls.id,
                academic_year_id=target_year_obj.id,
                academic_year=target_year,
                is_repeater=(decision == DECISION_REPEAT),
                status="active",
            )
            db.add(new_enr)

            if decision == DECISION_PASS:
                results["passed"] += 1
            else:
                results["repeated"] += 1

            details_log.append({
                "student": sid,
                "decision": decision,
                "from_class": src_cls.name,
                "to_class": tgt_cls.name,
                "year": target_year,
            })

        except HTTPException as he:
            results["errors"].append({"student_id": sid, "detail": he.detail})

    await safe_audit(
        db, school_id=school_id, user_id=user_id,
        action="students.promote", resource="class", resource_id=source_class_id,
        details={
            "source_class": src_cls.name,
            "source_year": source_year,
            "target_year": target_year,
            "summary": {k: v for k, v in results.items() if k != "errors"},
            "operations": details_log[:50],  # limiter la taille du log
        },
    )

    await db.flush()
    return {
        "summary": results,
        "source_class": src_cls.name,
        "source_year": source_year,
        "target_year": target_year,
    }


async def get_next_year_preparation(db: AsyncSession, school_id: int, source_year: str) -> dict[str, Any]:
    """Vue d'ensemble de la préparation de l'année suivante : stats par décision.

    Agrège les décisions déjà prises (via les statuts d'inscription) pour
    toutes les classes de l'année source, et identifie les élèves sans décision.
    """
    try:
        start = int(source_year.split("-")[0])
        next_year = f"{start + 1}-{start + 2}"
    except (ValueError, IndexError):
        next_year = source_year

    # Classes de l'année source
    classes = (await db.execute(
        select(Class).where(
            Class.school_id == school_id,
            Class.academic_year == source_year,
        ).order_by(Class.name)
    )).scalars().all()
    class_by_id = {c.id: c for c in classes}

    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.school_id == school_id,
            Enrollment.academic_year == source_year,
            Enrollment.status.in_(["active", "passed", "repeated", "to_review", "not_reenrolled"]),
        )
    )).scalars().all()

    student_ids = list({e.student_id for e in enrollments})
    students = {}
    if student_ids:
        rows = (await db.execute(
            select(Student).where(Student.id.in_(student_ids))
        )).scalars().all()
        students = {s.id: s for s in rows}

    per_class = []
    counts = {"pass": 0, "repeat": 0, "review": 0, "unenrolled": 0, "undecided": 0}
    students_out = []
    for e in enrollments:
        s = students.get(e.student_id)
        if not s:
            continue
        cls = class_by_id.get(e.class_id)
        decision = {
            "active": None, "passed": DECISION_PASS, "repeated": DECISION_REPEAT,
            "to_review": DECISION_REVIEW, "not_reenrolled": DECISION_UNENROLLED,
        }[e.status]
        if decision is None:
            counts["undecided"] += 1
        else:
            counts[decision] += 1
        students_out.append({
            "student_id": s.id,
            "matricule": s.matricule,
            "first_name": s.first_name,
            "last_name": s.last_name,
            "class_id": e.class_id,
            "class_name": cls.name if cls else None,
            "decision": decision,
            "enrollment_status": e.status,
            "is_repeater": e.is_repeater,
        })

    for c in classes:
        class_enr = [e for e in enrollments if e.class_id == c.id]
        c_counts = {"pass": 0, "repeat": 0, "review": 0, "unenrolled": 0, "undecided": 0}
        for e in class_enr:
            d = {"active": None, "passed": DECISION_PASS, "repeated": DECISION_REPEAT,
                 "to_review": DECISION_REVIEW, "not_reenrolled": DECISION_UNENROLLED}[e.status]
            c_counts[d if d else "undecided"] += 1
        per_class.append({
            "class_id": c.id, "name": c.name, "total": len(class_enr), **c_counts,
        })

    # Classes déjà créées pour l'année suivante
    dest_classes = (await db.execute(
        select(Class).where(
            Class.school_id == school_id,
            Class.academic_year == next_year,
            Class.is_active == True,  # noqa: E712
        ).order_by(Class.name)
    )).scalars().all()

    next_year_exists = (await db.execute(
        select(AcademicYear.id).where(
            AcademicYear.school_id == school_id, AcademicYear.name == next_year
        )
    )).scalar_one_or_none()

    return {
        "source_year": source_year,
        "next_year": next_year,
        "next_year_registered": next_year_exists is not None,
        "stats": counts,
        "total": len(students_out),
        "per_class": per_class,
        "students": students_out,
        "dest_classes": [{"id": c.id, "name": c.name} for c in dest_classes],
    }


async def list_promotion_history(
    db: AsyncSession,
    school_id: int,
    academic_year: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Historique des passages : enrollments passés/répetés/à revoir par année.

    S'appuie sur les statuts d'inscription + audit_logs pour l'auteur.
    """
    q = (
        select(Enrollment, Student, Class)
        .join(Student, Student.id == Enrollment.student_id)
        .join(Class, Class.id == Enrollment.class_id)
        .where(
            Enrollment.school_id == school_id,
            Enrollment.status.in_(["passed", "repeated", "to_review"]),
        )
        .order_by(Enrollment.enrolled_at.desc())
        .limit(limit)
    )
    if academic_year:
        q = q.where(Enrollment.academic_year == academic_year)

    rows = (await db.execute(q)).all()
    out = []
    for enr, stu, cls in rows:
        out.append({
            "student_id": stu.id,
            "matricule": stu.matricule,
            "student_name": f"{stu.first_name} {stu.last_name}",
            "decision": {"passed": "Passé", "repeated": "Redoublé", "to_review": "À revoir"}[enr.status],
            "class_name": cls.name,
            "academic_year": enr.academic_year,
            "enrolled_at": str(enr.enrolled_at),
        })
    return out
