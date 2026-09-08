"""Yiriba SaaS — Admin Portal routes.

Dashboard KPI, user management (create/validate/suspend), roles, audit log, settings.
All endpoints require admin role_type + specific RBAC permission.
"""

import math
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password, validate_password
from app.middleware.rbac import get_school_id, require_permission
from app.models.audit import AuditLog
from app.models.class_ import Class, Enrollment
from app.models.payment import FeeObligation, Payment, PaymentStatus
from app.models.permission import Permission, Role, RolePermission
from app.models.school import School
from app.models.school_setting import SchoolSetting
from app.models.student import Student, StudentStatus
from app.models.user import User, UserRole, UserStatus
from app.services.subscription_service import require_write_access

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Schemas ---


class UserCreate(BaseModel):
    email: str | None = Field(default=None, max_length=200)  # Nullable pour élèves (login par YRB-ID)
    phone: str | None = Field(default=None, max_length=30)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=8)  # Auto-généré si None
    role_type: UserRole = Field(default=UserRole.ADMIN)
    role_id: int | None = None  # Sous-rôle RBAC
    generate_password: bool = Field(default=False)  # Générer un mot de passe temporaire
    student_id: int | None = None  # Lien explicite avec un élève de l'école (compte élève)


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    permission_ids: list[int] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    permission_ids: list[int] | None = None


class SettingsUpdate(BaseModel):
    settings: dict[str, str]  # {"key": "value", ...}


# --- Global Search ---


@router.get("/search")
async def global_search(
    q: str = Query(..., min_length=1),
    user: User = Depends(require_permission("class.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Search across students, teachers, classes, and payments."""
    school_id = get_school_id(user)
    term = f"%{q.lower()}%"
    results = []

    # Students
    res = await db.execute(
        select(Student).where(
            Student.school_id == school_id,
            Student.is_active == True,  # noqa: E712
            or_(Student.first_name.ilike(term), Student.last_name.ilike(term), Student.matricule.ilike(term))
        ).limit(5)
    )
    for s in res.scalars().all():
        results.append({"type": "student", "id": s.id, "label": f"{s.first_name} {s.last_name}", "subtitle": s.matricule or "", "page": "students"})

    # Teachers (users with role teacher)
    res = await db.execute(
        select(User).where(
            User.school_id == school_id,
            User.role_type == "teacher",
            or_(User.first_name.ilike(term), User.last_name.ilike(term), User.email.ilike(term))
        ).limit(5)
    )
    for u in res.scalars().all():
        results.append({"type": "teacher", "id": u.id, "label": f"{u.first_name} {u.last_name}", "subtitle": u.email or "", "page": "teachers"})

    # Classes
    res = await db.execute(
        select(Class).where(
            Class.school_id == school_id,
            Class.is_active == True,  # noqa: E712
            Class.name.ilike(term)
        ).limit(5)
    )
    for c in res.scalars().all():
        results.append({"type": "class", "id": c.id, "label": c.name, "subtitle": c.level or "", "page": "classes"})

    return {"results": results}


# --- Dashboard KPIs ---


@router.get("/dashboard")
async def admin_dashboard(
    user: User = Depends(require_permission("report.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dashboard with aggregated KPIs — 4 SQL queries max (no N+1)."""
    school_id = get_school_id(user)

    # 1. Effectifs par statut (1 query)
    effectifs = (await db.execute(
        select(Student.status, func.count(Student.id))
        .where(Student.school_id == school_id)
        .group_by(Student.status)
    )).all()
    effectifs_dict = {row[0].value if hasattr(row[0], 'value') else row[0]: row[1] for row in effectifs}

    # 2. Total enrolled active students
    active_students = (await db.execute(
        select(func.count(Student.id)).where(
            Student.school_id == school_id,
            Student.status == StudentStatus.ACTIVE,
        )
    )).scalar() or 0

    # 3. Classes actives
    active_classes = (await db.execute(
        select(func.count(Class.id)).where(
            Class.school_id == school_id,
            Class.is_active == True,  # noqa: E712
        )
    )).scalar() or 0

    # 4. Impayés du mois (1 query with subquery)
    from datetime import date
    today = date.today()
    month_start = today.replace(day=1)

    unpaid_result = (await db.execute(
        select(
            FeeObligation.class_id,
            func.sum(FeeObligation.amount).label("total_owed"),
        )
        .join(Payment, Payment.obligation_id == FeeObligation.id, isouter=True)
        .where(
            FeeObligation.school_id == school_id,
            FeeObligation.is_active == True,  # noqa: E712
        )
        .group_by(FeeObligation.class_id)
    )).all()

    # 5. Total encaissé ce mois (1 query)
    total_collected = (await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.school_id == school_id,
            Payment.status == PaymentStatus.CONFIRMED,
            Payment.paid_at >= datetime.combine(month_start, datetime.min.time()),
        )
    )).scalar() or 0

    # 6. Dernières actions audit (1 query LIMIT 10)
    recent_audit = (await db.execute(
        select(AuditLog)
        .where(AuditLog.school_id == school_id)
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    )).scalars().all()

    # 7. Comptes en attente de validation
    pending_count = (await db.execute(
        select(func.count(User.id)).where(
            User.school_id == school_id,
            User.status == UserStatus.PENDING,
        )
    )).scalar() or 0

    # 8. Présences du jour
    from app.models.attendance import Attendance
    today_stats = (await db.execute(
        select(Attendance.status, func.count(Attendance.id))
        .where(
            Attendance.school_id == school_id,
            Attendance.date == today,
        )
        .group_by(Attendance.status)
    )).all()
    today_dict = {row[0].value if hasattr(row[0], 'value') else row[0]: row[1] for row in today_stats}

    # 9. Répartition des élèves par classe (1 query)
    class_dist = (await db.execute(
        select(Class.name, func.count(Enrollment.student_id))
        .join(Enrollment, Enrollment.class_id == Class.id)
        .where(
            Class.school_id == school_id,
            Enrollment.status == 'active',
        )
        .group_by(Class.name)
        .order_by(func.count(Enrollment.student_id).desc())
    )).all()
    class_distribution = {row[0]: row[1] for row in class_dist}

    # 10. Paiements par statut (1 query)
    pay_status = (await db.execute(
        select(Payment.status, func.count(Payment.id))
        .where(Payment.school_id == school_id)
        .group_by(Payment.status)
    )).all()
    payment_status = {}
    for row in pay_status:
        val = row[0].value if hasattr(row[0], 'value') else row[0]
        label = {'confirmed': 'Payés', 'pending': 'En attente', 'overdue': 'En retard', 'refunded': 'Remboursés'}.get(val, val)
        payment_status[label] = row[1]

    return {
        "effectifs": effectifs_dict,
        "active_students": active_students,
        "active_classes": active_classes,
        "total_collected_this_month": total_collected,
        "pending_accounts": pending_count,
        "today_attendance": today_dict,
        "class_distribution": class_distribution,
        "payment_status": payment_status,
        "recent_audit": [
            {
                "id": a.id,
                "user_id": a.user_id,
                "action": a.action,
                "resource": a.resource,
                "resource_id": a.resource_id,
                "created_at": str(a.created_at),
            }
            for a in recent_audit
        ],
    }


# --- User Management ---


@router.get("/users")
async def list_users(
    role_type: UserRole | None = None,
    status: UserStatus | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(require_permission("user.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(User).where(User.school_id == school_id)

    if role_type:
        query = query.where(User.role_type == role_type)
    if status:
        query = query.where(User.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    users = (await db.execute(
        query.order_by(User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    return {
        "users": [
            {
                "id": u.id, "email": u.email, "username": u.username,
                "phone": u.phone,
                "first_name": u.first_name, "last_name": u.last_name,
                "role_type": u.role_type.value,
                "status": u.status.value,
                "created_at": str(u.created_at),
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


@router.post("/users", status_code=201)
async def create_user(
    data: UserCreate,
    user: User = Depends(require_permission("user.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new user account. Supports all roles (admin, teacher, educator,
    secretary, comptable, parent, student). Auto-generates password and YIRIBA ID
    when requested."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Check duplicate email within school (if email provided)
    if data.email:
        existing = (await db.execute(
            select(User).where(User.email == data.email.strip().lower(), User.school_id == school_id)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Cet email est déjà utilisé dans cette école")

    # Check duplicate phone within school (if phone provided)
    if data.phone:
        existing_phone = (await db.execute(
            select(User).where(User.phone == data.phone.strip(), User.school_id == school_id)
        )).scalar_one_or_none()
        if existing_phone:
            raise HTTPException(status_code=409, detail="Ce numéro de téléphone est déjà utilisé dans cette école")

    # Handle password: auto-generate if requested or if None
    temp_password = None
    if data.generate_password or not data.password:
        from app.services.student_service import generate_temp_password
        temp_password = generate_temp_password()
        password_hash = hash_password(temp_password)
    else:
        valid, msg = validate_password(data.password)
        if not valid:
            raise HTTPException(status_code=400, detail=msg)
        password_hash = hash_password(data.password)

    # Generate YIRIBA ID for students
    yiriba_id = None
    must_change = False
    if data.role_type == UserRole.STUDENT:
        from app.services.student_service import generate_yiriba_id
        yiriba_id = await generate_yiriba_id(db, school_id)
        must_change = True  # Force password change on first login

    # ── Vérification FK croisée : le rôle appartient-il à cette école ?
    if data.role_id:
        role_ok = (await db.execute(
            select(Role.id).where(
                Role.id == data.role_id,
                Role.school_id == school_id,
            )
        )).scalar_one_or_none()
        if role_ok is None:
            raise HTTPException(status_code=404, detail="Rôle introuvable dans cette école")

    # ── Vérification FK croisée : l'élève lié appartient-il à cette école ?
    from app.models.student import Student
    linked_student = None
    if data.student_id is not None:
        linked_student = (await db.execute(
            select(Student).where(
                Student.id == data.student_id,
                Student.school_id == school_id,
            )
        )).scalar_one_or_none()
        if linked_student is None:
            raise HTTPException(status_code=404, detail="Élève introuvable dans cette école")
        if linked_student.user_id is not None:
            raise HTTPException(status_code=409, detail="Cet élève possède déjà un compte lié")

    # Determine initial status
    initial_status = UserStatus.ACTIVE
    if data.role_type == UserRole.ADMIN:
        creator_role = None
        if user.role_id:
            creator_role = (await db.execute(
                select(Role).where(Role.id == user.role_id)
            )).scalar_one_or_none()
        if creator_role and creator_role.name == "Directeur":
            initial_status = UserStatus.ACTIVE
        else:
            initial_status = UserStatus.PENDING

    new_user = User(
        school_id=school_id,
        email=data.email.strip().lower() if data.email else None,
        phone=data.phone.strip() if data.phone else None,
        username=yiriba_id,
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        password_hash=password_hash,
        role_type=data.role_type,
        role_id=data.role_id,
        status=initial_status,
        must_change_password=must_change,
        invited_by=user.id,
    )
    db.add(new_user)
    await db.flush()

    # Lien explicite élève ↔ compte (portail élève sécurisé)
    if linked_student is not None:
        linked_student.user_id = new_user.id
        await db.flush()

    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="user.create", resource="user", resource_id=new_user.id, details={"email": new_user.email, "username": new_user.username, "role_type": new_user.role_type.value if hasattr(new_user.role_type, 'value') else str(new_user.role_type)})

    result = {
        "id": new_user.id,
        "email": new_user.email,
        "username": new_user.username,
        "status": new_user.status.value,
        "message": f"Compte créé avec statut '{new_user.status.value}'",
    }
    if temp_password:
        result["temp_password"] = temp_password
    return result


@router.get("/pending-accounts")
async def list_pending_accounts(
    user: User = Depends(require_permission("user.validate")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all accounts pending validation."""
    school_id = get_school_id(user)
    pending = (await db.execute(
        select(User).where(
            User.school_id == school_id,
            User.status == UserStatus.PENDING,
        ).order_by(User.created_at.desc())
    )).scalars().all()

    return {
        "pending": [
            {
                "id": u.id, "email": u.email,
                "first_name": u.first_name, "last_name": u.last_name,
                "role_type": u.role_type.value,
                "invited_by": u.invited_by,
                "created_at": str(u.created_at),
            }
            for u in pending
        ],
        "count": len(pending),
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    data: dict,
    user: User = Depends(require_permission("user.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update user info (name, email, role_type)."""
    school_id = get_school_id(user)
    target = (await db.execute(
        select(User).where(User.id == user_id, User.school_id == school_id)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    for field in ['first_name', 'last_name', 'email']:
        if data.get(field):
            setattr(target, field, data[field])
    if data.get('role_type'):
        target.role_type = UserRole(data['role_type'])
    await db.commit()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="user.update", resource="user", resource_id=target.id, details={"fields": list(data.keys())})
    return {"id": target.id, "message": "Utilisateur mis à jour"}


@router.put("/users/{user_id}/validate")
async def validate_user(
    user_id: int,
    user: User = Depends(require_permission("user.validate")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Validate a pending account → status becomes ACTIVE."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    target = (await db.execute(
        select(User).where(User.id == user_id, User.school_id == school_id)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if target.status != UserStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Ce compte a déjà le statut '{target.status.value}'")

    target.status = UserStatus.ACTIVE
    target.confirmed_at = datetime.utcnow()
    target.confirmed_by = user.id
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="user.validate", resource="user", resource_id=target.id, details={"email": target.email})

    return {"id": target.id, "status": "active", "message": "Compte validé avec succès"}


@router.put("/users/{user_id}/suspend")
async def suspend_user(
    user_id: int,
    user: User = Depends(require_permission("user.delete")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Suspend a user account."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    # Prevent self-suspension
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas vous suspendre vous-même")

    target = (await db.execute(
        select(User).where(User.id == user_id, User.school_id == school_id)
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    # Prevent suspending the last admin
    from app.middleware.rbac import require_last_admin
    require_last_admin(db, school_id, user_id)

    target.status = UserStatus.SUSPENDED
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="user.suspend", resource="user", resource_id=target.id, details={"email": target.email})

    return {"id": target.id, "status": "suspended", "message": "Compte suspendu"}


# --- Roles Management ---


@router.get("/roles")
async def list_roles(
    user: User = Depends(require_permission("role.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    roles = (await db.execute(
        select(Role).where(Role.school_id == school_id).order_by(Role.name)
    )).scalars().all()

    # Permissions par rôle + catalogue complet pour l'éditeur
    role_ids = [r.id for r in roles]
    perms_by_role: dict[int, list[int]] = {}
    if role_ids:
        rows = (await db.execute(
            select(RolePermission.role_id, RolePermission.permission_id)
            .where(RolePermission.role_id.in_(role_ids))
        )).all()
        for rid, pid in rows:
            perms_by_role.setdefault(rid, []).append(pid)

    all_perms = (await db.execute(
        select(Permission).order_by(Permission.resource, Permission.action)
    )).scalars().all()

    return {
        "roles": [
            {
                "id": r.id, "name": r.name, "is_system": r.is_system,
                "permission_ids": sorted(perms_by_role.get(r.id, [])),
                "permission_count": len(perms_by_role.get(r.id, [])),
                "user_count": (await db.execute(
                    select(func.count()).select_from(User)
                    .where(User.role_id == r.id)
                )).scalar() or 0,
            }
            for r in roles
        ],
        "permissions": [
            {
                "id": p.id, "codename": p.codename,
                "resource": p.resource, "action": p.action,
                "description": p.description,
            }
            for p in all_perms
        ],
    }


@router.put("/roles/{role_id}")
async def update_role(
    role_id: int,
    data: RoleUpdate,
    user: User = Depends(require_permission("role.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rename a role and/or replace its permissions."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)
    role = (await db.execute(
        select(Role).where(Role.id == role_id, Role.school_id == school_id)
    )).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Rôle introuvable")

    if data.name is not None and data.name.strip():
        clash = (await db.execute(
            select(Role).where(Role.name == data.name.strip(), Role.school_id == school_id, Role.id != role_id)
        )).scalar_one_or_none()
        if clash:
            raise HTTPException(status_code=409, detail=f"Le rôle '{data.name.strip()}' existe déjà")
        role.name = data.name.strip()

    if data.permission_ids is not None:
        # Remplace l'ensemble des permissions
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        for perm_id in data.permission_ids:
            perm = (await db.execute(
                select(Permission).where(Permission.id == perm_id)
            )).scalar_one_or_none()
            if perm:
                db.add(RolePermission(role_id=role_id, permission_id=perm_id))

    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="role.update", resource="role", resource_id=role_id, details={"name": role.name, "permissions": len(data.permission_ids or [])})
    return {"id": role.id, "name": role.name}


@router.post("/roles", status_code=201)
async def create_role(
    data: RoleCreate,
    user: User = Depends(require_permission("role.create")),

    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a custom role with specific permissions."""
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    existing = (await db.execute(
        select(Role).where(Role.name == data.name, Role.school_id == school_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Le rôle '{data.name}' existe déjà")

    role = Role(school_id=school_id, name=data.name.strip(), is_system=False)
    db.add(role)
    await db.flush()

    # Add permissions
    for perm_id in data.permission_ids:
        perm = (await db.execute(
            select(Permission).where(Permission.id == perm_id)
        )).scalar_one_or_none()
        if perm:
            db.add(RolePermission(role_id=role.id, permission_id=perm_id))

    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="role.create", resource="role", resource_id=role.id, details={"name": role.name, "permissions": len(data.permission_ids)})
    return {"id": role.id, "name": role.name}


# --- Audit Log ---


@router.get("/audit-log")
async def list_audit_log(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    action: str | None = None,
    user: User = Depends(require_permission("audit.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    query = select(AuditLog).where(AuditLog.school_id == school_id)

    if action:
        query = query.where(AuditLog.action == action)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    logs = (await db.execute(
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    return {
        "logs": [
            {
                "id": l.id, "user_id": l.user_id,
                "action": l.action, "resource": l.resource,
                "resource_id": l.resource_id, "details": l.details,
                "ip_address": l.ip_address,
                "created_at": str(l.created_at),
            }
            for l in logs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total else 1,
    }


# --- School Profile ---


@router.get("/school-profile")
async def get_school_profile(
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the school profile (name, slug, logo, address, etc.)."""
    school_id = get_school_id(user)
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")
    return {
        "school": {
            "id": school.id,
            "name": school.name,
            "slug": school.slug,
            "short_name": school.short_name,
            "school_type": school.school_type,
            "email": school.email,
            "phone": school.phone,
            "address": school.address,
            "city": school.city,
            "district": school.district,
            "region": school.region,
            "country": school.country,
            "website": school.website,
            "logo_url": school.logo_url,
            "motto": school.motto,
            "subscription_status": school.subscription_status,
        }
    }


# --- Notification Settings ---


@router.get("/notification-settings")
async def get_notification_settings(
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all notification settings for the school."""
    from app.models.notification_setting import (
        DEFAULT_TEMPLATES,
        TEMPLATE_VARIABLES,
        NotificationSetting,
    )
    school_id = get_school_id(user)
    settings = (await db.execute(
        select(NotificationSetting).where(NotificationSetting.school_id == school_id)
    )).scalars().all()

    # If no settings exist, create defaults for all event types
    if not settings:
        default_events = [
            ("absence", False, True),
            ("new_grade", False, True),
            ("payment_due", True, True),
            ("payment_received", False, True),
            ("bulletin_ready", False, True),
            ("account_validation", False, True),
            ("announcement", True, True),
            ("low_attendance", True, True),
        ]
        for event_type, sms, email in default_events:
            ns = NotificationSetting(
                school_id=school_id,
                event_type=event_type,
                sms_enabled=sms,
                email_enabled=email,
                message_template=DEFAULT_TEMPLATES.get(event_type),
                is_active=True,
            )
            db.add(ns)
        await db.flush()
        settings = (await db.execute(
            select(NotificationSetting).where(NotificationSetting.school_id == school_id)
        )).scalars().all()

    return {
        "settings": [
            {
                "id": s.id,
                "event_type": s.event_type,
                "sms_enabled": s.sms_enabled,
                "email_enabled": s.email_enabled,
                "message_template": s.message_template or DEFAULT_TEMPLATES.get(s.event_type, ""),
                "template_variables": TEMPLATE_VARIABLES.get(s.event_type, []),
                "is_active": s.is_active,
            }
            for s in settings
        ]
    }


@router.put("/notification-settings/{setting_id}")
async def update_notification_setting(
    setting_id: int,
    data: dict,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a single notification setting."""
    from app.models.notification_setting import TEMPLATE_VARIABLES, NotificationSetting
    school_id = get_school_id(user)
    setting = (await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.id == setting_id,
            NotificationSetting.school_id == school_id,
        )
    )).scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Parametre introuvable")

    # Validate template variables if template is being updated
    if "message_template" in data:
        template = data["message_template"]
        allowed = TEMPLATE_VARIABLES.get(setting.event_type, [])
        # Extract used variables from template
        import re
        used_vars = re.findall(r"\{[^}]+\}", template)
        for var in used_vars:
            if var not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Variable {var} non autorisee pour cet evenement. Variables autorisees: {', '.join(allowed)}"
                )
        setting.message_template = template

    if "sms_enabled" in data:
        setting.sms_enabled = bool(data["sms_enabled"])
    if "email_enabled" in data:
        setting.email_enabled = bool(data["email_enabled"])
    if "is_active" in data:
        setting.is_active = bool(data["is_active"])

    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="school.notifications.update", resource="notification_setting", resource_id=setting.id, details={"event_type": setting.event_type, "fields": list(data.keys())})
    return {"message": "Parametre mis a jour", "id": setting.id}


@router.post("/school-profile/logo")
async def upload_school_logo(
    file: UploadFile = File(...),
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload and set the school logo."""
    import os
    import uuid
    school_id = get_school_id(user)
    school = (await db.execute(
        select(School).where(School.id == school_id)
    )).scalar_one_or_none()
    if not school:
        raise HTTPException(status_code=404, detail="Ecole introuvable")

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Type de fichier non autorise. Utilisez JPG, PNG, GIF ou WebP.")

    # Validate file size (max 5MB)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 5 Mo).")

    # Validate file type by real bytes signature (not just the client Content-Type)
    try:
        from app.core.security import validate_image_upload
        ext = validate_image_upload(
            content,
            file.filename,
            file.content_type,
            allowed_ext={"jpg", "png", "gif", "webp"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Type de fichier non autorise. Utilisez JPG, PNG, GIF ou WebP. ({e})") from e

    # Save file — dans le dossier uploads persistant (UPLOAD_DIR)
    filename = f"school_{school_id}_{uuid.uuid4().hex[:8]}.{ext}"
    from app.core.config import get_settings

    upload_dir = get_settings().upload_path / "logos"
    os.makedirs(upload_dir, exist_ok=True)
    filepath = upload_dir / filename
    with open(filepath, "wb") as f:
        f.write(content)

    # Update school logo_url
    logo_url = f"/uploads/logos/{filename}"
    school.logo_url = logo_url
    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="school.logo.update", resource="school", resource_id=school_id)
    return {"message": "Logo mis a jour", "logo_url": logo_url}


@router.get("/settings")
async def get_settings(
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    settings = (await db.execute(
        select(SchoolSetting).where(SchoolSetting.school_id == school_id)
    )).scalars().all()

    return {"settings": {s.key: s.value for s in settings}}


@router.put("/settings")
async def update_settings(
    data: SettingsUpdate,
    user: User = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    await require_write_access(db, school_id)

    for key, value in data.settings.items():
        existing = (await db.execute(
            select(SchoolSetting).where(
                SchoolSetting.school_id == school_id,
                SchoolSetting.key == key,
            )
        )).scalar_one_or_none()

        if existing:
            existing.value = value
        else:
            db.add(SchoolSetting(school_id=school_id, key=key, value=value))

    await db.flush()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=school_id, user_id=user.id, action="school.settings.update", resource="school_setting", details={"keys": list(data.settings.keys())})
    return {"message": "Paramètres mis à jour", "updated": len(data.settings)}


# ══════════════════════════════════════════════════════════════
# SPECIALITES ENSEIGNANTS
# ══════════════════════════════════════════════════════════════


class TeacherSpecialtyUpdate(BaseModel):
    subject_ids: list[int]


@router.get("/teachers/{teacher_id}/specialties")
async def get_teacher_specialties(
    teacher_id: int,
    user: User = Depends(require_permission("user.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get specialties for a teacher."""
    school_id = get_school_id(user)
    from app.models.teacher_subject import TeacherSubject
    rows = (await db.execute(
        select(TeacherSubject, Subject)
        .join(Subject, Subject.id == TeacherSubject.subject_id)
        .where(TeacherSubject.school_id == school_id, TeacherSubject.teacher_id == teacher_id)
    )).all()
    return {
        "specialties": [
            {"id": ts.id, "subject_id": s.id, "subject_name": s.name, "level_preference": ts.level_preference}
            for ts, s in rows
        ]
    }


@router.put("/teachers/{teacher_id}/specialties")
async def update_teacher_specialties(
    teacher_id: int,
    data: TeacherSpecialtyUpdate,
    user: User = Depends(require_permission("user.update")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Replace all specialties for a teacher."""
    school_id = get_school_id(user)
    from app.models.teacher_subject import TeacherSubject
    # Delete existing
    existing = (await db.execute(
        select(TeacherSubject).where(
            TeacherSubject.school_id == school_id,
            TeacherSubject.teacher_id == teacher_id,
        )
    )).scalars().all()
    for e in existing:
        await db.delete(e)
    # Add new
    added = 0
    for subject_id in data.subject_ids:
        # Verify subject belongs to school
        subject = (await db.execute(
            select(Subject).where(Subject.id == subject_id, Subject.school_id == school_id)
        )).scalar_one_or_none()
        if subject:
            db.add(TeacherSubject(school_id=school_id, teacher_id=teacher_id, subject_id=subject_id))
            added += 1
    await db.flush()
    return {"message": f"{added} spécialités enregistrées", "count": added}
