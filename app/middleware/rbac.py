"""Yiriba SaaS — RBAC dependency and OwnershipFilter middleware.

Applique la double barrière de sécurité :
1. RBAC : l'utilisateur a-t-il la permission ?
2. Ownership : la ressource lui appartient-elle ?
"""

from functools import wraps
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole
from app.models.permission import Role, RolePermission, Permission


# ── JWT Extraction ────────────────────────────────────────────────


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from JWT.

    Sources acceptées (dans l'ordre) :
    1. Header Authorization: Bearer <token>
    2. Query param ?token=<token> — pour l'ouverture des PDF dans un nouvel
       onglet (bulletins, reçus), où window.open ne peut pas envoyer de header.
    """
    token: str | None = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = request.query_params.get("token")
    if not token:
        token = request.cookies.get("yiriba_access")
    if not token:
        raise HTTPException(status_code=401, detail="Token d'authentification manquant")

    payload = decode_token(token)
    if payload is None:
        # SÉCURITÉ : ne JAMAIS logger le token ni la clé secrète.
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Type de token invalide")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Token invalide")

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable ou désactivé")
    if user.status.value != "active":
        raise HTTPException(status_code=403, detail="Compte non activé")

    # Défense en profondeur : un compte élève dont l'élève a été retiré /
    # transféré / diplômé perd l'accès immédiatement, même avec un token
    # encore valide (vérifié à CHAQUE requête API).
    if user.role_type == UserRole.STUDENT:
        from app.models.student import Student, StudentStatus
        student = (await db.execute(
            select(Student).where(Student.user_id == user.id)
        )).scalar_one_or_none()
        if student and student.status != StudentStatus.ACTIVE:
            raise HTTPException(status_code=403, detail="Ce compte élève n'est plus actif")

    # Attach school_id from token (never from client)
    user._school_id_from_token = payload.get("school_id")
    return user


def get_school_id(user: User) -> int:
    """Extract school_id from the JWT-decoded user."""
    school_id = getattr(user, "_school_id_from_token", None)
    if school_id is None:
        raise HTTPException(status_code=403, detail="École non définie dans le token")
    return int(school_id)


# ── Permission Check ──────────────────────────────────────────────


async def check_permission(
    user: User,
    codename: str,
    db: AsyncSession,
    school_id: int | None = None,
) -> bool:
    """Check if the user has a specific permission via their role.

    Returns True if allowed, False otherwise.
    """
    if user.role_type == UserRole.ADMIN:
        # Admin without an assigned role: fall back to the school's
        # "Directeur" role (auto-created at school registration) instead of
        # blocking every action. Prevents un-editable accounts when role_id
        # was never set (e.g. older accounts created before role assignment).
        if user.role_id is None:
            if user.school_id is None:
                return False
            fallback = (await db.execute(
                select(Role.id).where(
                    Role.school_id == user.school_id,
                    Role.name == "Directeur",
                )
            )).first()
            if fallback is None:
                return False
            user.role_id = fallback[0]
        result = await db.execute(
            select(RolePermission).join(Permission).where(
                RolePermission.role_id == user.role_id,
                Permission.codename == codename,
            )
        )
        return result.first() is not None

    # For teacher/parent/student, look up their role's permissions from DB
    # First try role_id if set, then fall back to finding role by role_type name
    if user.role_id is not None:
        result = await db.execute(
            select(RolePermission).join(Permission).where(
                RolePermission.role_id == user.role_id,
                Permission.codename == codename,
            )
        )
        return result.first() is not None

    # Fallback: find role by role_type name for this school
    role_name_map = {
        UserRole.TEACHER: "Enseignant",
        UserRole.PARENT: "Parent",
        UserRole.STUDENT: "Élève",
    }
    role_name = role_name_map.get(user.role_type)
    if role_name and user.school_id:
        role_rows = (await db.execute(
            select(Role.id).where(Role.school_id == user.school_id, Role.name == role_name)
        )).all()
        role_id = role_rows[0][0] if role_rows else None
        if role_id:
            result = await db.execute(
                select(RolePermission).join(Permission).where(
                    RolePermission.role_id == role_id,
                    Permission.codename == codename,
                )
            )
            return result.first() is not None

    return False


# ── FastAPI Dependencies ──────────────────────────────────────────


def require_permission(codename: str) -> Callable:
    """FastAPI dependency that checks a permission before allowing access.

    Usage:
        @router.get("/students")
        async def list_students(user=Depends(require_permission("student.read"))):
            ...
    """

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        school_id = get_school_id(user)
        if not await check_permission(user, codename, db, school_id):
            raise HTTPException(
                status_code=403,
                detail=f"Permission requise : {codename}",
            )
        return user

    return _check


def require_platform_admin() -> Callable:
    """FastAPI dependency: only YIRIBA platform admins (settings.PLATFORM_ADMIN_EMAILS).

    Tout autre utilisateur — y compris un admin d'école avec settings.manage —
    reçoit un 403. Vide par défaut : personne.
    """

    async def _check(
        user: User = Depends(get_current_user),
    ) -> User:
        settings = get_settings()
        if not user.email or user.email.lower() not in settings.platform_admin_emails:
            raise HTTPException(
                status_code=403,
                detail="Réservé à l'administration plateforme YIRIBA",
            )
        return user

    return _check


# ── Ownership Filter ──────────────────────────────────────────────


class OwnershipFilter:
    """Applies ownership filtering based on user role.

    Called AFTER RBAC permission check.
    Ensures teachers only see their classes, parents only see their children.
    """

    @staticmethod
    def for_students(user: User) -> dict[str, Any]:
        """Return filter kwargs for student queries based on user role."""
        if user.role_type == UserRole.ADMIN:
            return {}  # Admin sees all students in their school

        if user.role_type == UserRole.TEACHER:
            # Teacher sees students in their classes only (applied at query level)
            return {"_teacher_filter": user.id}

        if user.role_type == UserRole.PARENT:
            # Parent sees only their children (applied at query level)
            return {"_parent_filter": user.id}

        if user.role_type == UserRole.STUDENT:
            # Student sees only themselves
            return {"_student_filter": user.id}

        return {}

    @staticmethod
    def for_grades(user: User) -> dict[str, Any]:
        """Return filter kwargs for grade queries."""
        if user.role_type == UserRole.ADMIN:
            return {}

        if user.role_type == UserRole.TEACHER:
            return {"_teacher_filter": user.id}

        if user.role_type == UserRole.PARENT:
            return {"_parent_filter": user.id}

        if user.role_type == UserRole.STUDENT:
            return {"_student_filter": user.id}

        return {}


# ── Decorator for service-level checks ────────────────────────────


async def require_last_admin(db: AsyncSession, school_id: int, user_id: int) -> None:
    """Raise if deactivating the last admin with 'user.validate' permission.

    Called in service layer before deactivating a user.
    """
    from sqlalchemy import func as sqlfunc

    result = await db.execute(
        select(sqlfunc.count()).select_from(User).join(
            RolePermission, RolePermission.role_id == User.role_id
        ).join(
            Permission, Permission.id == RolePermission.permission_id
        ).where(
            User.school_id == school_id,
            User.status == "active",
            User.id != user_id,
            Permission.codename == "user.validate",
        )
    )
    count = result.scalar()
    if count == 0:
        raise HTTPException(
            status_code=403,
            detail="Impossible de désactiver le dernier administrateur de l'école",
        )
