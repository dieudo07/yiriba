"""Yiriba SaaS — Fee/scolarité service.

Gestion des frais de scolarité des élèves (paiement parent → établissement).
Complètement séparé du système d'abonnement école → YIRIBA (subscription).
Toutes les requêtes filtrent par school_id (isolation multi-tenant stricte).
"""

import csv
import io
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.class_ import Class, Enrollment
from app.models.payment import FeeInstallment, FeeObligation, Payment, PaymentStatus
from app.models.student import Student

# Paiements comptabilisés dans le "payé"
_PAID_STATUSES = (PaymentStatus.CONFIRMED,)


async def _active_enrollment(db: AsyncSession, school_id: int, student_id: int) -> Enrollment | None:
    return (await db.execute(
        select(Enrollment).where(
            Enrollment.school_id == school_id,
            Enrollment.student_id == student_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()


async def class_obligations(
    db: AsyncSession, school_id: int, class_id: int, academic_year: str | None = None,
) -> list[FeeObligation]:
    """Obligations de frais configurées pour une classe (et année si donnée)."""
    query = select(FeeObligation).where(
        FeeObligation.school_id == school_id,
        FeeObligation.class_id == class_id,
        FeeObligation.student_id.is_(None),
        FeeObligation.is_active == True,  # noqa: E712
    )
    if academic_year:
        query = query.where(FeeObligation.academic_year == academic_year)
    return list((await db.execute(query.order_by(FeeObligation.due_date.nulls_last()))).scalars().all())


async def paid_by_student(
    db: AsyncSession, school_id: int, student_id: int,
    obligation_id: int | None = None,
    installment_id: int | None = None,
) -> float:
    """Montant total payé et confirmé par un élève pour une obligation donnée."""
    query = select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
        Payment.school_id == school_id,
        Payment.student_id == student_id,
        Payment.status == PaymentStatus.CONFIRMED,
    )
    if obligation_id is not None:
        query = query.where(Payment.obligation_id == obligation_id)
    if installment_id is not None:
        query = query.where(Payment.installment_id == installment_id)
    return float((await db.execute(query)).scalar() or 0)


async def student_fee_summary(
    db: AsyncSession, school_id: int, student_id: int, academic_year: str | None = None,
) -> dict:
    """Résumé complet : obligations, échéances, payé par obligation, solde, échéances dépassées."""
    student = (await db.execute(
        select(Student).where(Student.id == student_id, Student.school_id == school_id)
    )).scalar_one_or_none()
    if not student:
        return {}

    enrollment = await _active_enrollment(db, school_id, student_id)
    if not enrollment:
        return {
            "student": {
                "id": student.id,
                "name": f"{student.first_name} {student.last_name}",
                "matricule": student.matricule,
            },
            "class_id": None,
            "academic_year": academic_year,
            "items": [],
            "total_owed": 0,
            "total_paid": 0,
            "balance": 0,
            "overdue": [],
        }

    # Année de l'inscription si non fournie
    if not academic_year and enrollment.academic_year_id:
        from app.models.academic_year import AcademicYear
        ay = (await db.execute(
            select(AcademicYear).where(AcademicYear.id == enrollment.academic_year_id)
        )).scalar_one_or_none()
        academic_year = ay.name if ay else None

    # 1. Obligations spécifiques à l'élève
    st_obs_query = select(FeeObligation).options(selectinload(FeeObligation.installments)).where(
        FeeObligation.school_id == school_id,
        FeeObligation.student_id == student_id,
        FeeObligation.is_active == True,  # noqa: E712
    )
    if academic_year:
        st_obs_query = st_obs_query.where(FeeObligation.academic_year == academic_year)
    student_obs = list((await db.execute(st_obs_query.order_by(FeeObligation.due_date.nulls_last()))).scalars().all())

    # 2. Obligations au niveau de la classe
    class_obs_query = select(FeeObligation).options(selectinload(FeeObligation.installments)).where(
        FeeObligation.school_id == school_id,
        FeeObligation.class_id == enrollment.class_id,
        FeeObligation.student_id.is_(None),
        FeeObligation.is_active == True,  # noqa: E712
    )
    if academic_year:
        class_obs_query = class_obs_query.where(FeeObligation.academic_year == academic_year)
    class_obs = list((await db.execute(class_obs_query.order_by(FeeObligation.due_date.nulls_last()))).scalars().all())

    # Combinaison : les obligations individuelles prennent la priorité sur les génériques de même nom
    st_names = {o.name.strip().lower() for o in student_obs}
    obligations = list(student_obs)
    for co in class_obs:
        if co.name.strip().lower() not in st_names:
            obligations.append(co)

    today = date.today()
    items, total_owed, overdue = [], 0.0, []

    for o in obligations:
        paid = await paid_by_student(db, school_id, student_id, o.id)
        balance = round(o.amount - paid, 2)
        total_owed += o.amount

        # Détail des tranches/échéances si présentes
        inst_items = []
        for inst in getattr(o, "installments", []):
            inst_paid = await paid_by_student(db, school_id, student_id, o.id, installment_id=inst.id)
            inst_overdue = bool(inst.due_date and inst.due_date < today and (inst.amount - inst_paid) > 0.001)
            inst_items.append({
                "id": inst.id,
                "number": inst.installment_number,
                "title": inst.title,
                "amount": inst.amount,
                "due_date": str(inst.due_date) if inst.due_date else None,
                "paid": round(inst_paid, 2),
                "overdue": inst_overdue,
            })

        is_overdue = bool(o.due_date and balance > 0.001 and o.due_date < today)
        item = {
            "obligation_id": o.id,
            "name": o.name,
            "description": o.description,
            "category": o.category,
            "level": o.level,
            "is_mandatory": o.is_mandatory,
            "amount": o.amount,
            "period": o.period,
            "academic_year": o.academic_year,
            "due_date": str(o.due_date) if o.due_date else None,
            "paid": round(paid, 2),
            "balance": max(balance, 0.0),
            "status": ("paid" if balance <= 0.001 else
                       ("partial" if paid > 0 else "unpaid")),
            "overdue": is_overdue,
            "installments": inst_items,
        }
        if item["overdue"]:
            overdue.append({
                "obligation_id": o.id,
                "name": o.name,
                "category": o.category,
                "balance": item["balance"],
                "due_date": item["due_date"],
            })
        items.append(item)

    total_paid = round(sum(i["paid"] for i in items), 2)
    return {
        "student": {
            "id": student.id,
            "name": f"{student.first_name} {student.last_name}",
            "matricule": student.matricule,
        },
        "class_id": enrollment.class_id,
        "academic_year": academic_year,
        "items": items,
        "total_owed": round(total_owed, 2),
        "total_paid": total_paid,
        "balance": round(max(total_owed - total_paid, 0.0), 2),
        "overdue": overdue,
    }


async def check_overpay(
    db: AsyncSession, school_id: int, student_id: int,
    obligation_id: int | None, amount: float, allow_overpay: bool = False,
    exclude_payment_id: int | None = None,
) -> None:
    """Refuse un paiement qui dépasse le solde restant, sauf si allow_overpay."""
    if obligation_id is None or allow_overpay:
        return
    obligation = (await db.execute(
        select(FeeObligation).where(
            FeeObligation.id == obligation_id, FeeObligation.school_id == school_id
        )
    )).scalar_one_or_none()
    if not obligation:
        return

    # Somme des paiements existants (sauf le paiement en cours de modification)
    q = select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
        Payment.school_id == school_id,
        Payment.student_id == student_id,
        Payment.obligation_id == obligation_id,
        Payment.status == PaymentStatus.CONFIRMED,
    )
    if exclude_payment_id:
        q = q.where(Payment.id != exclude_payment_id)
    paid = float((await db.execute(q)).scalar() or 0)

    remaining = obligation.amount - paid
    if amount > remaining + 0.001:
        raise ValueError(
            f"OVERPAY:{round(remaining, 2)}"
        )


async def cancel_payment(
    db: AsyncSession, school_id: int, user_id: int,
    payment_id: int, reason: str,
) -> dict:
    """Annulation avec motif obligatoire — jamais de suppression silencieuse."""
    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == school_id)
    )).scalar_one_or_none()
    if not payment:
        return {}
    if payment.status == PaymentStatus.CANCELLED:
        raise ValueError("Ce paiement est déjà annulé")
    old_status = payment.status.value if hasattr(payment.status, 'value') else str(payment.status)
    payment.status = PaymentStatus.CANCELLED
    payment.refund_reason = reason.strip()[:200]
    payment.refunded_at = datetime.now(timezone.utc)
    payment.refunded_by = user_id
    from app.services.audit_service import safe_audit
    await safe_audit(
        db, school_id=school_id, user_id=user_id, action="payment.cancel",
        resource="payment", resource_id=payment.id,
        details={"amount": payment.amount, "reason": reason.strip()[:200],
                 "previous_status": old_status},
    )
    return {"id": payment.id, "status": "cancelled", "reason": payment.refund_reason}


async def correct_payment(
    db: AsyncSession, school_id: int, user_id: int,
    payment_id: int, reason: str,
    amount: float | None = None,
    payment_method: str | None = None,
    notes: str | None = None,
    allow_overpay: bool = False,
) -> dict:
    """Correction d'un paiement avec motif obligatoire et conservation d'audit."""
    if not reason or len(reason.strip()) < 3:
        raise ValueError("Le motif de correction est obligatoire (minimum 3 caractères)")

    payment = (await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == school_id)
    )).scalar_one_or_none()
    if not payment:
        return {}
    if payment.status == PaymentStatus.CANCELLED:
        raise ValueError("Impossible de corriger un paiement annulé")

    # Si le montant change, vérifier le dépassement
    if amount is not None and amount != payment.amount:
        await check_overpay(
            db, school_id, payment.student_id, payment.obligation_id,
            amount, allow_overpay=allow_overpay, exclude_payment_id=payment.id,
        )

    previous_values = {
        "amount": payment.amount,
        "payment_method": payment.payment_method,
        "notes": payment.notes,
    }

    if amount is not None:
        payment.amount = amount
    if payment_method is not None:
        payment.payment_method = payment_method
    if notes is not None:
        payment.notes = notes

    payment.corrected_at = datetime.now(timezone.utc)
    payment.corrected_by = user_id
    payment.correction_reason = reason.strip()[:255]

    from app.services.audit_service import safe_audit
    await safe_audit(
        db, school_id=school_id, user_id=user_id, action="payment.correct",
        resource="payment", resource_id=payment.id,
        details={
            "reason": reason.strip()[:255],
            "previous": previous_values,
            "new": {"amount": payment.amount, "payment_method": payment.payment_method, "notes": payment.notes},
        },
    )

    return {
        "id": payment.id,
        "amount": payment.amount,
        "payment_method": payment.payment_method,
        "status": payment.status.value if hasattr(payment.status, "value") else str(payment.status),
        "notes": payment.notes,
        "correction_reason": payment.correction_reason,
        "corrected_at": str(payment.corrected_at),
    }


async def generate_student_obligations(
    db: AsyncSession, school_id: int, student_id: int, academic_year: str | None = None,
) -> list[dict]:
    """Génère les obligations de paiement pour un élève inscrit selon les frais configurés."""
    enrollment = await _active_enrollment(db, school_id, student_id)
    if not enrollment:
        raise ValueError("L'élève n'a pas d'inscription active")

    if not academic_year and enrollment.academic_year_id:
        from app.models.academic_year import AcademicYear
        ay = (await db.execute(
            select(AcademicYear).where(AcademicYear.id == enrollment.academic_year_id)
        )).scalar_one_or_none()
        academic_year = ay.name if ay else None

    # Chercher les obligations déjà configurées au niveau de la classe
    class_obs = await class_obligations(db, school_id, enrollment.class_id, academic_year)

    # Récupérer les obligations existantes de l'élève
    existing_st_obs = (await db.execute(
        select(FeeObligation).where(
            FeeObligation.school_id == school_id,
            FeeObligation.student_id == student_id,
            FeeObligation.academic_year == (academic_year or "2025-2026"),
        )
    )).scalars().all()
    existing_names = {o.name.strip().lower() for o in existing_st_obs}

    created = []
    if class_obs:
        # Cloner les obligations de classe en obligations personnalisées si elles n'existent pas encore
        for co in class_obs:
            if co.name.strip().lower() in existing_names:
                continue
            st_ob = FeeObligation(
                school_id=school_id,
                student_id=student_id,
                class_id=enrollment.class_id,
                name=co.name,
                amount=co.amount,
                category=co.category or "scolarite",
                period=co.period or "annuel",
                academic_year=co.academic_year,
                due_date=co.due_date,
                description=co.description,
                is_mandatory=co.is_mandatory,
            )
            db.add(st_ob)
            await db.flush()

            # Copier les échéances associées
            inst_query = select(FeeInstallment).where(FeeInstallment.obligation_id == co.id)
            installments = (await db.execute(inst_query)).scalars().all()
            for inst in installments:
                st_inst = FeeInstallment(
                    school_id=school_id,
                    obligation_id=st_ob.id,
                    installment_number=inst.installment_number,
                    title=inst.title,
                    amount=inst.amount,
                    due_date=inst.due_date,
                    notes=inst.notes,
                )
                db.add(st_inst)

            created.append({"id": st_ob.id, "name": st_ob.name, "amount": st_ob.amount})
    else:
        # Fallback sur les champs enrollment_fee et annual_tuition de la classe
        cls = (await db.execute(select(Class).where(Class.id == enrollment.class_id))).scalar_one_or_none()
        if cls:
            ay = academic_year or cls.academic_year or "2025-2026"
            if cls.enrollment_fee and float(cls.enrollment_fee) > 0 and "frais d'inscription" not in existing_names:
                ob = FeeObligation(
                    school_id=school_id,
                    student_id=student_id,
                    class_id=cls.id,
                    name="Frais d'inscription",
                    category="inscription",
                    amount=float(cls.enrollment_fee),
                    period="annuel",
                    academic_year=ay,
                    is_mandatory=True,
                )
                db.add(ob)
                await db.flush()
                created.append({"id": ob.id, "name": ob.name, "amount": ob.amount})

            if cls.annual_tuition and float(cls.annual_tuition) > 0 and "frais de scolarité" not in existing_names:
                ob = FeeObligation(
                    school_id=school_id,
                    student_id=student_id,
                    class_id=cls.id,
                    name="Frais de scolarité",
                    category="scolarite",
                    amount=float(cls.annual_tuition),
                    period="annuel",
                    academic_year=ay,
                    is_mandatory=True,
                )
                db.add(ob)
                await db.flush()
                created.append({"id": ob.id, "name": ob.name, "amount": ob.amount})

    return created


async def generate_class_obligations(
    db: AsyncSession, school_id: int, class_id: int, academic_year: str | None = None,
) -> dict:
    """Génère les obligations de paiement pour tous les élèves inscrits d'une classe."""
    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.school_id == school_id,
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
    )).scalars().all()

    total_created = 0
    for e in enrollments:
        created = await generate_student_obligations(db, school_id, e.student_id, academic_year)
        total_created += len(created)

    return {"students_processed": len(enrollments), "obligations_created": total_created}


async def debtors(
    db: AsyncSession, school_id: int, academic_year: str | None = None, limit: int = 100,
) -> list[dict]:
    """Élèves débiteurs : soldes impayés + échéances dépassées."""
    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.school_id == school_id, Enrollment.status == "active"
        ).limit(2000)
    )).scalars().all()
    if not enrollments:
        return []

    result = []
    for e in enrollments:
        summary = await student_fee_summary(db, school_id, e.student_id, academic_year)
        if not summary:
            continue
        balance = summary.get("balance", 0.0)
        if balance > 0.001:
            overdue_list = summary.get("overdue", [])
            overdue_amount = sum(o.get("balance", 0.0) for o in overdue_list)
            st_info = summary.get("student", {})
            result.append({
                "student_id": e.student_id,
                "name": st_info.get("name", f"#{e.student_id}"),
                "matricule": st_info.get("matricule", "—"),
                "class_id": e.class_id,
                "balance": round(balance, 2),
                "total_owed": summary.get("total_owed", 0.0),
                "total_paid": summary.get("total_paid", 0.0),
                "overdue_count": len(overdue_list),
                "overdue_amount": round(overdue_amount, 2),
            })
        if len(result) >= limit:
            break
    result.sort(key=lambda x: -x["balance"])
    return result


async def financial_dashboard(
    db: AsyncSession, school_id: int, academic_year: str | None = None,
) -> dict:
    """Statistiques du tableau de bord financier."""
    today = date.today()

    # Facturé = somme des obligations des classes avec inscriptions actives
    enrollments = (await db.execute(
        select(Enrollment).where(
            Enrollment.school_id == school_id, Enrollment.status == "active"
        ).limit(2000)
    )).scalars().all()
    class_ids = list({e.class_id for e in enrollments})
    student_ids = list({e.student_id for e in enrollments})

    billed = 0.0
    if class_ids:
        query = select(func.coalesce(func.sum(FeeObligation.amount), 0.0)).where(
            FeeObligation.school_id == school_id,
            FeeObligation.class_id.in_(class_ids),
            FeeObligation.is_active == True,  # noqa: E712
        )
        if academic_year:
            query = query.where(FeeObligation.academic_year == academic_year)
        billed = float((await db.execute(query)).scalar() or 0)

    paid_q = select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
        Payment.school_id == school_id,
        Payment.status == PaymentStatus.CONFIRMED,
        Payment.student_id.in_(student_ids) if student_ids else True,
    )
    if academic_year:
        paid_q = paid_q.where(Payment.paid_at >= _year_start(academic_year))
    collected = float((await db.execute(paid_q)).scalar() or 0)

    # Paiements du jour / du mois
    day_q = select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
        Payment.school_id == school_id,
        Payment.status == PaymentStatus.CONFIRMED,
        func.date(Payment.paid_at) == today,
    )
    month_q = select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
        Payment.school_id == school_id,
        Payment.status == PaymentStatus.CONFIRMED,
        func.date(Payment.paid_at) >= today.replace(day=1),
    )
    today_total = float((await db.execute(day_q)).scalar() or 0)
    month_total = float((await db.execute(month_q)).scalar() or 0)

    # Débiteurs et échéances en retard
    debtors_list = await debtors(db, school_id, academic_year, limit=500)
    debtors_count = len(debtors_list)
    overdue_count = sum(d["overdue_count"] for d in debtors_list)
    overdue_amount = sum(d["overdue_amount"] for d in debtors_list)

    return {
        "academic_year": academic_year,
        "billed": round(billed, 2),
        "collected": round(collected, 2),
        "outstanding": round(max(billed - collected, 0.0), 2),
        "today": round(today_total, 2),
        "month": round(month_total, 2),
        "debtors_count": debtors_count,
        "overdue_count": overdue_count,
        "overdue_amount": round(overdue_amount, 2),
    }


def _year_start(academic_year: str) -> datetime:
    """Début d'année scolaire '2025-2026' → 2025-08-01."""
    try:
        start_year = int(academic_year.split("-")[0])
        return datetime(start_year, 8, 1, tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return datetime(2020, 1, 1, tzinfo=timezone.utc)


async def export_payments_csv(
    db: AsyncSession, school_id: int, academic_year: str | None = None,
    class_id: int | None = None, status: str | None = None,
    export_type: str = "payments",
) -> bytes:
    """Export CSV des données financières (paiements, débiteurs, obligations)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")

    if export_type == "debtors":
        debtors_list = await debtors(db, school_id, academic_year, limit=1000)
        writer.writerow(["Matricule", "Élève", "Montant Dû (FCFA)", "Payé (FCFA)", "Reste à Payer (FCFA)", "Échéances en retard", "Montant en retard (FCFA)"])
        for d in debtors_list:
            writer.writerow([
                d.get("matricule", "—"),
                d.get("name", "—"),
                f"{d.get('total_owed', 0):.0f}",
                f"{d.get('total_paid', 0):.0f}",
                f"{d.get('balance', 0):.0f}",
                d.get("overdue_count", 0),
                f"{d.get('overdue_amount', 0):.0f}",
            ])
        return buf.getvalue().encode("utf-8-sig")

    if export_type == "obligations":
        query = select(FeeObligation).where(FeeObligation.school_id == school_id)
        if class_id:
            query = query.where(FeeObligation.class_id == class_id)
        if academic_year:
            query = query.where(FeeObligation.academic_year == academic_year)
        obs = (await db.execute(query.order_by(FeeObligation.id.desc()))).scalars().all()
        writer.writerow(["ID", "Frais", "Catégorie", "Montant (FCFA)", "Période", "Année scolaire", "Obligatoire", "Échéance", "Statut"])
        for o in obs:
            writer.writerow([
                o.id,
                o.name,
                o.category,
                f"{o.amount:.0f}",
                o.period,
                o.academic_year,
                "Oui" if o.is_mandatory else "Non",
                str(o.due_date) if o.due_date else "—",
                "Actif" if o.is_active else "Inactif",
            ])
        return buf.getvalue().encode("utf-8-sig")

    # Par défaut : export des paiements
    query = select(Payment).where(Payment.school_id == school_id)
    if status:
        query = query.where(Payment.status == status)
    payments = (await db.execute(
        query.order_by(Payment.paid_at.desc()).limit(5000)
    )).scalars().all()

    # Filtrage par classe via inscriptions
    if class_id:
        enrolls = (await db.execute(
            select(Enrollment.student_id).where(
                Enrollment.school_id == school_id, Enrollment.class_id == class_id
            )
        )).scalars().all()
        keep = set(enrolls)
        payments = [p for p in payments if p.student_id in keep]

    # Noms d'élèves en batch
    sids = list({p.student_id for p in payments})
    names = {}
    if sids:
        rows = (await db.execute(
            select(Student.id, Student.first_name, Student.last_name, Student.matricule)
            .where(Student.id.in_(sids))
        )).all()
        names = {r[0]: (f"{r[2]} {r[1]}", r[3]) for r in rows}

    writer.writerow(["ID", "Date", "Élève", "Matricule", "Montant (FCFA)",
                     "Moyen", "Référence", "Statut", "Notes"])
    for p in payments:
        nm = names.get(p.student_id, (f"#{p.student_id}", ""))
        writer.writerow([
            p.id, str(p.paid_at), nm[0], nm[1],
            f"{p.amount:.0f}", p.payment_method,
            p.transaction_id or p.id,
            p.status.value if hasattr(p.status, "value") else str(p.status),
            (p.notes or "").replace(";", ","),
        ])
    return buf.getvalue().encode("utf-8-sig")
