"""Yiriba SaaS — Payment routes: obligations, payments, Mobile Money, receipts."""

import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.services.subscription_service import require_write_access
from fastapi.responses import Response
from app.models.class_ import Class, Enrollment
from app.models.payment import FeeInstallment, FeeObligation, Payment, PaymentStatus
from app.models.student import Student
from app.models.user import User

router = APIRouter(prefix="/api/payments", tags=["payments"])


# ── Schemas ───────────────────────────────────────────────────────


class InstallmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0)
    due_date: str | None = None
    installment_number: int = 1
    notes: str | None = None


class ObligationCreate(BaseModel):
    class_id: int | None = None
    student_id: int | None = None
    level: str | None = None
    name: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0, le=10_000_000)
    category: str = Field(default="scolarite")  # scolarite, inscription, cantine, transport, activites, examens, autre
    period: str = Field(default="annuel", max_length=20)  # T1, T2, T3, S1, S2, annuel
    academic_year: str = Field(default="2025-2026", max_length=10)
    due_date: str | None = None
    description: str | None = None
    is_mandatory: bool = True
    installments: list[InstallmentCreate] = Field(default_factory=list)


class PaymentCreate(BaseModel):
    student_id: int
    obligation_id: int | None = None
    installment_id: int | None = None
    amount: float = Field(..., gt=0)
    payment_method: str = Field(..., pattern="^(cash|mobile_money|bank|cheque|check|other)$")
    transaction_id: str | None = None
    mobile_operator: str | None = Field(default=None, pattern="^(mtn|orange|wave|moov)$")
    mobile_number: str | None = Field(default=None, max_length=30)
    notes: str | None = None
    allow_overpay: bool = False


class PaymentCorrectRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)
    amount: float | None = Field(default=None, gt=0)
    payment_method: str | None = Field(default=None, pattern="^(cash|mobile_money|bank|cheque|check|other)$")
    notes: str | None = None
    allow_overpay: bool = False


class GenerateObligationsRequest(BaseModel):
    class_id: int | None = None
    student_id: int | None = None
    academic_year: str | None = None


class CancelRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=200)


class ReminderRequest(BaseModel):
    student_ids: list[int] = Field(default_factory=list)


# ── Fee Obligations ───────────────────────────────────────────────


@router.get("/obligations")
async def list_obligations(
    class_id: int | None = None,
    student_id: int | None = None,
    category: str | None = None,
    period: str | None = None,
    academic_year: str | None = None,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(FeeObligation).where(FeeObligation.school_id == school_id, FeeObligation.is_active == True)  # noqa: E712
    if class_id:
        query = query.where(FeeObligation.class_id == class_id)
    if student_id:
        query = query.where(FeeObligation.student_id == student_id)
    if category:
        query = query.where(FeeObligation.category == category)
    if period:
        query = query.where(FeeObligation.period == period)
    if academic_year:
        query = query.where(FeeObligation.academic_year == academic_year)

    result = await db.execute(query.order_by(FeeObligation.id.desc()))
    obligations = result.scalars().all()
    return {
        "obligations": [
            {
                "id": o.id,
                "class_id": o.class_id,
                "student_id": o.student_id,
                "level": o.level,
                "name": o.name,
                "category": o.category,
                "amount": o.amount,
                "period": o.period,
                "academic_year": o.academic_year,
                "due_date": str(o.due_date) if o.due_date else None,
                "is_mandatory": o.is_mandatory,
                "description": o.description,
            }
            for o in obligations
        ]
    }


@router.post("/obligations", status_code=201)
async def create_obligation(
    data: ObligationCreate,
    user: User = Depends(require_permission("payment.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Vérification multi-tenant de la classe si spécifiée
    if data.class_id:
        cls = (await db.execute(
            select(Class.id).where(Class.id == data.class_id, Class.school_id == school_id)
        )).scalar_one_or_none()
        if not cls:
            raise HTTPException(status_code=404, detail="Classe introuvable")

    # Vérification multi-tenant de l'élève si spécifié
    if data.student_id:
        stu = (await db.execute(
            select(Student.id).where(Student.id == data.student_id, Student.school_id == school_id)
        )).scalar_one_or_none()
        if not stu:
            raise HTTPException(status_code=404, detail="Élève introuvable")

    due_date_obj = None
    if data.due_date:
        from datetime import date as _date
        if isinstance(data.due_date, str):
            due_date_obj = _date.fromisoformat(data.due_date)
        else:
            due_date_obj = data.due_date

    obligation = FeeObligation(
        school_id=school_id,
        class_id=data.class_id,
        student_id=data.student_id,
        level=data.level,
        category=data.category or "scolarite",
        name=data.name.strip(),
        amount=data.amount,
        period=data.period,
        academic_year=data.academic_year,
        due_date=due_date_obj,
        description=data.description,
        is_mandatory=data.is_mandatory,
    )
    db.add(obligation)
    await db.flush()

    # Création des tranches d'échéancier si fournies
    if data.installments:
        for idx, inst in enumerate(data.installments, start=1):
            inst_due = None
            if inst.due_date:
                from datetime import date as _date
                inst_due = _date.fromisoformat(inst.due_date) if isinstance(inst.due_date, str) else inst.due_date
            db.add(FeeInstallment(
                school_id=school_id,
                obligation_id=obligation.id,
                installment_number=inst.installment_number or idx,
                title=inst.title.strip(),
                amount=inst.amount,
                due_date=inst_due,
                notes=inst.notes,
            ))
        await db.flush()

    from app.services.audit_service import safe_audit
    await safe_audit(
        db, school_id=school_id, user_id=user.id, action="payment.obligation.create",
        resource="fee_obligation", resource_id=obligation.id,
        details={"name": obligation.name, "amount": obligation.amount, "category": obligation.category},
    )
    return {"id": obligation.id, "name": obligation.name, "amount": obligation.amount, "category": obligation.category}


@router.post("/obligations/generate")
async def generate_obligations(
    data: GenerateObligationsRequest,
    user: User = Depends(require_permission("payment.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Génère automatiquement les obligations pour un élève ou une classe entière."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    from app.services import fee_service

    if data.student_id:
        stu = (await db.execute(
            select(Student).where(Student.id == data.student_id, Student.school_id == school_id)
        )).scalar_one_or_none()
        if not stu:
            raise HTTPException(status_code=404, detail="Élève introuvable")
        try:
            created = await fee_service.generate_student_obligations(
                db, school_id, data.student_id, data.academic_year
            )
            await db.commit()
            return {"status": "success", "created": created, "count": len(created)}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if data.class_id:
        cls = (await db.execute(
            select(Class).where(Class.id == data.class_id, Class.school_id == school_id)
        )).scalar_one_or_none()
        if not cls:
            raise HTTPException(status_code=404, detail="Classe introuvable")
        res = await fee_service.generate_class_obligations(
            db, school_id, data.class_id, data.academic_year
        )
        await db.commit()
        return {"status": "success", **res}

    raise HTTPException(status_code=400, detail="Veuillez spécifier un student_id ou un class_id")


@router.post("/obligations/{obligation_id}/installments", status_code=201)
async def add_obligation_installment(
    obligation_id: int,
    data: InstallmentCreate,
    user: User = Depends(require_permission("payment.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ajouter une échéance / tranche à une obligation."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    ob = (await db.execute(
        select(FeeObligation).where(FeeObligation.id == obligation_id, FeeObligation.school_id == school_id)
    )).scalar_one_or_none()
    if not ob:
        raise HTTPException(status_code=404, detail="Obligation introuvable")

    due_date_obj = None
    if data.due_date:
        from datetime import date as _date
        due_date_obj = _date.fromisoformat(data.due_date) if isinstance(data.due_date, str) else data.due_date

    inst = FeeInstallment(
        school_id=school_id,
        obligation_id=obligation_id,
        installment_number=data.installment_number,
        title=data.title.strip(),
        amount=data.amount,
        due_date=due_date_obj,
        notes=data.notes,
    )
    db.add(inst)
    await db.commit()
    return {"id": inst.id, "title": inst.title, "amount": inst.amount, "due_date": str(inst.due_date) if inst.due_date else None}


@router.get("/obligations/{obligation_id}/installments")
async def list_obligation_installments(
    obligation_id: int,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Lister les échéances d'une obligation."""
    school_id = get_school_id(user)
    ob = (await db.execute(
        select(FeeObligation).where(FeeObligation.id == obligation_id, FeeObligation.school_id == school_id)
    )).scalar_one_or_none()
    if not ob:
        raise HTTPException(status_code=404, detail="Obligation introuvable")

    installments = (await db.execute(
        select(FeeInstallment).where(
            FeeInstallment.obligation_id == obligation_id,
            FeeInstallment.school_id == school_id,
        ).order_by(FeeInstallment.installment_number)
    )).scalars().all()

    return {
        "installments": [
            {
                "id": inst.id,
                "installment_number": inst.installment_number,
                "title": inst.title,
                "amount": inst.amount,
                "due_date": str(inst.due_date) if inst.due_date else None,
                "notes": inst.notes,
            }
            for inst in installments
        ]
    }


# ── Payments ──────────────────────────────────────────────────────


@router.get("")
async def list_payments(
    student_id: int | None = None,
    status: str | None = None,
    payment_method: str | None = None,
    class_id: int | None = None,
    academic_year: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(Payment).where(Payment.school_id == school_id)

    if student_id:
        query = query.where(Payment.student_id == student_id)
    if status:
        query = query.where(Payment.status == status)
    if payment_method:
        query = query.where(Payment.payment_method == payment_method)

    # Filtrer par classe si demandé
    if class_id:
        enr_q = select(Enrollment.student_id).where(
            Enrollment.school_id == school_id,
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
        query = query.where(Payment.student_id.in_(enr_q))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    payments = (await db.execute(
        query.order_by(Payment.paid_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    # Charger les élèves et obligations en batch
    student_ids = list({p.student_id for p in payments})
    obligation_ids = list({p.obligation_id for p in payments if p.obligation_id})
    students_map = {}
    matricules_map = {}
    if student_ids:
        studs = (await db.execute(
            select(Student.id, Student.first_name, Student.last_name, Student.matricule)
            .where(Student.id.in_(student_ids))
        )).all()
        students_map = {s.id: f"{s.last_name} {s.first_name}" for s in studs}
        matricules_map = {s.id: s.matricule or f"STU-{s.id:05d}" for s in studs}

    obligations_map = {}
    if obligation_ids:
        obs = (await db.execute(
            select(FeeObligation.id, FeeObligation.name)
            .where(FeeObligation.id.in_(obligation_ids))
        )).all()
        obligations_map = {o.id: o.name for o in obs}

    rows = []
    for p in payments:
        sname = students_map.get(p.student_id, f"#{p.student_id}")
        smat = matricules_map.get(p.student_id, "")
        if search:
            sq = search.lower()
            if sq not in sname.lower() and sq not in smat.lower() and sq not in (p.transaction_id or "").lower():
                continue
        rows.append({
            "id": p.id,
            "student_id": p.student_id,
            "student_name": sname,
            "student_matricule": smat,
            "obligation_id": p.obligation_id,
            "obligation_name": obligations_map.get(p.obligation_id, "Frais scolaire"),
            "amount": p.amount,
            "payment_method": p.payment_method,
            "transaction_id": p.transaction_id,
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "mobile_operator": p.mobile_operator,
            "notes": p.notes,
            "paid_at": str(p.paid_at),
            "receipt_url": f"/api/payments/{p.id}/receipt",
        })

    return {
        "payments": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


# ── Fixed-path GET routes (AVANT /{payment_id} pour éviter l'interception) ──


@router.get("/student/{student_id}/fees")
async def student_fees_detail(
    student_id: int,
    academic_year: str | None = None,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Détail par obligation : dû, payé, solde, échéances dépassées."""
    from app.services import fee_service
    summary = await fee_service.student_fee_summary(db, get_school_id(user), student_id, academic_year)
    if not summary:
        raise HTTPException(status_code=404, detail="Élève introuvable")
    return summary


@router.get("/debtors")
async def list_debtors(
    academic_year: str | None = None,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Élèves débiteurs (solde > 0), triés par solde décroissant."""
    from app.services import fee_service
    rows = await fee_service.debtors(db, get_school_id(user), academic_year)
    return {"debtors": rows, "total": len(rows)}


@router.get("/dashboard")
async def finance_dashboard(
    academic_year: str | None = None,
    user: User = Depends(require_permission("report.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Statistiques financières : facturé, encaissé, restant, jour, mois."""
    from app.services import fee_service
    return await fee_service.financial_dashboard(db, get_school_id(user), academic_year)


@router.get("/export/csv")
async def export_csv(
    academic_year: str | None = None,
    class_id: int | None = None,
    status: str | None = None,
    export_type: str = Query("payments", pattern="^(payments|debtors|obligations)$"),
    user: User = Depends(require_permission("report.read")),
    db: AsyncSession = Depends(get_db),
):
    """Export CSV des paiements, débiteurs ou obligations (filtres : année, classe, statut)."""
    from app.services import fee_service
    from fastapi.responses import Response as _Resp
    content = await fee_service.export_payments_csv(
        db, get_school_id(user), academic_year, class_id, status, export_type=export_type)
    return _Resp(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{export_type}_yiriba.csv"'},
    )


@router.get("/{payment_id}")
async def get_payment(
    payment_id: int,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get payment details."""
    school_id = get_school_id(user)
    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == school_id)
    )).scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    return {
        "id": payment.id, "student_id": payment.student_id, "amount": payment.amount,
        "payment_method": payment.payment_method, "status": payment.status.value if hasattr(payment.status, "value") else str(payment.status),
        "mobile_operator": payment.mobile_operator, "mobile_number": payment.mobile_number,
        "notes": payment.notes, "paid_at": str(payment.paid_at),
        "created_at": str(payment.created_at), "transaction_id": payment.transaction_id,
        "obligation_id": payment.obligation_id, "installment_id": payment.installment_id,
        "receipt_url": payment.receipt_url, "receipt_qr_token": payment.receipt_qr_token,
        "refund_reason": payment.refund_reason, "correction_reason": payment.correction_reason,
        "corrected_at": str(payment.corrected_at) if payment.corrected_at else None,
    }


@router.patch("/{payment_id}/confirm")
async def confirm_payment(
    payment_id: int,
    user: User = Depends(require_permission("payment.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Confirm a pending payment (Comptable/Directeur only)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == school_id)
    )).scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    if payment.status != PaymentStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Ce paiement est déjà {payment.status.value}")
    payment.status = PaymentStatus.CONFIRMED
    await db.commit()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="payment.confirm", resource="payment", resource_id=payment.id, details={"amount": payment.amount, "student_id": payment.student_id})

    # ── Notification de confirmation au(x) parent(s) ──────────────
    try:
        from app.services.notification_service import notify_payment_confirmation
        await notify_payment_confirmation(
            db, school_id, payment.student_id,
            f"{payment.amount:,.0f}".replace(",", " "), payment.id,
        )
        await db.commit()
    except Exception:
        await db.rollback()

    return {"id": payment.id, "status": "confirmed", "message": "Paiement confirmé"}


@router.patch("/{payment_id}/reject")
async def reject_payment(
    payment_id: int,
    user: User = Depends(require_permission("payment.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a pending payment."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == school_id)
    )).scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    if payment.status != PaymentStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Ce paiement est déjà {payment.status.value}")
    payment.status = PaymentStatus.CANCELLED
    await db.commit()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="payment.reject", resource="payment", resource_id=payment.id, details={"amount": payment.amount, "student_id": payment.student_id})
    return {"id": payment.id, "status": "cancelled", "message": "Paiement refusé"}


@router.post("", status_code=201)
async def create_payment(
    data: PaymentCreate,
    user: User = Depends(require_permission("payment.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record a payment (cash, mobile money, bank, cheque)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Verify student belongs to school
    student = (await db.execute(
        select(Student).where(Student.id == data.student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Élève introuvable")

    # ── Vérification FK croisée : l'obligation appartient-elle à cette école ?
    if data.obligation_id:
        obligation = (await db.execute(
            select(FeeObligation.id).where(
                FeeObligation.id == data.obligation_id,
                FeeObligation.school_id == school_id,
            )
        )).scalar_one_or_none()
        if obligation is None:
            raise HTTPException(status_code=404, detail="Obligation de paiement introuvable")

    # ── Vérification FK croisée : l'échéance appartient-elle à cette école ?
    if data.installment_id:
        installment = (await db.execute(
            select(FeeInstallment.id).where(
                FeeInstallment.id == data.installment_id,
                FeeInstallment.school_id == school_id,
            )
        )).scalar_one_or_none()
        if installment is None:
            raise HTTPException(status_code=404, detail="Échéance introuvable")

    import secrets
    from datetime import datetime, timezone
    tx_ref = data.transaction_id or secrets.token_hex(16)
    method = "cheque" if data.payment_method == "check" else data.payment_method

    payment = Payment(
        school_id=school_id,
        student_id=data.student_id,
        obligation_id=data.obligation_id,
        installment_id=data.installment_id,
        recorded_by=user.id,
        amount=data.amount,
        payment_method=method,
        transaction_id=tx_ref,
        mobile_operator=data.mobile_operator,
        mobile_number=data.mobile_number,
        notes=data.notes,
        status=PaymentStatus.PENDING,
        paid_at=datetime.now(timezone.utc),
    )

    # ── Garde-fou : pas de dépassement du montant dû sans règle explicite
    from app.services import fee_service
    try:
        await fee_service.check_overpay(
            db, school_id, data.student_id, data.obligation_id,
            data.amount, data.allow_overpay,
        )
    except ValueError as e:
        msg = str(e)
        if msg.startswith("OVERPAY:"):
            remaining = msg.split(":", 1)[1]
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Ce paiement dépasse le solde restant ({remaining} FCFA). "
                    "Confirmez le dépassement pour l'autoriser."
                ),
            )
        raise

    db.add(payment)
    await db.flush()

    from app.services.audit_service import safe_audit
    await safe_audit(
        db, school_id=school_id, user_id=user.id, action="payment.create",
        resource="payment", resource_id=payment.id,
        details={"amount": payment.amount, "student_id": payment.student_id, "method": payment.payment_method},
    )

    return {"id": payment.id, "amount": payment.amount, "status": payment.status.value, "message": "Paiement enregistré, en attente de confirmation"}


# ── Annulation avec motif ────────────────────────────────────────


@router.patch("/{payment_id}/cancel")
async def cancel_payment(
    payment_id: int,
    data: CancelRequest,
    user: User = Depends(require_permission("payment.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Annuler un paiement (motif obligatoire, audit conservé)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    from app.services import fee_service
    try:
        result = await fee_service.cancel_payment(db, school_id, user.id, payment_id, data.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    await db.commit()
    return result


# ── Correction avec motif ────────────────────────────────────────


@router.patch("/{payment_id}/correct")
async def correct_payment_endpoint(
    payment_id: int,
    data: PaymentCorrectRequest,
    user: User = Depends(require_permission("payment.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Corriger un paiement existant (motif obligatoire, audit complet conservé)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    from app.services import fee_service
    method = "cheque" if data.payment_method == "check" else data.payment_method
    try:
        result = await fee_service.correct_payment(
            db, school_id=school_id, user_id=user.id,
            payment_id=payment_id, reason=data.reason,
            amount=data.amount, payment_method=method,
            notes=data.notes, allow_overpay=data.allow_overpay,
        )
    except ValueError as e:
        msg = str(e)
        if msg.startswith("OVERPAY:"):
            rem = msg.split(":", 1)[1]
            raise HTTPException(
                status_code=422,
                detail=f"Ce montant dépasse le solde restant ({rem} FCFA). Confirmez le dépassement.",
            )
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    await db.commit()
    return result


# ── Relances impayés (envoi uniquement — listes déjà en haut) ──


@router.post("/reminders")
async def send_reminders(
    data: ReminderRequest,
    user: User = Depends(require_permission("payment.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Envoyer une relance de paiement aux parents des élèves donnés.

    Seuls les parents réellement associés à l'élève sont notifiés.
    """
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    from app.services import fee_service
    from app.services.notification_service import notify_payment_reminder

    sent = 0
    for sid in data.student_ids:
        summary = await fee_service.student_fee_summary(db, school_id, sid)
        if not summary or summary.get("balance", 0) <= 0:
            continue
        due = (summary.get("overdue") or [{}])[0].get("due_date")
        n = await notify_payment_reminder(
            db, school_id, sid,
            f"{summary['balance']:,.0f}".replace(",", " "), due,
        )
        sent += n
    await db.commit()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="payment.reminder.send",
                     resource="payment", resource_id=None, details={"students": data.student_ids, "sent": sent})
    return {"sent": sent, "students_requested": len(data.student_ids)}


# ── Student Financial Summary ────────────────────────────────────


@router.get("/student/{student_id}")
async def student_financial_summary(
    student_id: int,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get financial summary for a student: obligations, payments, balance."""
    school_id = get_school_id(user)

    student = (await db.execute(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Élève introuvable")

    # Get all payments for this student
    payments = (await db.execute(
        select(Payment).where(
            Payment.student_id == student_id,
            Payment.school_id == school_id,
            Payment.status == PaymentStatus.CONFIRMED,
        )
    )).scalars().all()

    total_paid = sum(p.amount for p in payments)

    # Get obligations (from enrolled class)
    from app.models.class_ import Enrollment
    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()

    total_owed = 0
    obligations_detail = []
    if enrollment:
        obligations = (await db.execute(
            select(FeeObligation).where(
                FeeObligation.class_id == enrollment.class_id,
                FeeObligation.is_active == True,  # noqa: E712
            )
        )).scalars().all()
        total_owed = sum(o.amount for o in obligations)
        obligations_detail = [
            {"name": o.name, "amount": o.amount, "period": o.period}
            for o in obligations
        ]

    return {
        "student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"},
        "total_owed": total_owed,
        "total_paid": total_paid,
        "balance": total_owed - total_paid,
        "obligations": obligations_detail,
        "payments": [
            {"id": p.id, "amount": p.amount, "method": p.payment_method, "date": str(p.paid_at)}
            for p in payments
        ],
    }


@router.get("/stats")
async def payment_stats(
    user: User = Depends(require_permission("report.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Payment statistics: total collected, by method, pending."""
    school_id = get_school_id(user)

    total = (await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.school_id == school_id,
            Payment.status == "confirmed",
        )
    )).scalar() or 0

    by_method = (await db.execute(
        select(Payment.payment_method, func.sum(Payment.amount), func.count(Payment.id)).where(
            Payment.school_id == school_id,
            Payment.status == "confirmed",
        ).group_by(Payment.payment_method)
    )).all()

    return {
        "total_collected": total,
        "by_method": [
            {"method": row[0], "total": row[1], "count": row[2]}
            for row in by_method
        ],
    }


# ── Receipt PDF ─────────────────────────────────────────────────

@router.get("/{payment_id}/receipt")
async def get_receipt_pdf(
    payment_id: int,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate and return a payment receipt PDF."""
    from app.services.pdf_service import generate_receipt_pdf

    school_id = get_school_id(user)
    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == school_id)
    )).scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement introuvable")

    try:
        pdf_bytes = await generate_receipt_pdf(db, payment_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    filename = f"recu_{payment_id:06d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@router.get("/{payment_id}/receipt/html")
async def get_receipt_html(
    payment_id: int,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Aperçu HTML imprimable du reçu officiel avec logo, solde et caissier."""
    from app.services.pdf_service import (
        _jinja_env, _generate_receipt_number, _generate_receipt_token,
        _generate_qr_image, _resolve_uploaded_logo, _number_to_french_words,
        get_settings,
    )
    from app.models.school import School
    from app.services.fee_service import paid_by_student
    import os

    school_id = get_school_id(user)
    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == school_id)
    )).scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement introuvable")

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one()
    student = (await db.execute(select(Student).where(Student.id == payment.student_id))).scalar_one_or_none()

    obligation = None
    if payment.obligation_id:
        obligation = (await db.execute(
            select(FeeObligation).where(FeeObligation.id == payment.obligation_id)
        )).scalar_one_or_none()

    motif = obligation.name if obligation else (payment.notes or "Frais scolaire")
    period = obligation.period if obligation else "—"

    class_name = "—"
    if student:
        enr = (await db.execute(
            select(Enrollment).where(Enrollment.student_id == student.id, Enrollment.status == "active")
        )).scalar_one_or_none()
        if enr:
            cls = (await db.execute(select(Class).where(Class.id == enr.class_id))).scalar_one_or_none()
            if cls:
                class_name = cls.name

    remaining_balance = 0.0
    if payment.obligation_id and student:
        total_paid_for_ob = await paid_by_student(db, school.id, student.id, payment.obligation_id)
        if obligation:
            remaining_balance = max(obligation.amount - total_paid_for_ob, 0.0)

    cashier_name = "Le Service Comptable"
    if payment.recorded_by:
        cashier = (await db.execute(select(User).where(User.id == payment.recorded_by))).scalar_one_or_none()
        if cashier:
            cashier_name = f"{cashier.first_name} {cashier.last_name}".strip() or cashier.email

    receipt_number = _generate_receipt_number(school.id, payment.id)
    token = payment.receipt_qr_token or _generate_receipt_token(school.id, payment.id)
    cfg = get_settings()
    verification_url = f"{cfg.SERVER_URL}/api/verify/receipt/{payment.id}/{token}"
    qr_path = _generate_qr_image(verification_url)
    school_logo_url, school_logo_path = _resolve_uploaded_logo(school.logo_url)

    method_labels = {
        "cash": "Espèces",
        "mobile_money": f"Mobile Money ({payment.mobile_operator or ''})",
        "bank": "Virement bancaire",
        "cheque": "Chèque",
        "check": "Chèque",
        "other": "Autre",
    }
    payment_method = method_labels.get(payment.payment_method, payment.payment_method)

    tmpl = _jinja_env.get_template("receipt.html")
    html_content = tmpl.render(
        school_name=school.name,
        school_initial=school.short_name or school.name[:2].upper(),
        school_address=school.address or "",
        school_city=school.city or "",
        school_country=school.country or "",
        school_phone=school.phone or "",
        school_logo_url=school_logo_url,
        school_logo_path=school_logo_path or "",
        school_color="#0E5C3F",
        receipt_number=receipt_number,
        student_first_name=student.first_name if student else "—",
        student_last_name=student.last_name if student else "—",
        matricule=student.matricule if student and student.matricule else "—",
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

    try:
        os.remove(qr_path)
    except OSError:
        pass

    return Response(content=html_content, media_type="text/html")

