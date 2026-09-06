"""Yiriba SaaS — Audit logging service.

Every sensitive action (user create, grade modify, payment, role change)
is logged with who, what, when, and from where.
"""

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    school_id: int,
    user_id: int | None,
    action: str,
    resource: str,
    resource_id: int | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Log an auditable action to the database.

    Args:
        db: Async database session.
        school_id: School (tenant) ID.
        user_id: ID of the user performing the action.
        action: Action codename (e.g., "user.create", "grade.update").
        resource: Resource type (e.g., "user", "grade", "payment").
        resource_id: ID of the affected resource.
        details: Additional context (old/new values, etc.).
        ip_address: Client IP address.
        user_agent: Client user agent string.

    Returns:
        The created AuditLog instance.
    """
    log_entry = AuditLog(
        school_id=school_id,
        user_id=user_id,
        action=action,
        resource=resource,
        resource_id=resource_id,
        details=json.dumps(details, ensure_ascii=False) if details else None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(log_entry)
    await db.flush()
    return log_entry


async def log_login_success(
    db: AsyncSession,
    *,
    school_id: int,
    user_id: int,
    ip_address: str | None = None,
) -> None:
    """Log a successful login."""
    await log_action(
        db,
        school_id=school_id,
        user_id=user_id,
        action="login.success",
        resource="user",
        resource_id=user_id,
        ip_address=ip_address,
    )


async def log_login_failure(
    db: AsyncSession,
    *,
    school_id: int,
    user_id: int,
    reason: str = "wrong_password",
    ip_address: str | None = None,
) -> None:
    """Log a failed login attempt."""
    await log_action(
        db,
        school_id=school_id,
        user_id=user_id,
        action="login.failure",
        resource="user",
        resource_id=user_id,
        details={"reason": reason},
        ip_address=ip_address,
    )


async def safe_audit(
    db: AsyncSession,
    *,
    school_id: int | None = None,
    user_id: int | None = None,
    action: str,
    resource: str,
    resource_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write an audit log. NEVER raises — errors are silently swallowed.

    Use this in service functions to guarantee that a failed audit log
    never prevents the business action from completing.
    """
    try:
        await log_action(
            db,
            school_id=school_id or 0,
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
        )
    except Exception:
        pass  # Audit failure must NEVER block the business action
