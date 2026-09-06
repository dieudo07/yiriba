"""Yiriba SaaS — Endpoints publics de vérification des documents via QR.

Accessibles sans authentification (le QR est imprimé sur le document).
La signature HMAC du QR est recalculée à partir de la base : si elle ne
correspond pas, le document est considéré comme non authentique.

Routes :
- GET /api/verify/bulletin/{student_id}/{class_id}/{period}/{academic_year}[/{signature}]
- GET /api/verify/receipt/{payment_id}/{token}
"""

import html
import json

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.bulletin import Bulletin
from app.models.class_ import Class
from app.models.payment import Payment
from app.models.school import School
from app.models.student import Student
from app.services.grade_calculator import get_mention
from app.services.report_card_service import period_label
from app.services.verification_service import (
    verify_bulletin_signature,
    verify_receipt_signature,
)

router = APIRouter(prefix="/api/verify", tags=["verify"])


def _page(
    title: str,
    ok: bool,
    badge: str,
    subtitle: str,
    rows: list[tuple[str, str]],
) -> HTMLResponse:
    """Page de vérification minimaliste, autonome (CSS inline)."""
    color = "#2e7d32" if ok else "#c62828"
    bg = "#e8f5e9" if ok else "#fce4ec"
    style_bg = ("margin:0;font-family:Helvetica,Arial,sans-serif;background:#f4f6f4;"
                "color:#222;display:flex;justify-content:center;padding:24px")
    style_card = ("max-width:480px;width:100%;background:white;border-radius:12px;"
                  "box-shadow:0 2px 12px rgba(0,0,0,.08);overflow:hidden")
    rows_html = "".join(
        f"<tr><td style='padding:6px 12px;text-align:left;color:#666;width:45%'>{k}</td>"
        f"<td style='padding:6px 12px;text-align:right;font-weight:600'>{v}</td></tr>"
        for k, v in rows
    )
    style_band = ("background:{bg};color:#333;text-align:center;padding:10px;"
                  "font-size:13px;font-weight:600")
    body = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title></head>
<body style="{style_bg}">
<div style="{style_card}">
  <div style="background:{color};color:white;padding:20px;text-align:center">
    <div style="font-size:26px;margin-bottom:6px">{badge}</div>
    <div style="font-size:16px;font-weight:700">{html.escape(subtitle)}</div>
  </div>
  <div style="{style_band}">
    {html.escape(title)}
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:13px">
    {rows_html}
  </table>
  <div style="padding:12px;text-align:center;color:#999;font-size:11px;border-top:1px solid #eee">
    Document généré et vérifié par YIRIBA
  </div>
</div></body></html>"""
    return HTMLResponse(content=body)


@router.get("/bulletin/{student_id}/{class_id}/{period}/{academic_year}/{signature}",
            response_class=HTMLResponse)
@router.get("/bulletin/{student_id}/{class_id}/{period}/{academic_year}",
            response_class=HTMLResponse)
async def verify_bulletin(
    student_id: int,
    class_id: int,
    period: str,
    academic_year: str,
    signature: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Vérifie l'authenticité d'un bulletin à partir des valeurs figées en base."""
    student = (await db.execute(
        select(Student).where(Student.id == student_id)
    )).scalar_one_or_none()
    if not student:
        return _page(
            "Document introuvable", False, "✖",
            "Aucun bulletin correspondant",
            [("Référence", f"élève {student_id}")],
        )
    school = (await db.execute(
        select(School).where(School.id == student.school_id)
    )).scalar_one_or_none()
    bulletin = (await db.execute(
        select(Bulletin).where(
            Bulletin.student_id == student_id,
            Bulletin.class_id == class_id,
            Bulletin.period == period,
            Bulletin.academic_year == academic_year,
            Bulletin.school_id == student.school_id,
        )
    )).scalar_one_or_none()
    cls = (await db.execute(
        select(Class).where(Class.id == class_id)
    )).scalar_one_or_none()
    if not bulletin:
        return _page(
            "Document introuvable", False, "✖",
            "Aucun bulletin généré pour cette référence",
            [("Élève", f"{student.first_name} {student.last_name}")],
        )

    try:
        snapshot = json.loads(bulletin.data_json or "{}")
    except (ValueError, TypeError):
        snapshot = {}
    display_average = snapshot.get("display_average") or bulletin.overall_average or 0.0
    rank = snapshot.get("rank") or bulletin.rank or 1
    effectif = snapshot.get("total_students") or bulletin.total_students or 0

    authenticated = False
    legacy = False
    if signature:
        authenticated = verify_bulletin_signature(
            signature, school.id, student_id, class_id, period, academic_year,
            float(display_average), int(rank), int(effectif),
        )
    else:
        legacy = True  # ancien format de QR, pas de signature

    page_title = "Document authentique" if authenticated else "Signature invalide"
    badge = "✓" if authenticated else ("!" if legacy else "✖")
    subtitle = (
        "Le bulletin correspond aux valeurs validées par l'établissement"
        if authenticated
        else "Bulletin non signé (ancien format, sans QR sécurisé)"
        if legacy
        else "Le document ne correspond pas aux données officielles"
    )
    rows = [
        ("Établissement", school.name if school else "—"),
        ("Élève", f"{student.first_name} {student.last_name}"),
        ("Matricule", student.matricule or "—"),
        ("Classe", cls.name if cls else "—"),
        ("Période", period_label(period, cls.period_type if cls else "trimestre")),
        ("Année scolaire", academic_year),
        ("Moyenne générale", f"{display_average:.2f}/20"),
        ("Rang", f"{rank}/{effectif}"),
        ("Mention", get_mention(display_average)),
        ("Statut", bulletin.status),
    ]
    return _page(page_title, authenticated or legacy, badge, subtitle, rows)


@router.get("/receipt/{payment_id}/{token}", response_class=HTMLResponse)
async def verify_receipt(
    payment_id: int,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Vérifie l'authenticité d'un reçu de paiement."""
    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id)
    )).scalar_one_or_none()
    if not payment:
        return _page(
            "Reçu introuvable", False, "✖",
            "Aucun reçu correspondant",
            [("Référence", f"paiement #{payment_id}")],
        )
    school = (await db.execute(
        select(School).where(School.id == payment.school_id)
    )).scalar_one_or_none()
    student = (await db.execute(
        select(Student).where(Student.id == payment.student_id)
    )).scalar_one_or_none()

    authenticated = verify_receipt_signature(token, payment.school_id, payment.id)
    method_labels = {
        "cash": "Espèces",
        "mobile_money": "Mobile Money",
        "bank": "Virement bancaire",
        "other": "Autre",
    }
    rows = [
        ("Établissement", school.name if school else "—"),
        ("Élève", f"{student.first_name} {student.last_name}" if student else "—"),
        ("Montant", f"{int(payment.amount):,} FCFA".replace(",", " ")),
        ("Mode de paiement", method_labels.get(payment.payment_method, payment.payment_method)),
        ("Motif", payment.notes or "Frais scolaire"),
        ("Date", payment.paid_at.strftime("%d/%m/%Y à %H:%M") if payment.paid_at else "—"),
        ("Référence", payment.transaction_id or "—"),
    ]
    return _page(
        "Reçu authentique" if authenticated else "Reçu non authentique",
        authenticated,
        "✓" if authenticated else "✖",
        "Le reçu correspond au paiement enregistré" if authenticated
        else "Ce reçu ne correspond pas aux données officielles",
        rows,
    )
