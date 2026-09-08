"""Yiriba SaaS — Student service with business logic and ownership filtering.

All queries filter by school_id (tenant isolation).
OwnershipFilter applied based on user role after RBAC check.
Soft delete via StudentStatus — never a hard DELETE.
"""

import csv
import io
import math
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.class_ import Enrollment
from app.models.enums import ParentRole, StudentStatus
from app.models.parent_student import ParentStudent
from app.models.student import Student
from app.models.user import User, UserRole
from app.schemas.student import StudentCreate, StudentUpdate

settings = get_settings()


def _apply_ownership_filter(query: Select, user: User, school_id: int) -> Select:
    """Apply ownership filter to a student query based on user role.

    Called AFTER RBAC permission check.
    - Admin: sees all active students in their school
    - Teacher: sees students in their classes
    - Parent: sees only their children
    - Student: sees only themselves
    """
    query = query.where(Student.school_id == school_id)

    if user.role_type == UserRole.ADMIN:
        return query  # Admin sees all (status filter applied later if provided)

    if user.role_type == UserRole.TEACHER:
        from app.models.class_ import ClassSubject
        teacher_class_ids = select(ClassSubject.class_id).where(
            ClassSubject.teacher_id == user.id
        )
        student_ids_in_classes = select(Enrollment.student_id).where(
            Enrollment.class_id.in_(teacher_class_ids),
            Enrollment.status == "active",
        )
        return query.where(Student.id.in_(student_ids_in_classes))

    if user.role_type == UserRole.PARENT:
        parent_student_ids = select(ParentStudent.student_id).where(
            ParentStudent.parent_id == user.id
        )
        return query.where(Student.id.in_(parent_student_ids))

    if user.role_type == UserRole.STUDENT:
        # L'élève ne voit que la fiche liée à son compte (Student.user_id),
        # jamais via un doublon d'ID (Student.id != User.id).
        return query.where(Student.user_id == user.id)

    return query.where(Student.id == -1)  # Empty by default


async def list_students(
    db: AsyncSession,
    user: User,
    school_id: int,
    page: int = 1,
    per_page: int = 20,
    search: str = "",
    class_id: int | None = None,
    gender: str | None = None,
    status: str | None = None,
    level: str | None = None,
    academic_year: str | None = None,
) -> dict[str, Any]:
    """List students with pagination, search, and ownership filtering."""
    query = select(Student)
    query = _apply_ownership_filter(query, user, school_id)

    # Status filter: explicit override or default ACTIVE
    status_val = None if status == "all" else status
    if status_val:
        query = query.where(Student.status == status_val)
    elif status == "all":
        pass  # Tous les statuts demandé explicitement : aucun filtre
    else:
        # Default: only active students (unless ownership filter already applied)
        if user.role_type == UserRole.ADMIN:
            query = query.where(Student.status == StudentStatus.ACTIVE)

    # Search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                Student.first_name.ilike(search_pattern),
                Student.last_name.ilike(search_pattern),
                Student.matricule.ilike(search_pattern),
            )
        )

    # Class filter (via enrollment)
    if class_id:
        student_ids_in_class = select(Enrollment.student_id).where(
            Enrollment.class_id == class_id,
            Enrollment.status == "active",
        )
        query = query.where(Student.id.in_(student_ids_in_class))

    # Level filter (via enrollment -> class level)
    if level:
        from app.models.class_ import Class as ClassModel
        student_ids_in_level = select(Enrollment.student_id).join(
            ClassModel, ClassModel.id == Enrollment.class_id
        ).where(
            Enrollment.status == "active",
            ClassModel.level == level,
        )
        query = query.where(Student.id.in_(student_ids_in_level))

    # Academic year filter (via enrollment)
    if academic_year:
        from app.models.class_ import Class as ClassModel
        student_ids_in_year = select(Enrollment.student_id).join(
            ClassModel, ClassModel.id == Enrollment.class_id
        ).where(
            Enrollment.status == "active",
            ClassModel.academic_year == academic_year,
        )
        query = query.where(Student.id.in_(student_ids_in_year))

    # Gender filter
    if gender:
        query = query.where(Student.gender == gender)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Pagination
    per_page = min(max(per_page, 1), 100)
    page = max(page, 1)
    total_pages = math.ceil(total / per_page) if total > 0 else 1

    query = query.order_by(Student.last_name, Student.first_name)
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    students = result.scalars().all()

    return {
        "students": students,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


async def get_student(db: AsyncSession, student_id: int, school_id: int) -> Student:
    """Get a single student by ID, with tenant isolation."""
    result = await db.execute(
        select(Student).where(
            Student.id == student_id,
            Student.school_id == school_id,
        )
    )
    student = result.scalar_one_or_none()
    if student is None:
        raise HTTPException(status_code=404, detail="Eleve introuvable")
    return student


async def get_student_with_parents(db: AsyncSession, student_id: int, school_id: int) -> dict:
    """Get a student with their parent links and current class."""
    student = await get_student(db, student_id, school_id)

    # Get current class from active enrollment
    enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()

    current_class = None
    if enrollment:
        from app.models.class_ import Class
        cls = (await db.execute(
            select(Class).where(Class.id == enrollment.class_id)
        )).scalar_one_or_none()
        if cls:
            current_class = cls.name

    # Get parent links
    parent_links = (await db.execute(
        select(ParentStudent).where(ParentStudent.student_id == student_id)
    )).scalars().all()

    parents = []
    for pl in parent_links:
        parent_user = (await db.execute(
            select(User).where(User.id == pl.parent_id)
        )).scalar_one_or_none()
        parents.append({
            "id": pl.id,
            "parent_id": pl.parent_id,
            "parent_name": f"{parent_user.first_name} {parent_user.last_name}" if parent_user else "?",
            "role": pl.role.value,
            "is_primary": pl.is_primary,
        })

    return {
        "student": student,
        "current_class": current_class,
        "parents": parents,
    }


async def enrich_students_list(
    db: AsyncSession,
    students: list[Student],
    school_id: int,
) -> list[dict]:
    """Enrich a page of students with class, year, parents and account, batch-style."""
    if not students:
        return []
    ids = [s.id for s in students]

    # ── Classes / année (via enrollment actif + classe) ────────────
    from app.models.class_ import Class as ClassModel
    enroll_rows = (await db.execute(
        select(Enrollment.student_id, Enrollment.academic_year, ClassModel.name, ClassModel.academic_year)
        .join(ClassModel, ClassModel.id == Enrollment.class_id)
        .where(Enrollment.student_id.in_(ids), Enrollment.status == "active")
    )).all()
    cls_map: dict[int, dict] = {}
    for student_id, enroll_year, cls_name, cls_year in enroll_rows:
        if student_id not in cls_map:  # première inscription active trouvée
            cls_map[student_id] = {
                "current_class": cls_name,
                "current_year": cls_year or enroll_year or None,
            }

    # ── Parents ─────────────────────────────────────────────────────
    links = (await db.execute(
        select(ParentStudent).where(ParentStudent.student_id.in_(ids))
    )).scalars().all()
    parent_user_ids = list({l.parent_id for l in links})
    user_rows = {}
    if parent_user_ids:
        users = (await db.execute(
            select(User).where(User.id.in_(parent_user_ids), User.school_id == school_id)
        )).scalars().all()
        user_rows = {u.id: u for u in users}
    parents_map: dict[int, list] = {}
    for l in links:
        u = user_rows.get(l.parent_id)
        parents_map.setdefault(l.student_id, []).append({
            "id": l.id,
            "parent_id": l.parent_id,
            "parent_name": f"{u.first_name} {u.last_name}" if u else "?",
            "role": l.role.value if hasattr(l.role, "value") else str(l.role),
            "is_primary": l.is_primary,
        })

    # ── Compte de connexion élève ───────────────────────────────────
    account_ids = [s.user_id for s in students if s.user_id]
    account_rows = {}
    if account_ids:
        accounts = (await db.execute(
            select(User.id, User.username).where(User.id.in_(account_ids), User.school_id == school_id)
        )).all()
        account_rows = {uid: uname for uid, uname in accounts}

    from datetime import datetime
    out = []
    for s in students:
        info = cls_map.get(s.id, {})
        out.append({
            "id": s.id,
            "school_id": s.school_id,
            "matricule": s.matricule,
            "first_name": s.first_name,
            "last_name": s.last_name,
            "birth_date": s.birth_date,
            "birth_place": s.birth_place,
            "nationality": s.nationality,
            "gender": s.gender,
            "address": s.address,
            "phone": s.phone,
            "photo_url": s.photo_url,
            "previous_school": s.previous_school,
            "is_repeater": s.is_repeater,
            "status": s.status.value if hasattr(s.status, "value") else s.status,
            "status_reason": s.status_reason,
            "created_at": str(s.created_at) if s.created_at else None,
            "current_class": info.get("current_class"),
            "current_year": info.get("current_year"),
            "parents": parents_map.get(s.id, []),
            "user_id": s.user_id,
            "account_username": account_rows.get(s.user_id) if s.user_id else None,
            "account_exists": s.user_id is not None and s.user_id in account_rows,
        })
    return out


async def _generate_matricule(db: AsyncSession, school_id: int) -> str:
    """Generate a unique matricule for a student in a school.

    Format: ELV-YYYY-NNNN (e.g. ELV-2026-0001)
    """
    from datetime import datetime
    year = datetime.now().year
    prefix = f"ELV-{year}-"

    # Compter les eleves existants avec ce prefix
    result = await db.execute(
        select(func.count()).select_from(Student).where(
            Student.school_id == school_id,
            Student.matricule.like(f"{prefix}%"),
        )
    )
    count = (result.scalar() or 0) + 1
    return f"{prefix}{count:04d}"


async def generate_yiriba_id(db: AsyncSession, school_id: int) -> str:
    """Generate a unique YIRIBA login ID for a student.

    Format: YRB-XXXXXX (e.g. YRB-000001)
    Unique within the school.
    """
    # Count existing YRB- IDs for this school to find the next number
    result = await db.execute(
        select(func.count()).select_from(User).where(
            User.school_id == school_id,
            User.username.like("YRB-%"),
        )
    )
    count = (result.scalar() or 0) + 1
    yiriba_id = f"YRB-{count:06d}"

    # Safety: ensure uniqueness
    while (await db.execute(
        select(User.id).where(User.school_id == school_id, User.username == yiriba_id)
    )).scalar_one_or_none() is not None:
        count += 1
        yiriba_id = f"YRB-{count:06d}"

    return yiriba_id


def generate_temp_password() -> str:
    """Generate a secure temporary password (12 chars, mixed case + digits)."""
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(12))
        # Ensure it has at least one of each type
        if (any(c.islower() for c in pwd) and
            any(c.isupper() for c in pwd) and
            any(c.isdigit() for c in pwd)):
            return pwd


async def create_student(
    db: AsyncSession,
    data: StudentCreate,
    school_id: int,
) -> Student:
    """Create a new student. school_id comes from JWT, never from client."""
    # Auto-generate matricule if not provided
    matricule = data.matricule.strip() if data.matricule else None
    if not matricule:
        matricule = await _generate_matricule(db, school_id)

    student = Student(
        school_id=school_id,  # ← Forced from JWT
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        matricule=matricule,
        birth_date=data.birth_date,
        birth_place=data.birth_place,
        nationality=data.nationality,
        gender=data.gender,
        address=data.address,
        phone=data.phone,
        previous_school=data.previous_school,
        is_repeater=data.is_repeater,
        medical_info=data.medical_info,
    )
    db.add(student)
    await db.flush()
    await db.refresh(student)
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, action="student.create", resource="student", resource_id=student.id, details={"name": f"{student.first_name} {student.last_name}"})
    return student


async def update_student(
    db: AsyncSession,
    student_id: int,
    data: StudentUpdate,
    school_id: int,
) -> Student:
    """Update a student — only provided fields are changed."""
    student = await get_student(db, student_id, school_id)

    update_data = data.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(student, field_name, value)

    await db.flush()
    await db.refresh(student)
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, action="student.update", resource="student", resource_id=student.id, details={"fields": list(data.model_dump(exclude_unset=True).keys())})
    return student


async def change_student_status(
    db: AsyncSession,
    student_id: int,
    status: StudentStatus,
    school_id: int,
    reason: str = "",
) -> Student:
    """Change student status (soft delete / transfer / graduate).

    This is the ONLY way to "remove" a student — never a hard DELETE.
    """
    student = await get_student(db, student_id, school_id)
    old_status = student.status
    student.status = status
    student.status_reason = reason

    # Synchroniser le compte de connexion lié (s'il existe) : un élève
    # retiré/transféré/diplômé ne doit plus pouvoir se connecter.
    user_status_synced = None
    if student.user_id:
        from app.models.user import User, UserStatus
        linked_user = (await db.execute(
            select(User).where(User.id == student.user_id, User.school_id == school_id)
        )).scalar_one_or_none()
        if linked_user:
            if status == StudentStatus.ACTIVE:
                linked_user.status = UserStatus.ACTIVE
                user_status_synced = "active"
            else:
                # withdrawn / transferred / graduated / inactive -> compte suspendu
                linked_user.status = UserStatus.SUSPENDED
                user_status_synced = "suspended"

    await db.flush()
    await db.refresh(student)
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, action="student.status_change", resource="student", resource_id=student.id, details={"old_status": old_status.value if hasattr(old_status, 'value') else str(old_status), "new_status": status.value if hasattr(status, 'value') else str(status), "reason": reason, "linked_user_status": user_status_synced})
    return student


async def transfer_student(
    db: AsyncSession,
    student_id: int,
    new_class_id: int,
    school_id: int,
    reason: str = "",
) -> dict:
    """Transfer a student to a new class mid-year.

    Preserves enrollment history:
    - Old enrollment → status="transferred"
    - New enrollment → status="active"
    """
    student = await get_student(db, student_id, school_id)

    # Check new class exists and has capacity
    from app.models.class_ import Class
    new_class = (await db.execute(
        select(Class).where(Class.id == new_class_id, Class.school_id == school_id)
    )).scalar_one_or_none()
    if not new_class:
        raise HTTPException(status_code=404, detail="Classe de destination introuvable")

    # Count current enrollments in new class
    count_result = await db.execute(
        select(func.count()).select_from(Enrollment).where(
            Enrollment.class_id == new_class_id,
            Enrollment.status == "active",
        )
    )
    current_count = count_result.scalar()
    if current_count >= new_class.capacity:
        raise HTTPException(
            status_code=409,
            detail=f"Classe de destination complete ({current_count}/{new_class.capacity})",
        )

    # Mark old enrollment as transferred
    old_enrollment = (await db.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.status == "active",
        )
    )).scalar_one_or_none()

    old_class_name = None
    if old_enrollment:
        old_class = (await db.execute(
            select(Class).where(Class.id == old_enrollment.class_id)
        )).scalar_one_or_none()
        old_class_name = old_class.name if old_class else None
        old_enrollment.status = "transferred"

    # Create new enrollment
    new_enrollment = Enrollment(
        school_id=school_id,
        student_id=student_id,
        class_id=new_class_id,
        is_repeater=student.is_repeater,
        status="active",
    )
    db.add(new_enrollment)
    await db.flush()

    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, action="student.transfer", resource="student", resource_id=student_id, details={"from_class": old_class_name, "to_class": new_class.name, "reason": reason})

    return {
        "student_id": student_id,
        "old_class": old_class_name,
        "new_class": new_class.name,
        "reason": reason,
    }


# ── Parent Links ──────────────────────────────────────────────────


async def link_parent(
    db: AsyncSession,
    student_id: int,
    parent_id: int,
    school_id: int,
    role: ParentRole = ParentRole.OTHER,
    is_primary: bool = False,
) -> ParentStudent:
    """Link a parent to a student."""
    # Verify student
    await get_student(db, student_id, school_id)

    # Verify parent is a user with role_type=PARENT in the same school
    from app.models.permission import RolePermission, Permission
    parent_user = (await db.execute(
        select(User).where(
            User.id == parent_id,
            User.school_id == school_id,
            User.role_type == UserRole.PARENT,
        )
    )).scalar_one_or_none()
    if not parent_user:
        raise HTTPException(status_code=404, detail="Parent introuvable dans cette ecole")

    # Check if link already exists
    existing = (await db.execute(
        select(ParentStudent).where(
            ParentStudent.parent_id == parent_id,
            ParentStudent.student_id == student_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Ce parent est deja lie a cet eleve")

    # If is_primary, unset other primary links for this student
    if is_primary:
        other_primary = (await db.execute(
            select(ParentStudent).where(
                ParentStudent.student_id == student_id,
                ParentStudent.is_primary == True,  # noqa: E712
            )
        )).scalars().all()
        for op in other_primary:
            op.is_primary = False

    link = ParentStudent(
        school_id=school_id,
        parent_id=parent_id,
        student_id=student_id,
        role=role,
        is_primary=is_primary,
    )
    db.add(link)
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, action="student.parent_link", resource="student", resource_id=student_id, details={"parent_id": parent_id, "role": role.value if hasattr(role, 'value') else str(role)})
    return link


async def unlink_parent(
    db: AsyncSession,
    student_id: int,
    parent_id: int,
    school_id: int,
) -> None:
    """Remove a parent link from a student."""
    link = (await db.execute(
        select(ParentStudent).where(
            ParentStudent.student_id == student_id,
            ParentStudent.parent_id == parent_id,
            ParentStudent.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Lien parent-eleve introuvable")
    await db.delete(link)
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, action="student.parent_unlink", resource="student", resource_id=student_id, details={"parent_id": parent_id})


# ── CSV Import ────────────────────────────────────────────────────


async def import_students_csv(
    db: AsyncSession,
    file_content: bytes,
    school_id: int,
) -> dict[str, Any]:
    """Import students from a CSV file."""
    text = file_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    imported = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):
        try:
            first_name = row.get("first_name", "").strip()
            last_name = row.get("last_name", "").strip()

            if not first_name or not last_name:
                errors.append(f"Ligne {i}: prenom et nom requis")
                continue

            student = Student(
                school_id=school_id,
                first_name=first_name,
                last_name=last_name,
                matricule=row.get("matricule", "").strip(),
                gender=row.get("gender", "M").strip().upper()[:1],
                phone=row.get("phone", "").strip() or None,
            )

            bd = row.get("birth_date", "").strip()
            if bd:
                from datetime import date
                try:
                    student.birth_date = date.fromisoformat(bd)
                except ValueError:
                    pass

            db.add(student)
            imported += 1

        except Exception as e:
            errors.append(f"Ligne {i}: {str(e)}")

    await db.flush()
    return {"imported": imported, "errors": errors}
