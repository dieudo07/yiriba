"""Yiriba SaaS — Parent Portal routes.

Le parent ne voit QUE ses enfants rattachés via ParentStudent.
Filtrage par ownership : parent_id vérifié sur chaque requête.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.models.bulletin import Bulletin
from app.models.class_ import Enrollment, Class
from app.models.grade import Evaluation, Grade
from app.models.attendance import Attendance, StatutPresence
from app.models.payment import Payment, FeeObligation, PaymentStatus
from app.models.parent_student import ParentStudent
from app.models.student import Student
from app.models.user import User, UserRole
from datetime import datetime

router = APIRouter(prefix="/api/parent", tags=["parent_portal"])


# --- Helper: verify parent owns the child ---


async def _verify_parent_child(
    db: AsyncSession, parent_id: int, student_id: int, school_id: int
) -> Student:
    """Verify that the parent is linked to this student."""
    link = (await db.execute(
        select(ParentStudent).where(
            ParentStudent.parent_id == parent_id,
            ParentStudent.student_id == student_id,
        )
    )).scalar_one_or_none()
    if not link:
        raise HTTPException(
            status_code=403,
            detail="Cet enfant ne vous est pas rattaché"
        )

    student = (await db.execute(
        select(Student).where(
            Student.id == student_id,
            Student.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Élève introuvable")

    return student


# --- My Children ---


@router.get("/my-children")
async def my_children(
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all children linked to this parent."""
    school_id = get_school_id(user)

    links = (await db.execute(
        select(ParentStudent).where(ParentStudent.parent_id == user.id)
    )).scalars().all()

    children = []
    for link in links:
        student = (await db.execute(
            select(Student).where(
                Student.id == link.student_id,
                Student.school_id == school_id,
            )
        )).scalar_one_or_none()
        if not student:
            continue

        # Get current class
        enrollment = (await db.execute(
            select(Enrollment).where(
                Enrollment.student_id == student.id,
                Enrollment.status == "active",
            )
        )).scalar_one_or_none()
        class_name = None
        if enrollment:
            cls = (await db.execute(
                select(Class).where(Class.id == enrollment.class_id)
            )).scalar_one_or_none()
            class_name = cls.name if cls else None

        children.append({
            "id": student.id,
            "first_name": student.first_name,
            "last_name": student.last_name,
            "matricule": student.matricule,
            "class_name": class_name,
            "status": student.status.value,
        })

    return {"children": children}


# --- Child Grades ---


@router.get("/children/{student_id}/grades")
async def child_grades(
    student_id: int,
    period: str | None = None,
    academic_period_id: int | None = None,
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get grades for a child — only if parent is linked."""
    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    # Get student's current class
    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()
    if not enrollment:
        return {"grades": [], "student": student.first_name}

    # Get evaluations for this class
    eval_query = select(Evaluation).where(
        Evaluation.class_id == enrollment.class_id,
        Evaluation.school_id == school_id,
    )
    if period:
        eval_query = eval_query.where(Evaluation.period == period)
    if academic_period_id:
        eval_query = eval_query.where(Evaluation.academic_period_id == academic_period_id)

    evaluations = (await db.execute(eval_query)).scalars().all()
    eval_ids = [e.id for e in evaluations]
    eval_lookup = {e.id: e for e in evaluations}

    grades = (await db.execute(
        select(Grade).where(
            Grade.student_id == student_id,
            Grade.evaluation_id.in_(eval_ids),
        )
    )).scalars().all() if eval_ids else []

    # Subject names for grouping by matière
    from app.models.class_ import Subject
    subject_ids = list({e.subject_id for e in evaluations if e.subject_id})
    subjects = {}
    if subject_ids:
        sub_rows = (await db.execute(
            select(Subject).where(Subject.id.in_(subject_ids))
        )).scalars().all()
        subjects = {s.id: s.name for s in sub_rows}

    result = []
    for g in grades:
        ev = eval_lookup.get(g.evaluation_id)
        if ev:
            result.append({
                "evaluation_name": ev.name,
                "subject": subjects.get(ev.subject_id, ""),
                "assessment_type": ev.assessment_type,
                "period": ev.period,
                "period_id": ev.academic_period_id,
                "date": str(ev.date),
                "grade": g.grade,
                "max_grade": ev.max_grade,
                "coefficient": ev.coefficient,
                "comment": g.comment,
            })

    return {
        "student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"},
        "grades": result,
    }


# --- Child Attendance ---


@router.get("/children/{student_id}/attendance")
async def child_attendance(
    student_id: int,
    period: str | None = None,
    user: User = Depends(require_permission("attendance.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get attendance for a child — only if parent is linked."""
    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    query = select(Attendance).where(
        Attendance.student_id == student_id,
        Attendance.school_id == school_id,
    )
    if period:
        query = query.where(Attendance.period == period)

    records = (await db.execute(
        query.order_by(Attendance.date.desc())
    )).scalars().all()

    return {
        "student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"},
        "attendance": [
            {
                "date": str(a.date),
                "status": a.status.value,
                "minutes_late": a.minutes_late,
                "is_justified": a.is_justified,
                "justification": a.justification,
            }
            for a in records
        ],
    }


# --- Child Payments ---


@router.get("/children/{student_id}/payments")
async def child_payments(
    student_id: int,
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get payment summary for a child — only if parent is linked."""
    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    # Get payments
    payments = (await db.execute(
        select(Payment).where(
            Payment.student_id == student_id,
            Payment.school_id == school_id,
            Payment.status == PaymentStatus.CONFIRMED,
        ).order_by(Payment.paid_at.desc())
    )).scalars().all()

    total_paid = sum(p.amount for p in payments)

    # Get obligations from enrolled class (détail par frais + échéances)
    from app.services import fee_service
    fees = await fee_service.student_fee_summary(db, school_id, student_id)

    return {
        "student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"},
        "total_owed": fees.get("total_owed", 0),
        "total_paid": fees.get("total_paid", 0),
        "balance": fees.get("balance", 0),
        "items": fees.get("items", []),
        "overdue": fees.get("overdue", []),
        "payments": [
            {
                "id": p.id, "amount": p.amount,
                "method": p.payment_method,
                "date": str(p.paid_at),
                "reference": p.transaction_id,
                "receipt_url": f"/api/payments/{p.id}/receipt",
            }
            for p in payments
        ],
    }


# --- Child Discipline ---


@router.get("/children/{student_id}/discipline")
async def child_discipline(
    student_id: int,
    period: str = Query(..., pattern="^(T[123]|S[12])$"),
    academic_year: str = Query("2025-2026"),
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get discipline records for a child — only if parent is linked."""
    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    from app.models.discipline import DisciplinaryRecord, DisciplinaryRuleSet
    from app.services.discipline_service import get_total_deductions, get_student_records

    total = await get_total_deductions(db, school_id, student_id, period, academic_year)
    records = await get_student_records(db, school_id, student_id, period, academic_year)

    return {
        "student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"},
        "period": period,
        "total_deductions": total,
        "records": [
            {
                "id": r.id,
                "incident_type": r.incident_type,
                "points_deducted": r.points_deducted,
                "source": r.source,
                "date": r.date.isoformat() if r.date else None,
                "note": r.note,
                "status": r.status,
            }
            for r in records
        ],
    }


# --- Child Summary (dashboard) ---


@router.get("/children/{student_id}/summary")
async def child_summary(
    student_id: int,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate summary for the parent dashboard."""
    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()
    class_name = None
    class_id = None
    if enrollment:
        cls = (await db.execute(select(Class).where(Class.id == enrollment.class_id))).scalar_one_or_none()
        class_name = cls.name if cls else None
        class_id = enrollment.class_id

    # Grades
    eval_query = select(Evaluation).where(
        Evaluation.class_id == class_id,
        Evaluation.school_id == school_id,
    ) if class_id else select(Evaluation).where(Evaluation.id == -1)
    evaluations = (await db.execute(eval_query)).scalars().all()
    eval_ids = [e.id for e in evaluations]
    grades = (await db.execute(
        select(Grade).where(Grade.student_id == student_id, Grade.evaluation_id.in_(eval_ids))
    )).scalars().all() if eval_ids else []
    avg = round(sum(g.grade for g in grades) / len(grades), 1) if grades else None

    # Attendance
    att = (await db.execute(
        select(Attendance).where(Attendance.student_id == student_id, Attendance.school_id == school_id)
    )).scalars().all()
    present_count = sum(1 for a in att if a.status == StatutPresence.PRESENT)
    absent_count = sum(1 for a in att if a.status == StatutPresence.ABSENT)
    late_count = sum(1 for a in att if a.status == StatutPresence.LATE)
    unjustified = sum(1 for a in att if a.status == StatutPresence.ABSENT and not a.is_justified)

    # Payments
    payments = (await db.execute(
        select(Payment).where(Payment.student_id == student_id, Payment.school_id == school_id, Payment.status == PaymentStatus.CONFIRMED)
    )).scalars().all()
    total_paid = sum(p.amount for p in payments)
    total_owed = 0
    if enrollment:
        obligations = (await db.execute(
            select(FeeObligation).where(FeeObligation.class_id == class_id, FeeObligation.is_active == True)  # noqa: E712
        )).scalars().all()
        total_owed = sum(o.amount for o in obligations)

    # Unread notifications
    from app.models.notification import Notification
    unread = (await db.execute(
        select(func.count(Notification.id)).where(
            Notification.school_id == school_id,
            Notification.recipient_id == user.id,
            Notification.is_read == False,  # noqa: E712
        )
    )).scalar() or 0

    return {
        "student": {"id": student.id, "first_name": student.first_name, "last_name": student.last_name, "class_name": class_name, "matricule": student.matricule},
        "grades": {"count": len(grades), "average": avg},
        "attendance": {"present": present_count, "absent": absent_count, "late": late_count, "unjustified": unjustified, "total": len(att)},
        "payments": {"total_paid": total_paid, "total_owed": total_owed, "balance": total_owed - total_paid},
        "unread_notifications": unread,
    }


# --- Justify Absence ---


@router.post("/children/{student_id}/justify-absence")
async def justify_absence(
    student_id: int,
    body: dict,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Submit an absence justification from a parent."""
    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    absence_date = body.get("date")
    justification_text = body.get("justification", "")
    if not absence_date or not justification_text:
        raise HTTPException(status_code=400, detail="Date et motif requis")

    record = (await db.execute(
        select(Attendance).where(
            Attendance.student_id == student_id,
            Attendance.school_id == school_id,
            Attendance.date == absence_date,
            Attendance.status == StatutPresence.ABSENT,
        )
    )).scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Absence introuvable")

    record.is_justified = True
    record.justification = justification_text
    await db.commit()

    return {"message": "Justification enregistrée", "date": str(record.date)}


# --- Child Bulletins ---


@router.get("/children/{student_id}/bulletins")
async def child_bulletins(
    student_id: int,
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get published bulletins for a child — only if parent is linked."""
    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    bulletins = (await db.execute(
        select(Bulletin).where(
            Bulletin.student_id == student_id,
            Bulletin.school_id == school_id,
            Bulletin.status == "published",
        ).order_by(Bulletin.period.desc())
    )).scalars().all()

    import json
    from app.services.report_card_service import period_label as _plabel
    # period_type de la classe pour libeller correctement les périodes
    class_ids = list({b.class_id for b in bulletins})
    pt_map = {}
    if class_ids:
        for c in (await db.execute(
            select(Class).where(Class.id.in_(class_ids))
        )).scalars().all():
            pt_map[c.id] = c.period_type
    return {
        "student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"},
        "bulletins": [
            {
                "id": b.id,
                "period": b.period,
                "period_label": _plabel(b.period, pt_map.get(b.class_id, "trimestre")),
                "academic_year": b.academic_year,
                "overall_average": b.overall_average,
                "rank": b.rank,
                "total_students": b.total_students,
                "decision": b.decision,
                "data": json.loads(b.data_json) if b.data_json else {},
                "published_at": str(b.published_at),
            }
            for b in bulletins
        ],
    }


# --- Child Timetable ---


@router.get("/children/{student_id}/timetable")
async def child_timetable(
    student_id: int,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get timetable for a child's class."""
    from app.models.timetable import Timetable
    from app.models.class_ import Subject

    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    # Find student's class
    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.school_id == school_id,
        )
    )).scalar_one_or_none()

    if not enrollment:
        return {"student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"}, "timetable": []}

    entries = (await db.execute(
        select(Timetable, Subject.name.label("subject_name"), User.first_name.label("teacher_name"), User.last_name.label("teacher_last"))
        .join(Subject, Timetable.subject_id == Subject.id)
        .outerjoin(User, Timetable.teacher_id == User.id)
        .where(
            Timetable.class_id == enrollment.class_id,
            Timetable.school_id == school_id,
            Timetable.is_active == True,
        ).order_by(Timetable.day_of_week, Timetable.start_time)
    )).all()

    day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    return {
        "student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"},
        "timetable": [
            {
                "id": t.id,
                "day": day_names[t.day_of_week] if t.day_of_week < 7 else str(t.day_of_week),
                "day_of_week": t.day_of_week,
                "start_time": str(t.start_time),
                "end_time": str(t.end_time),
                "subject": sn,
                "teacher": f"{tn} {tln}".strip() if tn else "Non assigné",
                "room": t.room or "",
            }
            for t, sn, tn, tln in entries
        ],
    }


# --- Child Evaluations ---


@router.get("/children/{student_id}/evaluations")
async def child_evaluations(
    student_id: int,
    period_id: int | None = Query(None),
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get evaluations (past + upcoming) for a child's class."""
    from app.models.class_ import Subject
    from datetime import date as date_cls

    school_id = get_school_id(user)
    student = await _verify_parent_child(db, user.id, student_id, school_id)

    # Student's current class
    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()
    if not enrollment:
        return {"student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"}, "evaluations": []}

    eval_query = select(Evaluation).where(
        Evaluation.class_id == enrollment.class_id,
        Evaluation.school_id == school_id,
    )
    if period_id:
        eval_query = eval_query.where(Evaluation.academic_period_id == period_id)
    evaluations = (await db.execute(eval_query.order_by(Evaluation.date))).scalars().all()

    # Student's existing grades
    eval_ids = [e.id for e in evaluations]
    grades = (await db.execute(
        select(Grade).where(Grade.student_id == student_id, Grade.evaluation_id.in_(eval_ids))
    )).scalars().all() if eval_ids else []
    grade_map = {g.evaluation_id: g for g in grades}

    # Subject names
    subject_ids = list({e.subject_id for e in evaluations if e.subject_id})
    subjects = {}
    if subject_ids:
        sub_rows = (await db.execute(
            select(Subject).where(Subject.id.in_(subject_ids))
        )).scalars().all()
        subjects = {s.id: s.name for s in sub_rows}

    today = date_cls.today()
    items = []
    for ev in evaluations:
        g = grade_map.get(ev.id)
        if g:
            status = "completed"
        elif ev.date and ev.date >= today:
            status = "upcoming"
        else:
            status = "pending"  # passée mais non notée
        items.append({
            "id": g.id if g else 0,
            "evaluation_id": ev.id,
            "subject": subjects.get(ev.subject_id, ""),
            "type": ev.assessment_type,
            "name": ev.name,
            "date": str(ev.date) if ev.date else None,
            "grade": g.grade if g else None,
            "max_score": ev.max_grade,
            "coefficient": ev.coefficient,
            "period": ev.period,
            "period_id": ev.academic_period_id,
            "is_published": ev.is_published,
            "status": status,
        })

    return {
        "student": {"id": student.id, "name": f"{student.first_name} {student.last_name}"},
        "evaluations": items,
    }


# --- Parent Messages ---


@router.get("/messages")
async def parent_messages(
    user: User = Depends(require_permission("message.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get conversations for parent."""
    from app.models.message import Conversation, ConversationParticipant, Message

    school_id = get_school_id(user)

    # Get conversations where parent is a participant
    participations = (await db.execute(
        select(ConversationParticipant, Conversation)
        .join(Conversation, ConversationParticipant.conversation_id == Conversation.id)
        .where(
            ConversationParticipant.user_id == user.id,
            Conversation.school_id == school_id,
            Conversation.is_archived == False,
        ).order_by(Conversation.created_at.desc())
    )).all()

    conversations = []
    for cp, conv in participations:
        # Get last message
        last_msg = (await db.execute(
            select(Message).where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc()).limit(1)
        )).scalar_one_or_none()

        # Get other participants
        others = (await db.execute(
            select(ConversationParticipant, User)
            .join(User, ConversationParticipant.user_id == User.id)
            .where(
                ConversationParticipant.conversation_id == conv.id,
                ConversationParticipant.user_id != user.id,
            )
        )).all()

        other_name = ", ".join([f"{u.first_name} {u.last_name}" for _, u in others]) or "Administration"
        unread = (await db.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conv.id,
                Message.sender_id != user.id,
                Message.created_at > (cp.last_read_at or datetime.min),
            )
        )).scalar() or 0

        conversations.append({
            "id": conv.id,
            "subject": conv.subject or other_name,
            "other_user": other_name,
            "last_message": last_msg.content[:100] if last_msg else "",
            "last_message_date": str(last_msg.created_at) if last_msg else str(conv.created_at),
            "unread_count": unread,
            "type": conv.type,
        })

    return {"conversations": conversations}


# --- Send Message ---


@router.post("/messages")
async def send_message(
    data: dict,
    user: User = Depends(require_permission("message.send")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a message in a conversation or create new one."""
    from app.models.message import Conversation, ConversationParticipant, Message

    school_id = get_school_id(user)
    content = data.get("content", "").strip()
    conversation_id = data.get("conversation_id")
    recipient_id = data.get("recipient_id")
    subject = data.get("subject")

    if not content:
        raise HTTPException(status_code=400, detail="Le message ne peut pas être vide")

    if conversation_id:
        # Verify parent is participant
        is_part = (await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user.id,
            )
        )).scalar_one_or_none()
        if not is_part:
            raise HTTPException(status_code=403, detail="Accès refusé")
    elif recipient_id:
        # Create new conversation
        conv = Conversation(
            school_id=school_id,
            type="direct",
            subject=subject,
            created_by=user.id,
        )
        db.add(conv)
        await db.flush()
        db.add(ConversationParticipant(conversation_id=conv.id, user_id=user.id))
        db.add(ConversationParticipant(conversation_id=conv.id, user_id=recipient_id))
        conversation_id = conv.id
    else:
        raise HTTPException(status_code=400, detail="conversation_id ou recipient_id requis")

    msg = Message(
        conversation_id=conversation_id,
        sender_id=user.id,
        content=content,
    )
    db.add(msg)
    await db.commit()

    return {"message": "Envoyé", "conversation_id": conversation_id}


# --- Parent Notifications ---


@router.get("/notifications")
async def parent_notifications(
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get notifications for parent."""
    from app.models.notification import Notification

    school_id = get_school_id(user)

    notifs = (await db.execute(
        select(Notification).where(
            Notification.recipient_id == user.id,
            Notification.school_id == school_id,
        ).order_by(Notification.created_at.desc()).limit(50)
    )).scalars().all()

    return {
        "notifications": [
            {
                "id": n.id,
                "subject": n.subject or "",
                "body": n.body,
                "category": n.category.value if hasattr(n.category, 'value') else str(n.category),
                "is_read": n.is_read,
                "created_at": str(n.created_at),
            }
            for n in notifs
        ],
        "unread_count": sum(1 for n in notifs if not n.is_read),
    }


# --- Mark Notification Read ---


@router.post("/notifications/{notif_id}/read")
async def mark_notification_read(
    notif_id: int,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.models.notification import Notification

    notif = (await db.execute(
        select(Notification).where(
            Notification.id == notif_id,
            Notification.recipient_id == user.id,
        )
    )).scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification introuvable")

    notif.is_read = True
    notif.read_at = func.now()
    await db.commit()
    return {"message": "Notification marquée comme lue"}
