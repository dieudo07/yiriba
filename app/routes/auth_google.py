"""Yiriba SaaS — Google OAuth routes.

Flow:
  1. GET /api/auth/google  → redirects to Google consent screen
  2. GET /api/auth/google/callback?code=...&state=... → exchanges code for tokens,
     fetches user info, creates/finds user, returns JWT via redirect to frontend.

Security:
  - Le paramètre `state` est un jeton aléatoire stocké côté serveur (avec le
    school_slug et une expiration) et validé au callback (anti-CSRF).
  - Le lookup utilisateur est filtré par école : jamais de prise de compte
    cross-école.
  - Un nouvel utilisateur est créé en statut PENDING : validation par le
    directeur requise avant tout accès.

Configuration:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI in .env
"""

import logging
import secrets
import threading
import time
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token
from app.models.user import User, UserRole, UserStatus

logger = logging.getLogger("yiriba")

router = APIRouter(tags=["auth-google"])
settings = get_settings()

# ── Google OAuth endpoints ───────────────────────────────────────
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# ── Server-side OAuth state store ────────────────────────────────
# state_token -> {"school_slug": str, "expires_at": float}
_OAUTH_STATE_TTL = 600  # 10 minutes
_oauth_states: dict[str, dict] = {}
_oauth_lock = threading.Lock()


def _new_oauth_state(school_slug: str) -> str:
    """Generate a random state token and remember it server-side."""
    state = secrets.token_urlsafe(32)
    with _oauth_lock:
        _purge_oauth_states()
        _oauth_states[state] = {
            "school_slug": school_slug,
            "expires_at": time.monotonic() + _OAUTH_STATE_TTL,
        }
    return state


def _consume_oauth_state(state: str) -> str:
    """Validate and consume a state token. Returns the tied school_slug or ''."""
    with _oauth_lock:
        _purge_oauth_states()
        record = _oauth_states.pop(state, None)
    if record is None:
        return ""
    return record["school_slug"] or ""


def _purge_oauth_states() -> None:
    now = time.monotonic()
    expired = [s for s, r in _oauth_states.items() if r["expires_at"] < now]
    for s in expired:
        _oauth_states.pop(s, None)


@router.get("/api/auth/google")
async def google_login(school_slug: str = Query(default="")):
    """Redirect the user to Google's OAuth consent screen.

    Optionally accepts a school_slug query param so the user can be
    associated with the correct school after login.
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=501,
            detail="Google OAuth n'est pas configuré. Contactez l'administrateur.",
        )

    state = _new_oauth_state(school_slug.strip())

    # Build the redirect URI
    redirect_uri = settings.GOOGLE_REDIRECT_URI

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url)


@router.get("/api/auth/google/callback")
async def google_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback from Google.

    1. Validate the CSRF state token (server-side check)
    2. Exchange authorization code for access token
    3. Fetch user info (email, name, picture)
    4. Find or create user in DB (scoped to the school)
    5. Generate JWT tokens
    6. Redirect to frontend with tokens in URL fragment
    """
    # ── Step 0: Handle errors from Google ─────────────────────────
    if error:
        return RedirectResponse(
            url=f"/?error={urllib.parse.quote(error)}",
            status_code=302,
        )

    if not code:
        return RedirectResponse(
            url="/?error=code_manquant",
            status_code=302,
        )

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return RedirectResponse(
            url="/?error=oauth_non_configuré",
            status_code=302,
        )

    # ── Step 0b: Validate state (anti-CSRF) ───────────────────────
    if not state:
        return RedirectResponse(url="/?error=state_invalide", status_code=302)

    school_slug = _consume_oauth_state(state)

    # ── Step 1: Exchange code for tokens ──────────────────────────
    redirect_uri = settings.GOOGLE_REDIRECT_URI

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )

    if token_response.status_code != 200:
        return RedirectResponse(
            url="/?error=token_echange_failed",
            status_code=302,
        )

    token_data = token_response.json()
    access_token_google = token_data.get("access_token")

    if not access_token_google:
        return RedirectResponse(
            url="/?error=access_token_manquant",
            status_code=302,
        )

    # ── Step 2: Fetch user info from Google ───────────────────────
    async with httpx.AsyncClient() as client:
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token_google}"},
            timeout=15,
        )

    if userinfo_response.status_code != 200:
        return RedirectResponse(
            url="/?error=userinfo_failed",
            status_code=302,
        )

    google_user = userinfo_response.json()
    email = google_user.get("email", "").lower().strip()
    first_name = google_user.get("given_name", "")
    last_name = google_user.get("family_name", "")
    avatar_url = google_user.get("picture", "")

    if not email:
        return RedirectResponse(
            url="/?error=email_manquant",
            status_code=302,
        )

    # ── Step 3: Resolve school from the state-issued slug ─────────
    from app.models.school import School

    school = None
    if school_slug:
        school_result = await db.execute(
            select(School).where(School.slug == school_slug)
        )
        school = school_result.scalar_one_or_none()

    if not school:
        return RedirectResponse(
            url="/?error=ecole_non_trouvee",
            status_code=302,
        )

    # ── Step 4: Find or create user in DB (scoped to this school) ─
    query = select(User).where(
        User.email == email,
        User.school_id == school.id,
    )
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if user:
        # ── Existing user: update avatar if needed ────────────────
        if avatar_url and user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            await db.commit()
    else:
        # Check the email does not exist in another school (no silent
        # cross-tenant takeover).
        other = (await db.execute(
            select(User).where(User.email == email)
        )).scalar_one_or_none()
        if other:
            return RedirectResponse(
                url="/?error=email_deja_utilisee",
                status_code=302,
            )

        # Create user with student role (default for Google sign-in).
        # Status PENDING: le directeur doit valider le compte avant l'accès.
        user = User(
            email=email,
            first_name=first_name or "Utilisateur",
            last_name=last_name or "Google",
            password_hash="",  # No password for OAuth users
            school_id=school.id,
            role_type=UserRole.STUDENT,
            status=UserStatus.PENDING,
            is_active=True,
            avatar_url=avatar_url,
            failed_login_count=0,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # ── Step 5: Generate JWT tokens ───────────────────────────────
    token_payload = {
        "sub": str(user.id),
        "school_id": user.school_id,
        "role": user.role_type.value,
        "email": user.email,
    }

    yiriba_access = create_access_token(token_payload)
    yiriba_refresh = create_refresh_token(token_payload)

    # ── Step 6: Redirect to frontend with tokens ──────────────────
    # Use URL fragment (#) so tokens are in the client-side only
    fragment = urllib.parse.urlencode(
        {
            "token": yiriba_access,
            "refresh": yiriba_refresh,
        }
    )

    return RedirectResponse(
        url=f"/#google-auth={fragment}",
        status_code=302,
    )
