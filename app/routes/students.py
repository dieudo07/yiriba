"""Yiriba SaaS — Student routes: CRUD, transfer, status, parent links, CSV import.

All routes protected by RBAC. All queries filter by school_id from JWT.
"""

import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.rbac import get_school_id, require_permission
from app.services.subscription_service import require_write_access
from app.models.enums import ParentRole, StudentStatus
from app.models.user import User
from app.schemas.student import (
    ParentLinkCreate,
    StudentCreate,
    StudentListResponse,
    StudentResponse,
    StudentStatusUpdate,
    StudentTransfer,
    StudentUpdate,
)
from app.services import student_service

router = APIRouter(prefix="/api/students", tags=["students"])


def _student_response(student, current_class=None, parents=None, account_username=None) -> dict:
    """Build student response dict."""
    return {
        "id": student.id,
        "school_id": student.school_id,
        "matricule": student.matricule,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "birth_date": student.birth_date,
        "birth_place": student.birth_place,
        "nationality": student.nationality,
        "gender": student.gender,
        "address": student.address,
        "phone": student.phone,
        "photo_url": student.photo_url,
        "previous_school": student.previous_school,
        "is_repeater": student.is_repeater,
        "status": student.status.value,
        "status_reason": student.status_reason,
        "created_at": str(student.created_at) if student.created_at else None,
        "current_class": current_class,
        "parents": parents or [],
        "user_id": getattr(student, "user_id", None),
        "account_username": account_username,
        "account_exists": account_username is not None,
    }


@router.get("", response_model=StudentListResponse)
async def list_students(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=100),
    class_id: int | None = Query(None),
    gender: str | None = Query(None, pattern="^[MF]$"),
    status: str | None = Query(None),
    level: str | None = Query(None, max_length=50),
    academic_year: str | None = Query(None, max_length=10),
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List students with pagination, search, filters, and ownership."""
    school_id = get_school_id(user)
    result = await student_service.list_students(
        db, user, school_id,
        page=page, per_page=per_page,
        search=search, class_id=class_id, gender=gender, status=status,
        level=level, academic_year=academic_year,
    )
    # Enrichir chaque élève (classe, année, parents, compte) en batch pour la liste
    students = result["students"]
    enriched = await student_service.enrich_students_list(db, students, school_id)
    result["students"] = enriched
    return result


@router.get("/export")
async def export_students(
    search: str = Query("", max_length=100),
    class_id: int | None = Query(None),
    gender: str | None = Query(None, pattern="^[MF]$"),
    status: str | None = Query(None),
    level: str | None = Query(None, max_length=50),
    academic_year: str | None = Query(None, max_length=10),
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export all students (respecting filters) as CSV. Tenant-isolated."""
    import csv
    import io
    from fastapi.responses import Response as FastAPIResponse

    school_id = get_school_id(user)
    result = await student_service.list_students(
        db, user, school_id,
        page=1, per_page=10000,
        search=search, class_id=class_id, gender=gender, status=status,
        level=level, academic_year=academic_year,
    )
    students = result["students"]

    # Fetch parents + current class for each student
    rows = []
    for s in students:
        detail = await student_service.get_student_with_parents(db, s.id, school_id)
        parents = detail.get("parents") or []
        parent_names = "; ".join(p.get("parent_name", "") for p in parents)
        rows.append({
            "Matricule": s.matricule or "",
            "Nom": s.last_name or "",
            "Prénom": s.first_name or "",
            "Genre": s.gender or "",
            "Date de naissance": str(s.birth_date) if s.birth_date else "",
            "Lieu de naissance": s.birth_place or "",
            "Classe": detail.get("current_class") or "",
            "Téléphone": s.phone or "",
            "Adresse": s.address or "",
            "Statut": (s.status.value if hasattr(s.status, "value") else s.status) if s.status else "",
            "Parent(s)": parent_names,
        })

    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("Matricule;Nom;Prénom;Genre;Date de naissance;Lieu de naissance;Classe;Téléphone;Adresse;Statut;Parent(s)\n")

    filename = f"eleves_{school_id}.csv"
    return FastAPIResponse(
        content="\ufeff" + output.getvalue(),  # BOM pour Excel
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{student_id}")
async def get_student(
    student_id: int,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single student with parents and current class."""
    school_id = get_school_id(user)
    result = await student_service.get_student_with_parents(db, student_id, school_id)
    student = result["student"]

    # Enrichir avec l'info du compte de connexion élève
    account_username = None
    if student.user_id:
        account = (await db.execute(
            select(User).where(User.id == student.user_id, User.school_id == school_id)
        )).scalar_one_or_none()
        if account:
            account_username = account.username

    return _student_response(
        student,
        current_class=result["current_class"],
        parents=result["parents"],
        account_username=account_username,
    )


@router.post("", response_model=StudentResponse, status_code=201)
async def create_student(
    data: StudentCreate,
    user: User = Depends(require_permission("student.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new student. school_id forced from JWT."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Verifier la limite du forfait avant de creer
    from app.services.subscription_service import PlanLimitService
    await PlanLimitService.check_can_add_student(db, school_id)

    student = await student_service.create_student(db, data, school_id)

    # Creer le parent si les infos sont fournies
    parent_info = None
    if data.parent_first_name and data.parent_last_name:
        from app.models.parent_student import ParentStudent
        from app.models.permission import Role, RolePermission, Permission
        from app.core.security import hash_password
        import secrets

        # Creer un compte parent (user avec role PARENT)
        parent_email = data.parent_email or f"parent-{student.matricule or student.id}@yiriba.local"
        parent_pw = secrets.token_urlsafe(12)

        parent_user = User(
            school_id=school_id,
            email=parent_email,
            first_name=data.parent_first_name.strip(),
            last_name=data.parent_last_name.strip(),
            phone=data.parent_phone,
            password_hash=hash_password(parent_pw),
            role_type="parent",
        )
        db.add(parent_user)
        await db.flush()

        # Creer le lien parent-eleve
        role_val = data.parent_role or "other"
        parent_link = ParentStudent(
            school_id=school_id,
            parent_id=parent_user.id,
            student_id=student.id,
            role=ParentRole(role_val),
            is_primary=data.parent_is_primary,
        )
        db.add(parent_link)
        await db.flush()

        parent_info = {
            "id": parent_user.id,
            "parent_id": parent_user.id,
            "parent_name": f"{parent_user.first_name} {parent_user.last_name}",
            "name": f"{parent_user.first_name} {parent_user.last_name}",
            "email": parent_email,
            "role": role_val,
            "is_primary": data.parent_is_primary,
        }

    result = _student_response(student)
    if parent_info:
        result["parents"] = [parent_info]
    return result


@router.put("/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: int,
    data: StudentUpdate,
    user: User = Depends(require_permission("student.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a student — only provided fields are changed."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    student = await student_service.update_student(db, student_id, data, school_id)
    return _student_response(student)


@router.put("/{student_id}/status")
async def change_status(
    student_id: int,
    data: StudentStatusUpdate,
    user: User = Depends(require_permission("student.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change student status (soft delete / transfer / graduate / deactivate)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    student = await student_service.change_student_status(
        db, student_id, data.status, school_id, data.reason
    )
    return _student_response(student)


@router.post("/{student_id}/transfer")
async def transfer_student(
    student_id: int,
    data: StudentTransfer,
    user: User = Depends(require_permission("student.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Transfer a student to a new class mid-year.

    Preserves enrollment history:
    - Old enrollment → status="transferred"
    - New enrollment → status="active"
    """
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    return await student_service.transfer_student(
        db, student_id, data.new_class_id, school_id, data.reason
    )


@router.delete("/{student_id}", status_code=204)
async def deactivate_student(
    student_id: int,
    user: User = Depends(require_permission("student.delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a student (set status=WITHDRAWN). NEVER a hard delete."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    await student_service.change_student_status(
        db, student_id, StudentStatus.WITHDRAWN, school_id, "Supprime par l'administration"
    )


# ── Parent Links ──────────────────────────────────────────────────


@router.get("/{student_id}/parents")
async def list_student_parents(
    student_id: int,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all parents linked to a student."""
    school_id = get_school_id(user)
    result = await student_service.get_student_with_parents(db, student_id, school_id)
    return {"parents": result["parents"]}


@router.post("/{student_id}/parents", status_code=201)
async def link_parent(
    student_id: int,
    data: ParentLinkCreate,
    user: User = Depends(require_permission("student.update")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Link a parent to a student with a role (father/mother/guardian/other)."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    link = await student_service.link_parent(
        db, student_id, data.parent_id, school_id,
        role=data.role, is_primary=data.is_primary,
    )
    return {"id": link.id, "parent_id": link.parent_id, "role": link.role.value, "is_primary": link.is_primary}


@router.delete("/{student_id}/parents/{parent_id}", status_code=204)
async def unlink_parent(
    student_id: int,
    parent_id: int,
    user: User = Depends(require_permission("student.update")),

    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a parent link from a student."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    await student_service.unlink_parent(db, student_id, parent_id, school_id)


# ── History ───────────────────────────────────────────────────────


@router.get("/{student_id}/history")
async def student_history(
    student_id: int,
    user: User = Depends(require_permission("student.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get complete student history: enrollments, classes, status changes."""
    school_id = get_school_id(user)
    student = await student_service.get_student(db, student_id, school_id)

    from sqlalchemy import select
    from app.models.class_ import Enrollment, Class

    enrollments = (await db.execute(
        select(Enrollment).where(Enrollment.student_id == student_id)
        .order_by(Enrollment.enrolled_at.desc())
    )).scalars().all()

    history = []
    for e in enrollments:
        cls = (await db.execute(
            select(Class).where(Class.id == e.class_id)
        )).scalar_one_or_none()
        history.append({
            "enrollment_id": e.id,
            "class_name": cls.name if cls else "?",
            "class_id": e.class_id,
            "academic_year": e.academic_year,
            "status": e.status,
            "is_repeater": e.is_repeater,
            "enrolled_at": str(e.enrolled_at),
        })

    return {
        "student": _student_response(student),
        "enrollments": history,
    }


# ── Mass Import ────────────────────────────────────────────────────


@router.post("/import/detect")
async def detect_import_columns(
    file: UploadFile = File(...),
    user: User = Depends(require_permission("student.import")),
) -> dict:
    """Step 1: Upload file and auto-detect column mapping."""
    from app.services import import_service

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Fichier trop volumineux (max 10 Mo)")

    filename = file.filename or "upload.csv"
    if not filename.endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(400, "Formats acceptés: CSV, XLSX, XLS")

    result = await import_service.detect_columns(content, filename)
    return result


@router.post("/import/validate")
async def validate_import(
    file: UploadFile = File(...),
    mapping: str = File(...),
    user: User = Depends(require_permission("student.import")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Step 3: Validate all rows with confirmed mapping (no DB write)."""
    from app.services import import_service

    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Fichier trop volumineux (max 10 Mo)")

    filename = file.filename or "upload.csv"

    # Parse mapping from JSON string
    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(400, "Mapping invalide")

    result = await import_service.validate_import(
        content, filename, mapping_dict, school_id, db
    )
    return result


@router.post("/import/confirm")
async def confirm_import(
    session_id: str,
    create_accounts: bool = Query(False),
    user: User = Depends(require_permission("student.import")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Step 4: Atomically import all valid rows."""
    from app.services import import_service

    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    from app.services.subscription_service import PlanLimitService
    await PlanLimitService.check_can_add_student(db, school_id)

    try:
        result = await import_service.confirm_import(
            session_id, school_id, db, create_accounts=create_accounts
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Photo Upload ──────────────────────────────────────────────────


@router.post("/{student_id}/photo")
async def upload_student_photo(
    student_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("student.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a photo for a student. Max 5 Mo. Formats: jpg, png, webp."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Verifier que l'eleve appartient a l'ecole
    student = await student_service.get_student(db, student_id, school_id)

    # Verifier la taille (5 Mo max)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="La photo depasse 5 Mo. Choisissez une image plus legere.",
        )

    # Verifier le format par signature réelle des octets (pas le Content-Type)
    try:
        from app.core.security import validate_image_upload
        ext = validate_image_upload(
            content,
            file.filename,
            file.content_type,
            allowed_ext={"jpg", "png", "webp"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Formats acceptes : JPG, PNG, WebP. ({e})") from e

    # Sauvegarder le fichier
    import os
    import uuid
    from pathlib import Path

    upload_dir = Path("static/uploads/photos")
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"student_{school_id}_{student_id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = upload_dir / filename

    with open(filepath, "wb") as f:
        f.write(content)

    # Mettre a jour l'eleve
    photo_url = f"/static/uploads/photos/{filename}"
    student.photo_url = photo_url
    await db.flush()

    return {"student_id": student_id, "photo_url": photo_url, "message": "Photo mise a jour"}


# ── Student Access (YRB-ID + temporary password) ─────────────────


@router.post("/{student_id}/access")
async def create_or_reset_student_access(
    student_id: int,
    user: User = Depends(require_permission("user.create")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create the student login account (or reset its password).

    Auto-generates a YRB-XXXXXX identifier and a temporary password.
    The temp password is returned ONLY here, never stored in plain text.
    """
    from app.core.security import hash_password
    from app.models.student import Student
    from app.models.user import UserStatus
    from app.services.student_service import generate_temp_password, generate_yiriba_id

    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    student = await student_service.get_student(db, student_id, school_id)

    account = None
    if student.user_id:
        account = (await db.execute(
            select(User).where(User.id == student.user_id, User.school_id == school_id)
        )).scalar_one_or_none()

    temp_password = generate_temp_password()

    if account:
        # Réinitialisation : nouveau mot de passe temporaire
        account.password_hash = hash_password(temp_password)
        account.must_change_password = True
        account.status = UserStatus.ACTIVE
        await db.flush()
        created = False
    else:
        # Création : nouvel identifiant YRB + mot de passe temporaire
        yiriba_id = await generate_yiriba_id(db, school_id)
        account = User(
            school_id=school_id,
            username=yiriba_id,
            first_name=student.first_name,
            last_name=student.last_name,
            password_hash=hash_password(temp_password),
            role_type="student",
            role_id=None,
            status=UserStatus.ACTIVE,
            must_change_password=True,
            invited_by=user.id,
        )
        db.add(account)
        await db.flush()
        student.user_id = account.id
        created = True

    from app.services.audit_service import safe_audit
    await safe_audit(
        db, school_id=school_id, user_id=user.id,
        action="user.access_generated" if created else "user.access_reset",
        resource="student", resource_id=student.id,
        details={"username": account.username},
    )
    await db.commit()

    return {
        "student_id": student.id,
        "username": account.username,
        "temp_password": temp_password,
        "must_change_password": True,
        "created": created,
        "message": "Accès créé" if created else "Accès réinitialisé",
    }
