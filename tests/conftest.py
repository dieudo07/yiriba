"""Yiriba SaaS — Test configuration with async fixtures."""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

# Rate limiting désactivé pour les tests (la suite réalise de nombreux
# logins depuis la même IP dans la même minute).
os.environ["RATE_LIMIT_LOGIN"] = "0"
os.environ["RATE_LIMIT_API"] = "0"

# Captcha (Turnstile) désactivé pour les tests : pas de secret configuré,
# _verify_turnstile renverra toujours True.
os.environ["TURNSTILE_SECRET_KEY"] = ""

# Confirmation d'email désactivée pour les tests : les comptes créés via
# /register-school doivent être immédiatement ACTIVE (login possible).
os.environ["REQUIRE_EMAIL_CONFIRMATION"] = "false"

# Éditeur YIRIBA (platform_admin) pour les tests : un admin d'école dont
# l'email figure dans PLATFORM_ADMIN_EMAILS accède aux routes réservées éditeur.
os.environ.setdefault("PLATFORM_ADMIN_EMAILS", "platform@yiriba.com")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.core.seeds import backfill_roles_for_existing_schools, seed_permissions, seed_subscription_plans
from app.main import app
from app.models.school import School
from app.models.user import User, UserRole, UserStatus

# ── Test Database ─────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_yiriba.db"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30},
)
test_session_factory = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """Create all tables once for the test session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed permissions + subscription plans + backfill roles
    async with test_session_factory() as db:
        await seed_permissions(db)
        await seed_subscription_plans(db)
        await backfill_roles_for_existing_schools(db)
        await _ensure_platform_admin(db)

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh database session for each test, rolled back after."""
    async with test_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Yield an async HTTP client bound to the test app with test DB."""

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Helpers ─────────────────────────────────────────────────────

_EDITOR_EMAIL = "platform@yiriba.com"


async def _ensure_platform_admin(db: AsyncSession) -> None:
    """Créer (une seule fois, persistante) l'éditeur YIRIBA.

    `require_platform_admin` vérifie user.email ∈ PLATFORM_ADMIN_EMAILS.
    register-school commit réellement : impossible d'en créer via HTTP à
    chaque test (email unique). On le crée donc directement au setup.
    """
    from sqlalchemy import select

    existing = (await db.execute(
        select(User).where(User.email == _EDITOR_EMAIL)
    )).scalar_one_or_none()
    if existing:
        return

    school = School(
        name="Plateforme YIRIBA",
        slug="plateforme-yiriba",
        short_name="YRB",
        school_type="autre",
        country="Burkina Faso",
        city="Ouaga",
    )
    db.add(school)
    await db.flush()

    platform_admin = User(
        school_id=school.id,
        email=_EDITOR_EMAIL,
        first_name="Editeur",
        last_name="YIRIBA",
        password_hash=hash_password("EditorPass123!"),
        role_type=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        is_active=True,
        must_change_password=False,
    )
    db.add(platform_admin)
    await db.commit()


async def platform_admin_token() -> str:
    """Minter un token valide pour le compte éditeur YIRIBA (persistant)."""
    from sqlalchemy import select

    async with test_session_factory() as db:
        user = (await db.execute(
            select(User).where(User.email == _EDITOR_EMAIL)
        )).scalar_one()
        return create_access_token({
            "sub": str(user.id),
            "school_id": user.school_id,
            "role": user.role_type.value,
            "email": user.email,
            "must_change_pwd": False,
        })


async def register_and_login(
    client: AsyncClient,
    name: str = "Ecole Test",
    *,
    email: str | None = None,
    **extra: object,
) -> dict:
    """Créer une école puis se connecter avec le mot de passe temporaire.

    register-school n'effectue volontairement AUCUN auto-login et ne
    renvoie pas de token : il retourne un mot de passe temporaire.
    Ce helper encapsule le flow complet registre → login.

    Paramètre `email` : force l'email admin (ex. un compte éditeur YIRIBA
    dont l'adresse figure dans PLATFORM_ADMIN_EMAILS).
    """
    uid = str(uuid.uuid4())[:8]
    slug = f"{name.lower().replace(' ', '-')}-{uid}"
    email = email or f"admin_{slug}@test.com"
    payload = {
        "school_name": name,
        "school_slug": slug,
        "school_short_name": name[:3].upper(),
        "school_type": "college",
        "school_country": "Burkina Faso",
        "school_city": "Ouaga",
        "admin_first_name": "Admin",
        "admin_last_name": "Test",
        "admin_email": email,
        "admin_password": "Test1234!",
        "admin_phone": f"+226{uid[:8]}",
        **extra,
    }
    res = await client.post("/api/auth/register-school", json=payload)
    data = res.json()
    temp_password = data["admin"]["temp_password"]

    login_res = await client.post(
        "/api/auth/login", json={"email": email, "password": temp_password}
    )
    login_data = login_res.json()

    return {
        "token": login_data.get("access_token"),
        "user_id": data.get("user", {}).get("id"),
        "school_id": data["school"]["id"],
        "email": email,
        "temp_password": temp_password,
        "register": data,
        "is_platform_admin": email.lower() == _EDITOR_EMAIL,
    }
