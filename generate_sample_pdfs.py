"""Generate sample PDFs with test data for visual inspection."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import Base, get_db, engine
from app.core.seeds import seed_permissions, seed_subscription_plans
from app.models.class_ import Class, ClassSubject, Enrollment, Subject
from app.models.grade import Evaluation, Grade
from app.models.payment import FeeObligation, Payment, PaymentStatus
from app.models.school import School
from app.models.student import Student
from app.models.user import User
from app.services.pdf_service import generate_bulletin_pdf, generate_receipt_pdf
from sqlalchemy import select
from datetime import date
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession


async def main():
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        await seed_permissions(db)
        await seed_subscription_plans(db)

        # ── Create school ───────────────────────────────────────
        school = School(
            name="Collège Yiriba Ouaga",
            slug="college-yiriba-ouaga",
            short_name="CYO",
            school_type="college",
            email="contact@yiriba-ouaga.com",
            phone="+226 70 12 34 56",
            address="Avenue de la Révolution, Secteur 15",
            city="Ouagadougou",
            country="Burkina Faso",
            motto="L'excellence par l'éducation",
        )
        db.add(school)
        await db.flush()

        # ── Create admin user ───────────────────────────────────
        from app.core.security import hash_password
        admin = User(
            school_id=school.id,
            email="directeur@yiriba.com",
            first_name="Moussa",
            last_name="Ouedraogo",
            password_hash=hash_password("Yiriba@123"),
            role_type="admin",
            status="active",
        )
        db.add(admin)
        await db.flush()

        # ── Create class ────────────────────────────────────────
        cls = Class(
            school_id=school.id,
            name="6ème A",
            period_type="trimestre",
            capacity=45,
        )
        db.add(cls)
        await db.flush()

        # ── Create subjects ─────────────────────────────────────
        subjects_data = [
            ("Mathématiques", 4),
            ("Français", 3),
            ("Physique-Chimie", 3),
            ("Histoire-Géographie", 2),
            ("Anglais", 2),
            ("SVT", 2),
            ("EPS", 1),
            ("Informatique", 1),
        ]
        subjects = []
        for name, coeff in subjects_data:
            subj = Subject(school_id=school.id, name=name, coefficient=coeff)
            db.add(subj)
            await db.flush()
            subjects.append(subj)
            # Link to class
            cs = ClassSubject(school_id=school.id, class_id=cls.id, subject_id=subj.id, coefficient=coeff)
            db.add(cs)

        await db.flush()

        # ── Create students ─────────────────────────────────────
        students_data = [
            ("Awa", "Ouedraogo", "F", "2012-05-15"),
            ("Ibrahim", "Diallo", "M", "2011-08-22"),
            ("Fatima", "Traoré", "F", "2012-01-10"),
            ("Moussa", "Kabore", "M", "2012-03-05"),
            ("Aminata", "Sanou", "F", "2011-11-18"),
        ]
        students = []
        for first, last, gender, bdate in students_data:
            st = Student(
                school_id=school.id,
                first_name=first,
                last_name=last,
                gender=gender,
                birth_date=date.fromisoformat(bdate),
                matricule=f"CYO-2025-{len(students)+1:03d}",
            )
            db.add(st)
            await db.flush()
            students.append(st)
            # Enroll
            enr = Enrollment(
                school_id=school.id,
                student_id=st.id,
                class_id=cls.id,
                status="active",
            )
            db.add(enr)

        await db.flush()

        # ── Create evaluations + grades ─────────────────────────
        import random
        random.seed(42)

        eval_grades = {
            "Mathématiques": {"devoir1": [14, 12, 16, 11, 15], "devoir2": [15, 13, 14, 12, 16], "composition": [16, 14, 17, 13, 15]},
            "Français": {"devoir1": [12, 14, 13, 10, 11], "devoir2": [13, 15, 14, 11, 12], "composition": [14, 16, 15, 12, 13]},
            "Physique-Chimie": {"devoir1": [11, 10, 13, 9, 12], "devoir2": [12, 11, 14, 10, 13], "composition": [13, 12, 15, 11, 14]},
            "Histoire-Géographie": {"devoir1": [13, 11, 15, 10, 14], "devoir2": [14, 12, 16, 11, 15], "composition": [15, 13, 17, 12, 16]},
            "Anglais": {"devoir1": [10, 12, 11, 8, 9], "devoir2": [11, 13, 12, 9, 10], "composition": [12, 14, 13, 10, 11]},
            "SVT": {"devoir1": [12, 13, 14, 11, 12], "devoir2": [13, 14, 15, 12, 13], "composition": [14, 15, 16, 13, 14]},
            "EPS": {"devoir1": [15, 14, 16, 13, 15], "devoir2": [16, 15, 17, 14, 16], "composition": [17, 16, 18, 15, 17]},
            "Informatique": {"devoir1": [16, 15, 17, 14, 16], "devoir2": [17, 16, 18, 15, 17], "composition": [18, 17, 19, 16, 18]},
        }

        for subj in subjects:
            if subj.name not in eval_grades:
                continue
            for atype, grades_list in eval_grades[subj.name].items():
                ev = Evaluation(
                    school_id=school.id,
                    class_id=cls.id,
                    subject_id=subj.id,
                    teacher_id=admin.id,
                    name=f"{atype.replace('devoir', 'Devoir ').replace('composition', 'Composition')} - {subj.name}",
                    assessment_type=atype,
                    period="T1",
                    academic_year="2025-2026",
                    max_grade=20,
                    coefficient=1,
                    date=date.fromisoformat("2025-10-01"),
                    is_published=True,
                )
                db.add(ev)
                await db.flush()

                for i, st in enumerate(students):
                    grade = Grade(
                        school_id=school.id,
                        evaluation_id=ev.id,
                        student_id=st.id,
                        teacher_id=admin.id,
                        grade=grades_list[i],
                        status="graded",
                    )
                    db.add(grade)

        await db.flush()

        # ── Create payment for student 1 ────────────────────────
        obligation = FeeObligation(
            school_id=school.id,
            class_id=cls.id,
            name="Frais d'inscription T1",
            amount=25000,
            period="T1",
            academic_year="2025-2026",
        )
        db.add(obligation)
        await db.flush()

        payment = Payment(
            school_id=school.id,
            student_id=students[0].id,
            obligation_id=obligation.id,
            recorded_by=admin.id,
            amount=25000,
            payment_method="cash",
            status=PaymentStatus.CONFIRMED,
        )
        db.add(payment)
        await db.flush()

        # ── Discipline rules + records ──────────────────────────
        from app.models.discipline import DisciplinaryRuleSet, DisciplinaryRecord
        from app.services.discipline_service import seed_default_rules

        await seed_default_rules(db, school.id)
        await db.flush()

        # Set school to conduct mode (default)
        school.discipline_mode = "conduct"

        # Add some disciplinary records for student 1
        record1 = DisciplinaryRecord(
            school_id=school.id, student_id=students[0].id,
            period="T1", academic_year="2025-2026",
            incident_type="absence_non_justifiee", points_deducted=0.5,
            source="auto", recorded_by=admin.id, date=date(2025, 10, 5),
        )
        record2 = DisciplinaryRecord(
            school_id=school.id, student_id=students[0].id,
            period="T1", academic_year="2025-2026",
            incident_type="retard", points_deducted=0.25,
            source="manual", recorded_by=admin.id, date=date(2025, 10, 12),
            note="Retard répété",
        )
        db.add(record1)
        db.add(record2)
        await db.flush()

        await db.commit()

        # ── Generate PDFs ───────────────────────────────────────
        output_dir = os.path.join(os.path.dirname(__file__), "sample_pdfs")
        os.makedirs(output_dir, exist_ok=True)

        # Generate bulletin for student 1
        print("Generating bulletin PDF...")
        bulletin_pdf = await generate_bulletin_pdf(
            db, students[0].id, cls.id, "T1", "2025-2026"
        )
        bulletin_path = os.path.join(output_dir, "sample_bulletin.pdf")
        with open(bulletin_path, "wb") as f:
            f.write(bulletin_pdf)
        print(f"  -> {bulletin_path} ({len(bulletin_pdf)} bytes)")

        # Generate receipt for payment
        print("Generating receipt PDF...")
        receipt_pdf = await generate_receipt_pdf(db, payment.id)
        receipt_path = os.path.join(output_dir, "sample_receipt.pdf")
        with open(receipt_path, "wb") as f:
            f.write(receipt_pdf)
        print(f"  -> {receipt_path} ({len(receipt_pdf)} bytes)")

        print("\nDone! Check the sample_pdfs/ folder.")


if __name__ == "__main__":
    asyncio.run(main())
