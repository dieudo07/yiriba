"""Yiriba SaaS — Auth routes: login, register, refresh, confirm account."""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

settings = get_settings()
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_confirmation_token,
    hash_password,
    validate_password,
    verify_password,
)
from app.models.user import User, UserRole, UserStatus

logger = logging.getLogger("yiriba")

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str  # Accepte email OU identifiant YIRIBA (username)
    password: str
    school_slug: str | None = None  # Pour distinguer admin/teacher/parent


class RegisterSchoolRequest(BaseModel):
    # ── École ─────────────────────────────────────────────────
    school_name: str = Field(..., min_length=2, max_length=200)
    school_type: str = Field(default="college", pattern=r"^(maternelle|primaire|college|lycee|complexe|autre)$")
    school_city: str | None = Field(default=None, max_length=100)
    # ── Directeur ─────────────────────────────────────────────
    admin_first_name: str = Field(..., min_length=1, max_length=100)
    # ── Forfait ───────────────────────────────────────────────
    plan_code: str = Field(default="graine", pattern=r"^(graine|racine|baobab)$")
    admin_last_name: str = Field(..., min_length=1, max_length=100)
    admin_email: str = Field(..., max_length=200)
    admin_phone: str | None = Field(default=None, max_length=30)
    # ── Conformité & anti-bot ─────────────────────────────────
    cgv_accepted: bool = True
    turnstile_token: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


@router.get("/subscription-plans")
async def list_subscription_plans(db: AsyncSession = Depends(get_db)) -> dict:
    """Public endpoint: list available subscription plans for registration."""
    import json

    from app.models.subscription import SubscriptionPlan
    plans = (await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.is_active == True).order_by(SubscriptionPlan.id)
    )).scalars().all()
    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "code": p.code,
                "max_students": p.max_students,
                "trial_days": p.trial_days,
                "price_per_student_year": float(p.price_per_student_year),
                "features": json.loads(p.features) if p.features else {},
            }
            for p in plans
        ]
    }


class ConfirmAccountRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=200)
    school_slug: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


# ── Routes ────────────────────────────────────────────────────────


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Authenticate a user and return JWT tokens.

    Accepts email OR YIRIBA username (YRB-XXXXXX) for student login.
    """
    ip = request.client.host if request.client else "unknown"

    identifier = body.email.strip()
    is_yiriba_id = identifier.upper().startswith("YRB-") or identifier.upper().startswith("YIRIBA-")

    if is_yiriba_id:
        # Login by YIRIBA ID (students)
        query = select(User).where(User.username == identifier.upper())
    else:
        # Login by email
        query = select(User).where(User.email == identifier.lower())

    # If school_slug provided, filter by school to avoid cross-tenant collision
    if body.school_slug:
        from app.models.school import School
        school = (await db.execute(
            select(School).where(School.slug == body.school_slug)
        )).scalar_one_or_none()
        if school:
            query = query.where(User.school_id == school.id)

    users_found = (await db.execute(query)).scalars().all()
    if len(users_found) == 0:
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect")
    if len(users_found) > 1:
        # Multiple users with same email in different schools — need school_slug
        if not body.school_slug:
            raise HTTPException(status_code=400, detail="Plusieurs comptes existent avec cet identifiant. Veuillez préciser le sigle de l'école.")
    user = users_found[0]

    if user.locked_until and user.locked_until.replace(tzinfo=UTC) > datetime.now(UTC):
        raise HTTPException(
            status_code=423,
            detail="Compte temporairement verrouillé. Réessayez plus tard.",
        )

    if not verify_password(body.password, user.password_hash):
        # Increment failed count
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
        from app.services.audit_service import safe_audit
        await safe_audit(db, school_id=user.school_id, user_id=user.id, action="login.failure", resource="user", resource_id=user.id, details={"reason": "wrong_password", "ip": ip})
        await db.commit()
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=403,
            detail="Compte non activé. En attente de validation par le directeur.",
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")

    # Update login info
    user.last_login_at = datetime.now(UTC)
    user.last_login_ip = ip
    user.failed_login_count = 0
    user.locked_until = None
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=user.school_id, user_id=user.id, action="login.success", resource="user", resource_id=user.id, details={"ip": ip})
    await db.commit()

    # Create tokens
    token_data = {
        "sub": str(user.id),
        "school_id": user.school_id,
        "role": user.role_type.value,
        "email": user.email,
        "must_change_pwd": user.must_change_password,
    }
    access = create_access_token(token_data)
    refresh = create_refresh_token(token_data)

    body_out = {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "must_change_password": user.must_change_password,
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role_type": user.role_type.value,
            "school_id": user.school_id,
            "status": user.status.value,
        },
    }
    # Cookie HttpOnly de session — permet d'ouvrir les PDF (bulletins, reçus)
    # dans un nouvel onglet même sans query param ?token=.
    response = JSONResponse(content=body_out)
    response.set_cookie(
        "yiriba_access", access,
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True, samesite="lax", path="/",
    )
    return response


@router.post("/change-password")
async def change_password(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change password (first login flow or manual). Requires valid JWT token."""
    # Extract user from Authorization header manually (no specific permission needed)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token manquant")
    token = auth_header.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token invalide")
    user = (await db.execute(select(User).where(User.id == int(payload["sub"])))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")

    new_password = body.get("new_password", "")
    valid, msg = validate_password(new_password)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.temp_password_displayed = False
    await db.commit()
    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=user.school_id, user_id=user.id, action="user.password_change", resource="user", resource_id=user.id)

    # Issue a new JWT with must_change_pwd = false so frontend doesn't loop
    new_access = create_access_token({
        "sub": str(user.id),
        "school_id": user.school_id,
        "role": user.role_type.value if hasattr(user.role_type, 'value') else user.role_type,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
    })
    new_refresh = create_refresh_token({
        "sub": str(user.id),
        "school_id": user.school_id,
        "role": user.role_type.value if hasattr(user.role_type, 'value') else user.role_type,
    })
    return {
        "message": "Mot de passe changé avec succès",
        "access_token": new_access,
        "refresh_token": new_refresh,
        "must_change_password": False,
    }


@router.post("/refresh")
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a new access token using a refresh token."""
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Refresh token invalide")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="Utilisateur invalide")

    token_data = {
        "sub": str(user.id),
        "school_id": user.school_id,
        "role": user.role_type.value,
        "email": user.email,
    }
    access = create_access_token(token_data)
    refresh = create_refresh_token(token_data)

    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
    }


@router.get("/registration-config")
async def registration_config() -> dict:
    """Configuration publique du formulaire d'inscription (anti-bot, confirmation email)."""
    settings = get_settings()
    return {
        "captcha_provider": "turnstile",
        "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
        "require_email_confirmation": settings.REQUIRE_EMAIL_CONFIRMATION,
    }


async def _verify_turnstile(token: str | None) -> bool:
    """Vérifie le token Turnstile côté serveur. Skip si le captcha n'est pas configuré."""
    settings = get_settings()
    if not settings.captcha_enabled:
        return True
    if not token:
        return False
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": settings.TURNSTILE_SECRET_KEY, "response": token},
        )
        return resp.status_code == 200 and resp.json().get("success") is True


async def _activate_account(user: User, db: AsyncSession) -> dict:
    """Active le compte d'un directeur après vérification de l'email."""
    user.status = UserStatus.ACTIVE
    user.confirmed_at = datetime.now(UTC)
    user.account_confirmation_token = None
    user.account_confirmation_expires_at = None
    await db.commit()
    from app.services.audit_service import safe_audit
    await safe_audit(
        db,
        school_id=user.school_id,
        user_id=user.id,
        action="user.account_confirmed",
        resource="user",
        resource_id=user.id,
    )
    return {"message": "Compte activé avec succès. Vous pouvez maintenant vous connecter."}


@router.post("/confirm-account")
async def confirm_account(
    body: ConfirmAccountRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Active un compte via le token envoyé par email (lien à usage unique)."""
    token = body.token.strip()
    user = (await db.execute(
        select(User).where(User.account_confirmation_token == token)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Lien invalide ou expiré.")

    if user.status == UserStatus.ACTIVE:
        user.account_confirmation_token = None
        user.account_confirmation_expires_at = None
        await db.commit()
        return {"message": "Compte déjà activé.", "already_active": True}

    expires = user.account_confirmation_expires_at
    if expires is None or expires.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Lien invalide ou expiré.")

    if user.status not in (UserStatus.PENDING, UserStatus.SUSPENDED):
        raise HTTPException(status_code=400, detail="Ce compte ne peut pas être activé.")

    return await _activate_account(user, db)


@router.post("/register-school")
async def register_school(
    body: RegisterSchoolRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Register a new school with auto-generated admin account.

    Auto-generates: slug, YIRIBA-XXXXXX identifier, temporary password.
    Admin must change password on first login.
    Returns confirmation page data (no auto-login).
    """
    import re
    import unicodedata
    from datetime import date, timedelta

    from app.models.academic_year import AcademicYear
    from app.models.school import School
    from app.models.subscription import Subscription, SubscriptionPlan, SubscriptionStatus
    from app.services.student_service import generate_temp_password

    # ── Auto-generate slug from school name ───────────────────
    def slugify(text: str) -> str:
        text = unicodedata.normalize('NFKD', text)
        text = text.encode('ascii', 'ignore').decode('ascii')
        text = text.lower().strip()
        text = re.sub(r'[^a-z0-9]+', '-', text)
        text = text.strip('-')
        return text

    base_slug = slugify(body.school_name)
    slug = base_slug
    counter = 1
    while (await db.execute(select(School).where(School.slug == slug))).scalar_one_or_none():
        slug = f"{base_slug}-{counter}"
        counter += 1

    # ── CGU obligatoires + anti-bot ───────────────────────────
    if not body.cgv_accepted:
        raise HTTPException(
            status_code=400,
            detail=(
                "Vous devez accepter les conditions d'utilisation "
                "et la politique de confidentialité."
            ),
        )

    settings = get_settings()
    if not await _verify_turnstile(body.turnstile_token):
        raise HTTPException(
            status_code=400,
            detail="Vérification anti-robot échouée. Veuillez réessayer.",
        )

    # ── Check duplicate email ─────────────────────────────────
    email_lower = body.admin_email.lower().strip()
    email_count = (await db.execute(
        select(func.count()).select_from(User).where(User.email == email_lower)
    )).scalar()
    if email_count and email_count > 0:
        raise HTTPException(status_code=409, detail="Cet email est déjà utilisé")

    # ── Auto-generate YIRIBA identifier for admin ─────────────
    async def generate_yiriba_admin_id() -> str:
        result = await db.execute(
            select(func.count()).select_from(User).where(User.username.like("YIRIBA-%"))
        )
        count = (result.scalar() or 0) + 1
        yiriba_id = f"YIRIBA-{count:06d}"
        while (await db.execute(
            select(User.id).where(User.username == yiriba_id)
        )).scalar_one_or_none() is not None:
            count += 1
            yiriba_id = f"YIRIBA-{count:06d}"
        return yiriba_id

    yiriba_id = await generate_yiriba_admin_id()
    temp_password = generate_temp_password()

    # ── Confirmation email ? ──────────────────────────────────
    confirm_mode = settings.REQUIRE_EMAIL_CONFIRMATION
    confirmation_token = None
    if confirm_mode:
        confirmation_token = generate_confirmation_token()

    # ── Create school ────────────────────────────────────────
    school = School(
        name=body.school_name.strip(),
        slug=slug,
        school_type=body.school_type,
        email=email_lower,
        phone=body.admin_phone,
        city=body.school_city,
    )
    db.add(school)
    await db.flush()

    # ── Create admin user ────────────────────────────────────
    user = User(
        school_id=school.id,
        email=email_lower,
        username=yiriba_id,
        first_name=body.admin_first_name.strip(),
        last_name=body.admin_last_name.strip(),
        phone=body.admin_phone,
        password_hash=hash_password(temp_password),
        role_type=UserRole.ADMIN,
        status=UserStatus.PENDING if confirm_mode else UserStatus.ACTIVE,
        must_change_password=True,
        is_active=True,
        account_confirmation_token=confirmation_token,
        account_confirmation_expires_at=(
            datetime.now(UTC) + timedelta(hours=settings.CONFIRMATION_TOKEN_TTL_HOURS)
            if confirm_mode else None
        ),
    )
    db.add(user)
    await db.flush()

    # ── Default roles ────────────────────────────────────────
    from app.core.seeds import seed_school_roles
    roles = await seed_school_roles(db, school.id)
    if "Directeur" in roles:
        user.role_id = roles["Directeur"].id

    # ── Default academic year ────────────────────────────────
    current_year = date.today().year
    academic_year = AcademicYear(
        school_id=school.id,
        name=f"{current_year}-{current_year + 1}",
        start_date=date(current_year, 9, 1),
        end_date=date(current_year + 1, 6, 30),
        is_current=True,
        is_active=True,
    )
    db.add(academic_year)

    # ── Subscription (selected plan) ─────────────────────────
    selected_plan = (await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.code == body.plan_code)
    )).scalar_one_or_none()

    if selected_plan:
        now = datetime.now(UTC)
        is_trial = selected_plan.trial_days > 0
        sub_status = SubscriptionStatus.TRIAL if is_trial else SubscriptionStatus.ACTIVE
        trial_end = now + timedelta(days=selected_plan.trial_days) if is_trial else None
        ends = trial_end if is_trial else None
        amount = Decimal("0")  # Free trial or pending payment for Racine/Baobab

        subscription = Subscription(
            school_id=school.id,
            plan_id=selected_plan.id,
            status=sub_status,
            started_at=now,
            trial_ends_at=trial_end,
            ends_at=ends,
            student_count_at_billing=0,
            amount=amount,
        )
        db.add(subscription)

        # Update school
        school.current_plan_id = selected_plan.id
        school.subscription_status = sub_status.value
        school.trial_ends_at = trial_end

    # ── Audit (AVANT commit : ne laisse aucune transaction orpheline) ──
    from app.services.audit_service import safe_audit
    await safe_audit(
        db,
        school_id=school.id,
        user_id=user.id,
        action="account.register",
        resource="school",
        resource_id=school.id,
        details={
            "school_name": school.name,
            "admin_yiriba_id": yiriba_id,
            "cgv_accepted": body.cgv_accepted,
        },
    )

    await db.commit()

    # ── Envoi email de confirmation (si activé) ─────────────
    confirmation_url = None
    if confirm_mode:
        base_url = settings.SERVER_URL.rstrip("/")
        confirmation_url = f"{base_url}/static/confirm.html?token={confirmation_token}"
        from app.services.email_service import send_email
        email_sent = send_email(
            to_address=email_lower,
            subject="Activez votre compte YIRIBA",
            html=(
                f"<p>Bonjour {user.first_name},</p>"
                f"<p>Votre établissement <strong>{school.name}</strong> a été créé "
                f"sur la plateforme YIRIBA.</p>"
                f"<p>Votre identifiant de connexion est : <strong>{yiriba_id}</strong><br>"
                f"Votre mot de passe temporaire est : <strong>{temp_password}</strong></p>"
                f"<p>Cliquez sur le lien ci-dessous pour activer votre compte :</p>"
                f"<p><a href=\"{confirmation_url}\">{confirmation_url}</a></p>"
                f"<p>Ce lien expire dans {settings.CONFIRMATION_TOKEN_TTL_HOURS} heures.</p>"
            ),
        )
    else:
        email_sent = False

    # ── Return confirmation (NO auto-login) ─────────────────
    plan_info = None
    if selected_plan:
        plan_info = {
            "name": selected_plan.name,
            "code": selected_plan.code,
            "max_students": selected_plan.max_students,
            "trial_days": selected_plan.trial_days,
            "price_per_student_year": float(selected_plan.price_per_student_year),
            "status": subscription.status.value,
            "trial_ends_at": str(subscription.trial_ends_at) if subscription.trial_ends_at else None,
        }

    admin_payload = {
        "yiriba_id": yiriba_id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
    }
    if not confirm_mode or not settings.is_production:
        admin_payload["temp_password"] = temp_password

    payload = {
        "success": True,
        "school": {
            "id": school.id,
            "name": school.name,
            "slug": school.slug,
        },
        "admin": admin_payload,
        "subscription": plan_info,
        "message": (
            "Établissement créé avec succès. Un email de confirmation a été envoyé au "
            "directeur : activez votre compte avec le lien reçu."
            if confirm_mode and email_sent
            else (
                "Établissement créé avec succès. Un email de confirmation a été préparé "
                "(non envoyé, SMTP non configuré). Utilisez le lien de confirmation fourni."
                if confirm_mode
                else (
                    "Établissement créé avec succès. Conservez précieusement votre "
                    "identifiant et mot de passe."
                )
            )
        ),
    }
    if confirm_mode:
        payload["confirmation_required"] = True
        payload["confirmation_url"] = confirmation_url if not settings.is_production else None

    return payload


@router.get("/schools")
async def list_schools(db: AsyncSession = Depends(get_db)) -> dict:
    """List all active schools (for login page)."""
    from app.models.school import School

    result = await db.execute(select(School).where(School.is_active == True))  # noqa: E712
    schools = result.scalars().all()

    return {
        "schools": [
            {"id": s.id, "name": s.name, "slug": s.slug, "logo_url": s.logo_url}
            for s in schools
        ]
    }


# -- Password Reset -------------------------------------------------


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request a password reset link.

    Always returns success to prevent email enumeration.
    If the email exists, stores a reset token.
    """
    email = body.email.lower().strip()
    query = select(User).where(User.email == email)

    # Filter by school if slug provided
    if body.school_slug:
        from app.models.school import School
        school = (await db.execute(
            select(School).where(School.slug == body.school_slug)
        )).scalar_one_or_none()
        if school:
            query = query.where(User.school_id == school.id)

    user = (await db.execute(query)).scalar_one_or_none()

    # Always return success to prevent email enumeration
    if user:
        reset_token = generate_confirmation_token()
        user.confirmation_token = reset_token
        user.reset_token_expires_at = datetime.now(UTC) + timedelta(hours=1)
        await db.commit()

        # Send the reset link out of band (email in production; server log in dev).
        from app.services.email_service import send_email

        base_url = get_settings().SERVER_URL.rstrip("/")
        reset_url = f"{base_url}/static/reset-password.html?token={reset_token}"
        send_email(
            to_address=user.email,
            subject="Réinitialiser votre mot de passe YIRIBA",
            html=(
                f"<p>Bonjour {user.first_name},</p>"
                f"<p>Cliquez sur le lien ci-dessous pour choisir un nouveau mot de passe :</p>"
                f"<p><a href=\"{reset_url}\">{reset_url}</a></p>"
                f"<p>Ce lien expire dans 1 heure. Si vous n'êtes pas à l'origine "
                f"de cette demande, ignorez cet email.</p>"
            ),
        )

    return {
        "message": "Si un compte est associe a cette adresse, vous recevrez un lien de reinitialisation.",
    }


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reset password using a valid reset token."""
    user = (await db.execute(
        select(User).where(User.confirmation_token == body.token)
    )).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Lien invalide ou expire.")

    # Token a usage unique + expiration
    if user.reset_token_expires_at is None or user.reset_token_expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Lien invalide ou expire.")

    # Validate password complexity
    is_valid, msg = validate_password(body.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=msg)

    # Update password and clear token
    user.password_hash = hash_password(body.new_password)
    user.confirmation_token = None
    user.reset_token_expires_at = None
    user.failed_login_count = 0
    user.locked_until = None
    user.must_change_password = False
    await db.commit()

    from app.services.audit_service import safe_audit
    await safe_audit(db, school_id=user.school_id, user_id=user.id, action="account.password_reset", resource="user", resource_id=user.id)

    return {"message": "Mot de passe reinitialise avec succes."}


@router.post("/logout")
async def logout() -> dict:
    """Log out: clear the session cookie (client discards its tokens)."""
    response = JSONResponse(content={"message": "Deconnecte."})
    response.delete_cookie("yiriba_access", path="/")
    return response
