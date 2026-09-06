"""Yiriba SaaS — Ownership Service.

Centralise la logique de filtrage par ownership pour tous les portails.
Un enseignant ne voit que ses classes, un parent que ses enfants, etc.
"""

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.models.student import Student
from app.models.class_ import Class, Enrollment
from app.models.grade import Grade, Evaluation
from app.models.attendance import Attendance
from app.models.payment import Payment
from app.models.parent_student import ParentStudent
from app.models.class_ import TeacherClass


class OwnershipService:
    """Service de filtrage par ownership pour les requêtes multi-portails."""

    @staticmethod
    def get_school_id(user: User) -> int:
        """Extract school_id from the JWT-decoded user."""
        school_id = getattr(user, "_school_id_from_token", None)
        if school_id is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="École non définie dans le token")
        return int(school_id)

    # ── Students ───────────────────────────────────────────────────

    @staticmethod
    async def filter_students_query(
        query,
        user: User,
        db: AsyncSession,
        school_id: int,
    ):
        """Filter student query based on user role and ownership."""
        if user.role_type == UserRole.ADMIN:
            return query.where(Student.school_id == school_id)

        if user.role_type == UserRole.TEACHER:
            # Teacher sees students in their assigned classes
            subquery = select(Enrollment.student_id).join(
                Class, Class.id == Enrollment.class_id
            ).join(
                TeacherClass, TeacherClass.class_id == Class.id
            ).where(
                TeacherClass.teacher_id == user.id,
                TeacherClass.school_id == school_id,
                Enrollment.status == "active",
            ).distinct()
            return query.where(
                Student.school_id == school_id,
                Student.id.in_(subquery),
            )

        if user.role_type == UserRole.PARENT:
            # Parent sees only their children
            subquery = select(ParentStudent.student_id).where(
                ParentStudent.parent_id == user.id,
            )
            return query.where(
                Student.school_id == school_id,
                Student.id.in_(subquery),
            )

        if user.role_type == UserRole.STUDENT:
            # Student sees only themselves
            return query.where(
                Student.school_id == school_id,
                Student.user_id == user.id,
            )

        return query.where(Student.school_id == school_id)

    # ── Grades ─────────────────────────────────────────────────────

    @staticmethod
    async def filter_grades_query(
        query,
        user: User,
        db: AsyncSession,
        school_id: int,
    ):
        """Filter grade query based on user role and ownership."""
        if user.role_type == UserRole.ADMIN:
            return query.where(Grade.school_id == school_id)

        if user.role_type == UserRole.TEACHER:
            # Teacher sees grades for evaluations in their classes
            subquery = select(Grade.id).join(
                Evaluation, Evaluation.id == Grade.evaluation_id
            ).join(
                Class, Class.id == Evaluation.class_id
            ).join(
                TeacherClass, TeacherClass.class_id == Class.id
            ).where(
                TeacherClass.teacher_id == user.id,
                TeacherClass.school_id == school_id,
            ).distinct()
            return query.where(
                Grade.school_id == school_id,
                Grade.id.in_(subquery),
            )

        if user.role_type == UserRole.PARENT:
            # Parent sees grades for their children
            subquery = select(Grade.id).join(
                Student, Student.id == Grade.student_id
            ).join(
                ParentStudent, ParentStudent.student_id == Student.id
            ).where(
                ParentStudent.parent_id == user.id,
            ).distinct()
            return query.where(
                Grade.school_id == school_id,
                Grade.id.in_(subquery),
            )

        if user.role_type == UserRole.STUDENT:
            # Student sees only their own grades
            return query.where(
                Grade.school_id == school_id,
                Grade.student_id == select(Student.id).where(
                    Student.user_id == user.id
                ).correlate_except(Student).scalar_subquery(),
            )

        return query.where(Grade.school_id == school_id)

    # ── Attendance ─────────────────────────────────────────────────

    @staticmethod
    async def filter_attendance_query(
        query,
        user: User,
        db: AsyncSession,
        school_id: int,
    ):
        """Filter attendance query based on user role and ownership."""
        from app.models.class_ import Enrollment as EnrollmentModel

        if user.role_type == UserRole.ADMIN:
            return query.where(Attendance.school_id == school_id)

        if user.role_type == UserRole.TEACHER:
            # Teacher sees attendance for their classes
            subquery = select(Attendance.id).join(
                Student, Student.id == Attendance.student_id
            ).join(
                EnrollmentModel, EnrollmentModel.student_id == Student.id
            ).join(
                Class, Class.id == EnrollmentModel.class_id
            ).join(
                TeacherClass, TeacherClass.class_id == Class.id
            ).where(
                TeacherClass.teacher_id == user.id,
                TeacherClass.school_id == school_id,
            ).distinct()
            return query.where(
                Attendance.school_id == school_id,
                Attendance.id.in_(subquery),
            )

        if user.role_type == UserRole.PARENT:
            # Parent sees attendance for their children
            subquery = select(Attendance.id).join(
                Student, Student.id == Attendance.student_id
            ).join(
                ParentStudent, ParentStudent.student_id == Student.id
            ).where(
                ParentStudent.parent_id == user.id,
            ).distinct()
            return query.where(
                Attendance.school_id == school_id,
                Attendance.id.in_(subquery),
            )

        if user.role_type == UserRole.STUDENT:
            # Student sees only their own attendance
            return query.where(
                Attendance.school_id == school_id,
                Attendance.student_id == select(Student.id).where(
                    Student.user_id == user.id
                ).correlate_except(Student).scalar_subquery(),
            )

        return query.where(Attendance.school_id == school_id)

    # ── Payments ───────────────────────────────────────────────────

    @staticmethod
    async def filter_payments_query(
        query,
        user: User,
        db: AsyncSession,
        school_id: int,
    ):
        """Filter payment query based on user role and ownership."""
        from app.models.payment import FeeObligation

        if user.role_type == UserRole.ADMIN:
            return query.where(Payment.school_id == school_id)

        if user.role_type == UserRole.PARENT:
            # Parent sees payments for their children
            subquery = select(Payment.id).join(
                FeeObligation, FeeObligation.id == Payment.fee_obligation_id
            ).join(
                Student, Student.id == FeeObligation.student_id
            ).join(
                ParentStudent, ParentStudent.student_id == Student.id
            ).where(
                ParentStudent.parent_id == user.id,
            ).distinct()
            return query.where(
                Payment.school_id == school_id,
                Payment.id.in_(subquery),
            )

        if user.role_type == UserRole.STUDENT:
            # Student sees only their own payments
            subquery = select(Payment.id).join(
                FeeObligation, FeeObligation.id == Payment.fee_obligation_id
            ).join(
                Student, Student.id == FeeObligation.student_id
            ).where(
                Student.user_id == user.id,
            ).distinct()
            return query.where(
                Payment.school_id == school_id,
                Payment.id.in_(subquery),
            )

        return query.where(Payment.school_id == school_id)

    # ── Bulletins ──────────────────────────────────────────────────

    @staticmethod
    async def filter_bulletins_query(
        query,
        user: User,
        db: AsyncSession,
        school_id: int,
    ):
        """Filter bulletin query based on user role and ownership."""
        from app.models.bulletin import Bulletin

        if user.role_type == UserRole.ADMIN:
            return query.where(Bulletin.school_id == school_id)

        if user.role_type == UserRole.PARENT:
            # Parent sees bulletins for their children
            subquery = select(Bulletin.id).join(
                Student, Student.id == Bulletin.student_id
            ).join(
                ParentStudent, ParentStudent.student_id == Student.id
            ).where(
                ParentStudent.parent_id == user.id,
            ).distinct()
            return query.where(
                Bulletin.school_id == school_id,
                Bulletin.id.in_(subquery),
            )

        if user.role_type == UserRole.STUDENT:
            # Student sees only their own bulletins
            return query.where(
                Bulletin.school_id == school_id,
                Bulletin.student_id == select(Student.id).where(
                    Student.user_id == user.id
                ).correlate_except(Student).scalar_subquery(),
            )

        return query.where(Bulletin.school_id == school_id)

    # ── Classes ────────────────────────────────────────────────────

    @staticmethod
    async def filter_classes_query(
        query,
        user: User,
        db: AsyncSession,
        school_id: int,
    ):
        """Filter class query based on user role and ownership."""
        if user.role_type == UserRole.ADMIN:
            return query.where(Class.school_id == school_id)

        if user.role_type == UserRole.TEACHER:
            # Teacher sees only their assigned classes
            subquery = select(TeacherClass.class_id).where(
                TeacherClass.teacher_id == user.id,
                TeacherClass.school_id == school_id,
            ).distinct()
            return query.where(
                Class.school_id == school_id,
                Class.id.in_(subquery),
            )

        if user.role_type == UserRole.PARENT:
            # Parent sees classes where their children are enrolled
            subquery = select(Enrollment.class_id).join(
                Student, Student.id == Enrollment.student_id
            ).join(
                ParentStudent, ParentStudent.student_id == Student.id
            ).where(
                ParentStudent.parent_id == user.id,
                Enrollment.status == "active",
            ).distinct()
            return query.where(
                Class.school_id == school_id,
                Class.id.in_(subquery),
            )

        if user.role_type == UserRole.STUDENT:
            # Student sees only their own class
            subquery = select(Enrollment.class_id).join(
                Student, Student.id == Enrollment.student_id
            ).where(
                Student.user_id == user.id,
                Enrollment.status == "active",
            )
            return query.where(
                Class.school_id == school_id,
                Class.id.in_(subquery),
            )

        return query.where(Class.school_id == school_id)

    # ── Evaluations ────────────────────────────────────────────────

    @staticmethod
    async def filter_evaluations_query(
        query,
        user: User,
        db: AsyncSession,
        school_id: int,
    ):
        """Filter evaluation query based on user role and ownership."""
        if user.role_type == UserRole.ADMIN:
            return query.where(Evaluation.school_id == school_id)

        if user.role_type == UserRole.TEACHER:
            # Teacher sees evaluations for their classes
            subquery = select(Evaluation.id).join(
                Class, Class.id == Evaluation.class_id
            ).join(
                TeacherClass, TeacherClass.class_id == Class.id
            ).where(
                TeacherClass.teacher_id == user.id,
                TeacherClass.school_id == school_id,
            ).distinct()
            return query.where(
                Evaluation.school_id == school_id,
                Evaluation.id.in_(subquery),
            )

        return query.where(Evaluation.school_id == school_id)
