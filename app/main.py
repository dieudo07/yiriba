"""Yiriba SaaS — Main FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import Base, async_session_factory, engine
from app.core.seeds import (
    backfill_roles_for_existing_schools,
    seed_permissions,
    seed_subscription_plans,
)

settings = get_settings()

# ── Logging ───────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("yiriba")


# ── Lifespan (startup / shutdown) ────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: create tables + seed permissions. Shutdown: cleanup."""
    logger.info("🚀 Yiriba SaaS starting...")

    # Create tables (dev only — Alembic in production)
    if settings.APP_DEBUG:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Seed permissions + subscription plans
    async with async_session_factory() as db:
        await seed_permissions(db)
        await seed_subscription_plans(db)
        await backfill_roles_for_existing_schools(db)

    logger.info("✅ Database ready, permissions + plans seeded")

    yield

    logger.info("👋 Yiriba SaaS shutting down")
    await engine.dispose()


# ── App ───────────────────────────────────────────────────────────

app = FastAPI(
    title="Yiriba SaaS API",
    description="API de gestion scolaire multi-établissement pour le Burkina Faso",
    version="2.0.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url="/redoc" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)


# ── Security Headers ──────────────────────────────────────────────


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
    return response


# ── CORS ──────────────────────────────────────────────────────────

# En production, `*` + allow_credentials=True n'est jamais acceptable :
# on exige une liste explicite d'origines. Le wildcard (si un jour
# utilisé) interdit les credentials.
cors_origins = settings.cors_origins_list
cors_allow_credentials = "*" not in cors_origins
if settings.is_production and "*" in cors_origins:
    raise RuntimeError(
        "CORS_ORIGINS=* est interdit en production. "
        "Listez explicitement les domaines du frontend dans .env."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiting ─────────────────────────────────────────────────

from app.middleware.ratelimit import RateLimitMiddleware  # noqa: E402

app.add_middleware(
    RateLimitMiddleware,
    login_rate=settings.RATE_LIMIT_LOGIN,
    api_rate=settings.RATE_LIMIT_API,
)


# ── Routes ────────────────────────────────────────────────────────

from app.routes.academic_periods import router as academic_periods_router  # noqa: E402
from app.routes.admin import router as admin_router  # noqa: E402
from app.routes.attendance import router as attendance_router  # noqa: E402
from app.models import attendance_ext as _attendance_ext  # noqa: F401,E402 — colonnes justification/validation
from app.routes.auth import router as auth_router  # noqa: E402
from app.routes.auth_google import router as auth_google_router  # noqa: E402
from app.routes.bulletins import router as bulletins_router  # noqa: E402
from app.routes.classes import router as classes_router  # noqa: E402
from app.routes.cycles import router as cycles_router  # noqa: E402
from app.routes.discipline import router as discipline_router  # noqa: E402
from app.routes.grades import router as grades_router  # noqa: E402
from app.routes.messages import router as messages_router  # noqa: E402
from app.routes.notifications import router as notifications_router  # noqa: E402
from app.routes.onboarding import router as onboarding_router  # noqa: E402
from app.routes.parent_portal import router as parent_router  # noqa: E402
from app.routes.payments import router as payments_router  # noqa: E402
from app.routes.platform import router as platform_router  # noqa: E402
from app.routes.promotion import router as promotion_router  # noqa: E402
from app.routes.report_cards import router as report_cards_router  # noqa: E402
from app.routes.student_portal import router as student_portal_router  # noqa: E402
from app.routes.students import router as students_router  # noqa: E402
from app.routes.subscriptions import router as subscriptions_router  # noqa: E402
from app.routes.teacher_portal import router as teacher_router  # noqa: E402
from app.routes.timetable import router as timetable_router  # noqa: E402
from app.routes.verify import router as verify_router  # noqa: E402

app.include_router(academic_periods_router)
app.include_router(admin_router)
app.include_router(attendance_router)
app.include_router(auth_router)
app.include_router(auth_google_router)
app.include_router(bulletins_router)
app.include_router(report_cards_router)
app.include_router(classes_router)
app.include_router(cycles_router)
app.include_router(discipline_router)
app.include_router(grades_router)
app.include_router(messages_router)
app.include_router(notifications_router)
app.include_router(onboarding_router)
app.include_router(parent_router)
app.include_router(payments_router)
app.include_router(platform_router)
app.include_router(student_portal_router)
app.include_router(students_router)
app.include_router(promotion_router)
app.include_router(subscriptions_router)
app.include_router(teacher_router)
app.include_router(timetable_router)
app.include_router(verify_router)

# ── Static Files ──────────────────────────────────────────────────

import os
from pathlib import Path

STATIC_DIR = str(Path(__file__).resolve().parent.parent / "static")
if os.path.isdir(STATIC_DIR):
    app.mount(
        "/static",
        StaticFiles(directory=STATIC_DIR),
        name="static",
    )


@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    """Empêche le cache navigateur des assets statiques.

    Évite les décalages UI quand on déploie une nouvelle version : le
    navigateur recharge toujours la dernière version du CSS/JS.
    """
    response = await call_next(request)
    if request.url.path.startswith(("/static/", "/logo/", "/uploads/")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Mount logo directory
LOGO_DIR = str(Path(__file__).resolve().parent.parent / "logo")
if os.path.isdir(LOGO_DIR):
    app.mount("/logo", StaticFiles(directory=LOGO_DIR), name="logo")

# Mount uploads directory
UPLOADS_DIR = str(Path(__file__).resolve().parent.parent / "uploads")
if os.path.isdir(UPLOADS_DIR):
    app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")


# ── Health Check ──────────────────────────────────────────────────


@app.get("/health")
async def health_check() -> dict:
    """Healthcheck endpoint for monitoring."""
    return {"status": "ok", "service": "yiriba-saas", "version": "2.0.0"}


from fastapi.responses import FileResponse


@app.get("/")
async def root():
    """Serve the admin portal HTML."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html", headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    return {"service": "Yiriba SaaS", "version": "2.0.0", "docs": "/docs"}
