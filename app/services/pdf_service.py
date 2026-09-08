"""Yiriba SaaS — PDF generation service using WeasyPrint + Jinja2.

Generates:
- Bulletin scolaire (student report card)
- Reçu de paiement (payment receipt)

All templates are HTML/CSS rendered to PDF via WeasyPrint.
Templates live in app/services/pdf_templates/.
"""

import hashlib
import io
import json
import os
import secrets
from datetime import datetime
from io import BytesIO
from pathlib import Path

import qrcode
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from xhtml2pdf import pisa

from app.core.config import get_settings
from app.models.bulletin import Bulletin
from app.models.class_ import Class, ClassSubject, Enrollment, Subject
from app.models.discipline import DisciplinaryRecord
from app.models.grade import Evaluation, Grade
from app.models.payment import FeeObligation, Payment
from app.models.school import School
from app.models.student import Student
from app.services.grade_calculator import (
    apply_discipline,
    calculate_overall_average,
    conduct_appreciation,
    get_mention,
    get_mention_bg,
    get_mention_color,
)
from app.services.verification_service import bulletin_signature, receipt_signature

# ── Template engine ─────────────────────────────────────────────

_TEMPLATE_DIR = Path(__file__).parent / "pdf_templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,  # Échappement HTML de toutes les données métier (anti-XSS PDF)
)
# Chemin absolu de la police Unicode injecté dans les templates (@font-face)
_jinja_env.globals["_tpl_dir"] = str(_TEMPLATE_DIR).replace("\\", "/")

_PERIOD_NAMES = {
    "T1": "Trimestre 1", "T2": "Trimestre 2", "T3": "Trimestre 3",
    "S1": "Semestre 1", "S2": "Semestre 2",
}


# ── Helpers ─────────────────────────────────────────────────────


def _resolve_uploaded_logo(logo_url: str | None) -> tuple[str | None, str | None]:
    """Resolve a school logo URL to a local path, strictly inside uploads/.

    Antidote au LFI : le logo n'est lisible que s'il vit réellement sous
    le dossier uploads/ de l'application. Retourne (url, abs_path).
    """
    if not logo_url:
        return None, None

    # Dossier uploads persistant (UPLOAD_DIR configurable — ex. /app/data/uploads)
    uploads_root = get_settings().upload_path.resolve()
    rel = logo_url.replace("\\", "/").lstrip("/")
    # Les URLs historiques contiennent le préfixe uploads/ ou static/uploads/ :
    # on le retire pour obtenir le chemin relatif au dossier racine uploads.
    for prefix in ("static/uploads/", "uploads/"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    try:
        candidate = (uploads_root / rel).resolve()
    except (ValueError, OSError):
        return None, None

    if candidate == uploads_root or not candidate.is_relative_to(uploads_root):
        return None, None
    if not os.path.isfile(candidate):
        return None, None

    return logo_url, str(candidate)

def _number_to_french_words(n: float) -> str:
    """Convert a number to French words for receipt amount."""
    if n == 0:
        return "Zéro"
    ones = ["", "un", "deux", "trois", "quatre", "cinq", "six", "sept",
            "huit", "neuf", "dix", "onze", "douze", "treize", "quatorze",
            "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
    tens = ["", "", "vingt", "trente", "quarante", "cinquante",
            "soixante", "soixante-dix", "quatre-vingts", "quatre-vingt-dix"]
    if n < 20:
        return ones[int(n)].capitalize()
    if n < 100:
        t = int(n) // 10
        o = int(n) % 10
        return f"{tens[t]}{'-' + ones[o] if o else ''}".capitalize()
    if n < 1000:
        h = int(n) // 100
        rest = int(n) % 100
        prefix = f"{ones[h]} cent" if h > 1 else "cent"
        return f"{prefix}{' ' + _number_to_french_words(rest).lower() if rest else ''}".capitalize()
    if n < 1_000_000:
        m = int(n) // 1000
        rest = int(n) % 1000
        prefix = _number_to_french_words(m).lower() + " mille"
        return f"{prefix}{' ' + _number_to_french_words(rest).lower() if rest else ''}".capitalize()
    return f"{int(n):,}".replace(",", " ") + " francs CFA"


def _mention_from_average(avg: float) -> str:
    """Get mention based on configurable thresholds (default)."""
    if avg >= 16:
        return "Félicitations"
    elif avg >= 14:
        return "Encouragements"
    elif avg >= 12:
        return "Tableau d'honneur"
    elif avg >= 10:
        return "Passable"
    else:
        return "Avertissement"


def _mention_color(mention: str) -> str:
    """Return CSS color for a mention."""
    colors = {
        "Félicitations": "#1b5e20",
        "Encouragements": "#2e7d32",
        "Tableau d'honneur": "#0E5C3F",
        "Passable": "#f57f17",
        "Avertissement": "#c62828",
    }
    return colors.get(mention, "#333")


def _mention_bg(mention: str) -> str:
    """Return CSS background for a mention."""
    colors = {
        "Félicitations": "#e8f5e9",
        "Encouragements": "#e8f5e9",
        "Tableau d'honneur": "#f0f8f0",
        "Passable": "#fff8e1",
        "Avertissement": "#fce4ec",
    }
    return colors.get(mention, "#f5f5f5")


def _bulletin_grade_columns(grades: dict) -> tuple[float | None, float | None, float | None]:
    """Extract (d1, d2, comp) from a snapshot grades dict (best-effort display).

    Les colonnes Devoir 1 / Devoir 2 / Compo. sont purement indicatives :
    la moyenne affichée provient toujours du snapshot (champ "average").
    """
    d1 = d2 = comp = None
    for key, val in (grades or {}).items():
        k = (key or "").lower()
        if "composition" in k or "compo" in k or k in ("controle", "examen"):
            comp = val
        elif "devoir2" in k:
            d2 = val
        elif "devoir1" in k or k == "devoir":
            d1 = val
    return d1, d2, comp


def _render_bulletin_pdf(school: School, school_color: str, values: dict) -> bytes:
    """Render the bulletin template + pisa from a fully resolved values dict."""
    qr_data = values.pop("_qr_data")
    qr_path = _generate_qr_image(qr_data).replace("\\", "/")
    school_logo_url, school_logo_path = _resolve_uploaded_logo(school.logo_url)
    school_logo_path = (school_logo_path or "").replace("\\", "/")

    template = _jinja_env.get_template("bulletin.html")
    html_content = template.render(
        school_name=school.name,
        school_initial=school.short_name or school.name[:2].upper(),
        school_address=school.address or "",
        school_city=school.city or "",
        school_country=school.country or "",
        school_phone=school.phone or "",
        school_motto=school.motto or "",
        school_logo_url=school_logo_url,
        school_logo_path=school_logo_path or "",
        school_color=school_color,
        qr_path=qr_path,
        **values,
    )
    buf = BytesIO()
    pisa.CreatePDF(html_content, dest=buf)
    pdf_bytes = buf.getvalue()

    try:
        os.remove(qr_path)
    except OSError:
        pass

    return pdf_bytes


def _generate_qr_image(data: str, size: int = 150) -> str:
    """Generate a QR code PNG and return its temp file path."""
    qr = qrcode.QRCode(version=1, box_size=size // 30, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    tmp_path = os.path.join(
        os.path.dirname(__file__), f"_tmp_qr_{secrets.token_hex(4)}.png"
    )
    with open(tmp_path, "wb") as f:
        f.write(buf.getvalue())
    return tmp_path


def _generate_receipt_number(school_id: int, payment_id: int) -> str:
    """Generate a unique receipt number scoped to the school.

    Format: REC-{school_short_id}-{payment_id:06d}
    The school_short_id is a 4-char hex derived from school_id,
    ensuring uniqueness per school without revealing total volume.
    """
    school_hash = hashlib.md5(str(school_id).encode()).hexdigest()[:4].upper()
    return f"REC-{school_hash}-{payment_id:06d}"


def _generate_receipt_token(school_id: int, payment_id: int) -> str:
    """Generate HMAC-signed token for receipt verification QR."""
    return receipt_signature(school_id, payment_id)


# ── Bulletin PDF ────────────────────────────────────────────────

async def generate_bulletin_pdf(
    db: AsyncSession,
    student_id: int,
    class_id: int,
    period: str,
    academic_year: str = "2025-2026",
    school_color: str = "#0E5C3F",
) -> bytes:
    """Generate a bulletin PDF for a student.

    Returns PDF as bytes.
    """
    # ── Load entities ───────────────────────────────────────────
    student = (await db.execute(
        select(Student).where(Student.id == student_id)
    )).scalar_one_or_none()
    if not student:
        raise ValueError("Student not found")

    school = (await db.execute(
        select(School).where(School.id == student.school_id)
    )).scalar_one_or_none()
    if not school:
        raise ValueError("School not found")

    cls = (await db.execute(
        select(Class).where(Class.id == class_id, Class.school_id == school.id)
    )).scalar_one_or_none()

    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()

    # ── Load evaluations for this class/period ──────────────────
    evaluations = (await db.execute(
        select(Evaluation).where(
            Evaluation.class_id == class_id,
            Evaluation.period == period,
            Evaluation.academic_year == academic_year,
            Evaluation.school_id == school.id,
        )
    )).scalars().all()

    eval_ids = [e.id for e in evaluations]
    if not eval_ids:
        raise ValueError(f"No evaluations found for class {class_id}, period {period}")

    # Load grades for this student
    all_grades = (await db.execute(
        select(Grade).where(
            Grade.student_id == student_id,
            Grade.evaluation_id.in_(eval_ids),
        )
    )).scalars().all()

    eval_lookup = {e.id: e for e in evaluations}

    # Load subject names
    subject_names: dict[int, str] = {}
    for e in evaluations:
        if e.subject_id not in subject_names:
            subj = (await db.execute(
                select(Subject).where(Subject.id == e.subject_id)
            )).scalar_one_or_none()
            subject_names[e.subject_id] = subj.name if subj else "?"

    # Load class-subject coefficients
    cs_results = (await db.execute(
        select(ClassSubject).where(
            ClassSubject.class_id == class_id,
            ClassSubject.school_id == school.id,
        )
    )).scalars().all()
    cs_coeffs = {cs.subject_id: cs.coefficient for cs in cs_results}

    # ── Build subject data ──────────────────────────────────────
    subject_data: dict[int, dict] = {}
    for e in evaluations:
        sid = e.subject_id
        if sid not in subject_data:
            subject_data[sid] = {
                "name": subject_names.get(sid, "?"),
                "coefficient": cs_coeffs.get(sid, e.coefficient),
                "d1": None, "d2": None, "comp": None,
            }
        # Map assessment type to column
        atype = e.assessment_type
        if "devoir1" in atype or atype == "devoir1":
            subject_data[sid]["d1"] = atype
        elif "devoir2" in atype or atype == "devoir2":
            subject_data[sid]["d2"] = atype
        elif "composition" in atype or atype == "composition":
            subject_data[sid]["comp"] = atype

    for g in all_grades:
        e = eval_lookup.get(g.evaluation_id)
        if e and e.subject_id in subject_data:
            atype = e.assessment_type
            if "devoir1" in atype or atype == "devoir1":
                subject_data[e.subject_id]["d1"] = g.grade
            elif "devoir2" in atype or atype == "devoir2":
                subject_data[e.subject_id]["d2"] = g.grade
            elif "composition" in atype or atype == "composition":
                subject_data[e.subject_id]["comp"] = g.grade

    # ── Calculate averages ──────────────────────────────────────
    subjects_list = []
    total_pts = 0.0
    total_cfs = 0

    for sid, sd in subject_data.items():
        d1 = sd["d1"] if isinstance(sd["d1"], (int, float)) else None
        d2 = sd["d2"] if isinstance(sd["d2"], (int, float)) else None
        comp = sd["comp"] if isinstance(sd["comp"], (int, float)) else None
        coef = sd["coefficient"]

        # Calculate subject average
        grades = [g for g in [d1, d2, comp] if g is not None]
        if len(grades) == 3:
            avg = (d1 + d2 + 2 * comp) / 4
        elif len(grades) == 2 and comp is not None:
            avg = (d1 or 0 + d2 or 0 + 2 * comp) / 4
        elif comp is not None:
            avg = comp
        elif d1 is not None and d2 is not None:
            avg = (d1 + d2) / 2
        elif d1 is not None:
            avg = d1
        elif d2 is not None:
            avg = d2
        else:
            avg = None

        avg_rounded = round(avg, 2) if avg is not None else None

        subjects_list.append({
            "name": sd["name"],
            "coefficient": coef,
            "d1": d1,
            "d2": d2,
            "comp": comp,
            "average": avg_rounded,
            "class_average": None,  # Filled below
            "rank": None,           # Filled below
            "appreciation": get_mention(avg_rounded) if avg_rounded is not None else "—",
        })

    # Use shared calculator (single source of truth)
    overall_average = calculate_overall_average(subjects_list)
    total_coeff = sum(s["coefficient"] for s in subjects_list)

    # ── Rankings across class ───────────────────────────────────
    all_student_ids = [
        e.student_id for e in (await db.execute(
            select(Enrollment).where(
                Enrollment.class_id == class_id,
                Enrollment.status == "active",
            )
        )).scalars().all()
    ]

    all_student_avgs = []
    for sid in all_student_ids:
        sg = (await db.execute(
            select(Grade).where(
                Grade.student_id == sid,
                Grade.evaluation_id.in_(eval_ids),
            )
        )).scalars().all() if eval_ids else []

        sg_evals = {eval_lookup[g.evaluation_id]: g for g in sg if g.evaluation_id in eval_lookup}
        st_pts = 0.0
        st_cfs = 0
        for ev, gr in sg_evals.items():
            st_pts += (gr.grade or 0) * ev.coefficient
            st_cfs += ev.coefficient
        st_avg = round(st_pts / st_cfs, 2) if st_cfs > 0 else 0.0
        all_student_avgs.append({"id": sid, "average": st_avg})

    all_student_avgs.sort(key=lambda x: x["average"], reverse=True)
    effectif = len(all_student_avgs)

    # Assign ranks (with ex-aequo handling)
    rank_map = {}
    current_rank = 1
    for i, sa in enumerate(all_student_avgs):
        if i > 0 and sa["average"] < all_student_avgs[i - 1]["average"]:
            current_rank = i + 1
        rank_map[sa["id"]] = current_rank

    student_rank = rank_map.get(student_id, effectif)

    # Class average per subject (for display)
    all_grades_by_eval: dict[int, list[float]] = {}
    if eval_ids:
        all_g = (await db.execute(
            select(Grade).where(Grade.evaluation_id.in_(eval_ids))
        )).scalars().all()
        for g in all_g:
            all_grades_by_eval.setdefault(g.evaluation_id, []).append(g.grade or 0)

    for s in subjects_list:
        # Find eval IDs for this subject
        subj_eval_ids = [e.id for e in evaluations if subject_names.get(e.subject_id) == s["name"]]
        subj_grades = []
        for eid in subj_eval_ids:
            subj_grades.extend(all_grades_by_eval.get(eid, []))
        s["class_average"] = round(sum(subj_grades) / len(subj_grades), 2) if subj_grades else None

    # Sort subjects by coefficient desc, then name
    subjects_list.sort(key=lambda x: (-x["coefficient"], x["name"]))

    class_average = round(sum(sa["average"] for sa in all_student_avgs) / effectif, 2) if effectif > 0 else 0.0
    best_average = all_student_avgs[0]["average"] if all_student_avgs else 0.0

    # ── Discipline ──────────────────────────────────────────────
    total_deductions = (await db.execute(
        select(func.coalesce(func.sum(DisciplinaryRecord.points_deducted), 0.0)).where(
            DisciplinaryRecord.school_id == school.id,
            DisciplinaryRecord.student_id == student_id,
            DisciplinaryRecord.period == period,
            DisciplinaryRecord.academic_year == academic_year,
            DisciplinaryRecord.status == "active",
        )
    )).scalar() or 0.0

    # Bulletin sans aucune note -> pas de mention/decision automatique trompeuse
    if overall_average is None:
        display_average = None
        conduct_score = None
        discipline_line = None
        mention = None
        decision = None
    else:
        discipline = apply_discipline(
            overall_average, school.discipline_mode, total_deductions
        )
        display_average = discipline["display_average"]
        conduct_score = discipline["conduct_score"]
        discipline_line = discipline["discipline_line"]

        # -- Mention --
        mention = get_mention(display_average)

        # -- Decision (last period) --
        is_trimestre = period.startswith("T")
        periods_list = ["T1", "T2", "T3"] if is_trimestre else ["S1", "S2"]
        is_last_period = period == periods_list[-1]
        decision = None
        if is_last_period:
            decision = "Admis" if display_average >= 10 else "Redouble"

    # -- Period name --
    period_name = _PERIOD_NAMES.get(period, period)

    # ── QR signé (anti-fraude) ─────────────────────────────────
    _cfg = get_settings()
    signature = bulletin_signature(
        school.id, student_id, class_id, period, academic_year,
        display_average or 0.0, student_rank, effectif,
    )
    verification_url = (
        f"{_cfg.SERVER_URL}/api/verify/bulletin/"
        f"{student_id}/{class_id}/{period}/{academic_year}/{signature}"
    )
    qr_data = verification_url

    # ── Render + PDF (helper commun, aucune valeur n'y est recalculée) ──
    # Appréciation générale du conseil (snapshot si disponible, sinon rien)
    council_comment = None
    try:
        import json as _json
        _snap = (await db.execute(
            select(Bulletin).where(
                Bulletin.school_id == school.id,
                Bulletin.student_id == student_id,
                Bulletin.period == period,
                Bulletin.academic_year == academic_year,
            )
        )).scalar_one_or_none()
        if _snap and _snap.data_json:
            council_comment = (_json.loads(_snap.data_json) or {}).get("general_appreciation")
    except Exception:
        council_comment = None

    return _render_bulletin_pdf(school, school_color, {
        "academic_year": academic_year,
        "period": period,
        "period_name": period_name,
        "class_name": cls.name if cls else "—",
        "effectif": effectif,
        "student_first_name": student.first_name,
        "student_last_name": student.last_name,
        "matricule": student.matricule or f"STU-{student.id:05d}",
        "birth_date": student.birth_date.strftime("%d/%m/%Y") if student.birth_date else None,
        "is_repeater": enrollment.is_repeater if enrollment else False,
        "subjects": subjects_list,
        "total_coeff": total_coeff,
        "overall_average": overall_average,
        "display_average": display_average,
        "rank": student_rank,
        "class_average": class_average,
        "best_average": best_average,
        "mention": mention,
        "mention_color": get_mention_color(mention),
        "mention_bg": get_mention_bg(mention),
        "decision": decision,
        "discipline_mode": school.discipline_mode,
        "discipline_line": discipline_line,
        "conduct_score": conduct_score,
        "conduct_appreciation": (
            conduct_appreciation(conduct_score) if conduct_score is not None else None
        ),
        "total_deductions": total_deductions,
        "generated_at": datetime.now().strftime("%d/%m/%Y à %H:%M"),
        "verification_url": verification_url,
        "observations": council_comment or "",
        "_qr_data": qr_data,
    })


# Keep QR temp files alive until PDF is generated
_KeepQRTempFiles = True


async def generate_bulletin_from_snapshot(
    db: AsyncSession,
    bulletin,
    school_color: str = "#0E5C3F",
) -> bytes:
    """Génère le PDF de bulletin EXCLUSIVEMENT depuis le snapshot figé data_json.

    Aucune moyenne n'est recalculée ici : les valeurs affichées sont celles
    validées dans l'application (snapshot). Les anciens bulletins qui ne
    contiennent pas encore les nouveaux champs (discipline, mention, décision,
    moyennes de classe) sont régénérés via le calcul canonique SANS rien
    persister en base.
    """
    b = bulletin

    student = (await db.execute(
        select(Student).where(Student.id == b.student_id)
    )).scalar_one_or_none()
    if not student:
        raise ValueError("Student not found")

    school = (await db.execute(
        select(School).where(School.id == b.school_id)
    )).scalar_one_or_none()
    if not school:
        raise ValueError("School not found")

    cls = (await db.execute(
        select(Class).where(Class.id == b.class_id, Class.school_id == school.id)
    )).scalar_one_or_none()

    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == b.student_id,
            Enrollment.class_id == b.class_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()

    try:
        data = json.loads(b.data_json or "{}")
    except (ValueError, TypeError):
        data = {}

    required = ("subjects", "overall_average", "display_average", "discipline_mode", "mention")
    if not all(k in data for k in required):
        # Snapshot incomplet (bulletin créé avant l'enrichissement) :
        # régénère le snapshot canonique sans rien écrire en base.
        from app.services.report_card_service import build_snapshot, compute_class_results
        computed = await compute_class_results(
            db, b.school_id, b.class_id, b.period, b.academic_year
        )
        data = build_snapshot(computed, b.student_id)

    subjects_list = []
    for s in data.get("subjects", []):
        d1, d2, comp = _bulletin_grade_columns(s.get("grades"))
        subjects_list.append({
            "name": s.get("name", "?"),
            "coefficient": s.get("coefficient") or 1,
            "d1": d1,
            "d2": d2,
            "comp": comp,
            "average": s.get("average"),
            "class_average": s.get("class_average"),
            "rank": s.get("rank"),
            "appreciation": s.get("appreciation") or "—",
        })
    subjects_list.sort(key=lambda x: (-x["coefficient"], x["name"]))

    overall_average = data.get("overall_average")
    if not subjects_list and overall_average is None:
        raise ValueError("Bulletin vide : aucune donnée figée disponible")

    # Bulletin sans notes -> pas de mention/décision automatique trompeuse
    if overall_average is None:
        display_average = None
        mention = None
        decision = None
        class_average = None
        best_average = None
    else:
        display_average = data.get("display_average", overall_average)
        class_average = data.get("class_average")
        best_average = data.get("class_best")
        mention = data.get("mention") or get_mention(display_average)
        decision = data.get("decision")
    rank = data.get("rank") or b.rank
    effectif = data.get("total_students") or b.total_students or 0
    discipline_mode = data.get("discipline_mode", school.discipline_mode or "conduct")
    total_deductions = data.get("total_deductions", 0)
    conduct_score = data.get("conduct_score")
    discipline_line = data.get("discipline_line")

    # ── QR signé (anti-fraude, depuis les valeurs figées) ───────
    _cfg = get_settings()
    signature = bulletin_signature(
        school.id, b.student_id, b.class_id, b.period, b.academic_year,
        display_average or 0.0, rank or 0, effectif,
    )
    verification_url = (
        f"{_cfg.SERVER_URL}/api/verify/bulletin/"
        f"{b.student_id}/{b.class_id}/{b.period}/{b.academic_year}/{signature}"
    )
    qr_data = verification_url

    return _render_bulletin_pdf(school, school_color, {
        "academic_year": b.academic_year,
        "period": b.period,
        "period_name": data.get("period_label") or _PERIOD_NAMES.get(b.period, b.period),
        "class_name": cls.name if cls else "—",
        "effectif": effectif,
        "student_first_name": student.first_name,
        "student_last_name": student.last_name,
        "matricule": student.matricule or f"STU-{student.id:05d}",
        "birth_date": student.birth_date.strftime("%d/%m/%Y") if student.birth_date else None,
        "is_repeater": enrollment.is_repeater if enrollment else False,
        "subjects": subjects_list,
        "total_coeff": sum(s["coefficient"] for s in subjects_list),
        "overall_average": overall_average,
        "display_average": display_average,
        "rank": rank,
        "class_average": class_average,
        "best_average": best_average,
        "mention": mention,
        "mention_color": get_mention_color(mention),
        "mention_bg": get_mention_bg(mention),
        "decision": decision,
        "discipline_mode": discipline_mode,
        "discipline_line": discipline_line,
        "conduct_score": conduct_score,
        "conduct_appreciation": (
            conduct_appreciation(conduct_score) if conduct_score is not None else None
        ),
        "total_deductions": total_deductions,
        "generated_at": datetime.now().strftime("%d/%m/%Y à %H:%M"),
        "verification_url": verification_url,
        "observations": data.get("general_appreciation") or "",
        "_qr_data": qr_data,
    })


# ── Receipt PDF ─────────────────────────────────────────────────

async def generate_receipt_pdf(
    db: AsyncSession,
    payment_id: int,
    school_color: str = "#0E5C3F",
) -> bytes:
    """Generate a payment receipt PDF.

    Returns PDF as bytes.
    """
    # ── Load payment ────────────────────────────────────────────
    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id)
    )).scalar_one_or_none()
    if not payment:
        raise ValueError("Payment not found")

    school = (await db.execute(
        select(School).where(School.id == payment.school_id)
    )).scalar_one_or_none()
    if not school:
        raise ValueError("School not found")

    student = (await db.execute(
        select(Student).where(Student.id == payment.student_id)
    )).scalar_one_or_none()

    # ── Load obligation (motif) ─────────────────────────────────
    obligation = None
    if payment.obligation_id:
        obligation = (await db.execute(
            select(FeeObligation).where(FeeObligation.id == payment.obligation_id)
        )).scalar_one_or_none()

    motif = obligation.name if obligation else (payment.notes or "Frais scolaire")
    period = obligation.period if obligation else "—"

    # ── Load class name ─────────────────────────────────────────
    class_name = "—"
    if student:
        enrollment = (await db.execute(
            select(Enrollment).where(
                Enrollment.student_id == student.id,
                Enrollment.status == "active",
            )
        )).scalar_one_or_none()
        if enrollment:
            cls = (await db.execute(
                select(Class).where(Class.id == enrollment.class_id)
            )).scalar_one_or_none()
            class_name = cls.name if cls else "—"

    # ── Receipt number (scoped to school) ───────────────────────
    receipt_number = _generate_receipt_number(school.id, payment.id)

    # ── Payment method label ────────────────────────────────────
    method_labels = {
        "cash": "Espèces",
        "mobile_money": f"Mobile Money ({payment.mobile_operator or ''})",
        "bank": "Virement bancaire",
        "other": "Autre",
    }
    payment_method = method_labels.get(payment.payment_method, payment.payment_method)

    # ── QR code for verification ────────────────────────────────
    token = payment.receipt_qr_token or _generate_receipt_token(school.id, payment.id)
    _cfg = get_settings()
    verification_url = f"{_cfg.SERVER_URL}/api/verify/receipt/{payment.id}/{token}"
    qr_path = _generate_qr_image(verification_url).replace("\\", "/")

    # ── School logo ─────────────────────────────────────────────
    school_logo_url, school_logo_path = _resolve_uploaded_logo(school.logo_url)
    school_logo_path = (school_logo_path or "").replace("\\", "/")

    # ── Remaining balance & Cashier ─────────────────────────────
    remaining_balance = 0.0
    if payment.obligation_id and student:
        from app.services.fee_service import paid_by_student
        total_paid_for_ob = await paid_by_student(db, school.id, student.id, payment.obligation_id)
        if obligation:
            remaining_balance = max(obligation.amount - total_paid_for_ob, 0.0)

    cashier_name = "Le Service Comptable"
    if payment.recorded_by:
        from app.models.user import User
        cashier = (await db.execute(select(User).where(User.id == payment.recorded_by))).scalar_one_or_none()
        if cashier:
            cashier_name = f"{cashier.first_name} {cashier.last_name}".strip() or cashier.email

    # ── Render template ─────────────────────────────────────────
    template = _jinja_env.get_template("receipt.html")
    html_content = template.render(
        school_name=school.name,
        school_initial=school.short_name or school.name[:2].upper(),
        school_address=school.address or "",
        school_city=school.city or "",
        school_country=school.country or "",
        school_phone=school.phone or "",
        school_logo_url=school_logo_url,
        school_logo_path=school_logo_path or "",
        school_color=school_color,
        receipt_number=receipt_number,
        student_first_name=student.first_name if student else "—",
        student_last_name=student.last_name if student else "—",
        matricule=student.matricule if student and student.matricule else f"STU-{student.id:05d}" if student else "—",
        class_name=class_name,
        payment_date=payment.paid_at.strftime("%d/%m/%Y à %H:%M") if payment.paid_at else "—",
        payment_method=payment_method,
        payment_motif=motif,
        payment_period=period,
        transaction_ref=payment.transaction_id or "",
        amount=payment.amount,
        remaining_balance=remaining_balance,
        cashier_name=cashier_name,
        amount_in_words=_number_to_french_words(payment.amount) + " francs CFA",
        academic_year=obligation.academic_year if obligation else "—",
        verification_url=verification_url,
        qr_path=qr_path,
        generated_at=datetime.now().strftime("%d/%m/%Y à %H:%M"),
    )

    # ── Generate PDF ────────────────────────────────────────────
    buf = BytesIO()
    pisa.CreatePDF(html_content, dest=buf)
    pdf_bytes = buf.getvalue()

    # Cleanup
    try:
        os.remove(qr_path)
    except OSError:
        pass

    return pdf_bytes


# ── Batch bulletin generation ───────────────────────────────────

async def generate_bulletins_for_class(
    db: AsyncSession,
    class_id: int,
    period: str,
    academic_year: str = "2025-2026",
    school_color: str = "#0E5C3F",
) -> list[dict]:
    """Generate bulletins for all students in a class.

    Returns a list of {"student_id": int, "student_name": str, "pdf": bytes, "error": str|None}.
    """
    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
    )).scalars().all()

    results = []
    for enrollment in enrollments:
        student = (await db.execute(
            select(Student).where(Student.id == enrollment.student_id)
        )).scalar_one_or_none()
        if not student:
            results.append({
                "student_id": enrollment.student_id,
                "student_name": "Inconnu",
                "pdf": None,
                "error": "Student not found",
            })
            continue

        try:
            pdf = await generate_bulletin_pdf(
                db, student.id, class_id, period, academic_year, school_color
            )
            results.append({
                "student_id": student.id,
                "student_name": f"{student.first_name} {student.last_name}",
                "pdf": pdf,
                "error": None,
            })
        except Exception as e:
            results.append({
                "student_id": student.id,
                "student_name": f"{student.first_name} {student.last_name}",
                "pdf": None,
                "error": str(e),
            })

    return results
