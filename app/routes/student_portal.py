"""Yiriba SaaS — Student Portal routes.

L'élève ne voit QUE ses propres données.
Jamais de modification possible — lecture seule.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.models.bulletin import Bulletin
from app.models.class_ import Class, Enrollment, TeacherClass, Subject
from app.models.grade import Evaluation, Grade
from app.models.attendance import Attendance
from app.models.payment import Payment, FeeObligation, PaymentStatus
from app.models.student import Student
from app.models.parent_student import ParentStudent
from app.models.user import User, UserRole

router = APIRouter(prefix="/api/student", tags=["student_portal"])


# --- Helper: get student from user ---


async def _get_my_student(db: AsyncSession, user: User, school_id: int) -> Student:
    """Get the student record explicitly linked to this user.

    Par sécurité, aucun matching par nom/email/numéro unique de l'école :
    seule la liaison explicite (ParentStudent ou Student.user_id) est
    acceptée. Sinon 404 — jamais les données d'un autre élève.
    """
    # Parent : via la table de liaison parent ↔ élève
    if user.role_type == UserRole.PARENT:
        link = (await db.execute(
            select(ParentStudent).where(ParentStudent.parent_id == user.id)
        )).scalar_one_or_none()
        if link:
            student = (await db.execute(
                select(Student).where(
                    Student.id == link.student_id,
                    Student.school_id == school_id,
                )
            )).scalar_one_or_none()
            if student:
                return student

    # Élève : via le lien explicite Student.user_id
    student = (await db.execute(
        select(Student).where(
            Student.user_id == user.id,
            Student.school_id == school_id,
        )
    )).scalar_one_or_none()
    if student is not None:
        return student

    raise HTTPException(status_code=404, detail="Aucun profil élève lié à ce compte")


# --- My Info ---


@router.get("/me")
async def my_info(
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get my student information."""
    school_id = get_school_id(user)
    student = await _get_my_student(db, user, school_id)

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

    return {
        "id": student.id,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "matricule": student.matricule,
        "class_name": class_name,
        "gender": student.gender,
        "status": student.status.value,
    }


# --- My Grades ---


@router.get("/me/grades")
async def my_grades(
    period: str | None = None,
    academic_period_id: int | None = None,
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get my grades — only my own data."""
    school_id = get_school_id(user)
    student = await _get_my_student(db, user, school_id)

    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()
    if not enrollment:
        return {"grades": []}

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
            Grade.student_id == student.id,
            Grade.evaluation_id.in_(eval_ids),
        )
    )).scalars().all() if eval_ids else []

    result = []
    for g in grades:
        ev = eval_lookup.get(g.evaluation_id)
        if ev:
            result.append({
                "evaluation_name": ev.name,
                "assessment_type": ev.assessment_type,
                "period": ev.period,
                "grade": g.grade,
                "max_grade": ev.max_grade,
                "coefficient": ev.coefficient,
                "comment": g.comment,
            })

    return {"grades": result}


# --- My Attendance ---


@router.get("/me/attendance")
async def my_attendance(
    period: str | None = None,
    user: User = Depends(require_permission("attendance.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get my attendance — only my own data."""
    school_id = get_school_id(user)
    student = await _get_my_student(db, user, school_id)

    query = select(Attendance).where(
        Attendance.student_id == student.id,
        Attendance.school_id == school_id,
    )
    if period:
        query = query.where(Attendance.period == period)

    records = (await db.execute(
        query.order_by(Attendance.date.desc())
    )).scalars().all()

    return {
        "attendance": [
            {
                "date": str(a.date),
                "status": a.status.value,
                "minutes_late": a.minutes_late,
                "is_justified": a.is_justified,
            }
            for a in records
        ],
    }


# --- My Bulletins ---


@router.get("/me/bulletins")
async def my_bulletins(
    user: User = Depends(require_permission("bulletin.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get my published bulletins — only my own data."""
    school_id = get_school_id(user)
    student = await _get_my_student(db, user, school_id)

    bulletins = (await db.execute(
        select(Bulletin).where(
            Bulletin.student_id == student.id,
            Bulletin.school_id == school_id,
            Bulletin.status == "published",
        ).order_by(Bulletin.period.desc())
    )).scalars().all()

    from app.services.report_card_service import period_label as _plabel
    from app.models.class_ import Class
    pt = "trimestre"
    if bulletins:
        cls = (await db.execute(
            select(Class).where(Class.id == bulletins[0].class_id)
        )).scalar_one_or_none()
        if cls:
            pt = cls.period_type or "trimestre"
    return {
        "bulletins": [
            {
                "id": b.id,
                "period": b.period,
                "period_label": _plabel(b.period, pt),
                "academic_year": b.academic_year,
                "overall_average": b.overall_average,
                "rank": b.rank,
                "total_students": b.total_students,
                "decision": b.decision,
                "data": json.loads(b.data_json) if b.data_json else {},
            }
            for b in bulletins
        ],
    }


# --- My Payments ---


@router.get("/me/payments")
async def my_payments(
    user: User = Depends(require_permission("payment.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get my payment summary — only my own data, read-only."""
    school_id = get_school_id(user)
    student = await _get_my_student(db, user, school_id)

    payments = (await db.execute(
        select(Payment).where(
            Payment.student_id == student.id,
            Payment.school_id == school_id,
            Payment.status == PaymentStatus.CONFIRMED,
        ).order_by(Payment.paid_at.desc())
    )).scalars().all()

    total_paid = sum(p.amount for p in payments)

    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()

    total_owed = 0
    if enrollment:
        obligations = (await db.execute(
            select(FeeObligation).where(
                FeeObligation.class_id == enrollment.class_id,
                FeeObligation.is_active == True,  # noqa: E712
            )
        )).scalars().all()
        total_owed = sum(o.amount for o in obligations)

    return {
        "total_owed": total_owed,
        "total_paid": total_paid,
        "balance": total_owed - total_paid,
        "payments": [
            {
                "id": p.id, "amount": p.amount,
                "method": p.payment_method,
                "date": str(p.paid_at),
            }
            for p in payments
        ],
    }


# --- My Timetable ---


@router.get("/me/timetable")
async def my_timetable(
    user: User = Depends(require_permission("grade.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get my class timetable from TeacherClass assignments."""
    school_id = get_school_id(user)
    student = await _get_my_student(db, user, school_id)

    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student.id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()
    if not enrollment:
        return {"timetable": []}

    teacher_classes = (await db.execute(
        select(TeacherClass).where(
            TeacherClass.class_id == enrollment.class_id,
            TeacherClass.school_id == school_id,
        )
    )).scalars().all()

    timetable = []
    for tc in teacher_classes:
        subj = (await db.execute(
            select(Subject).where(Subject.id == tc.subject_id)
        )).scalar_one_or_none()
        timetable.append({
            "subject_name": subj.name if subj else "?",
            "subject_id": tc.subject_id,
            "is_primary": tc.is_primary,
        })

    return {"timetable": timetable}
