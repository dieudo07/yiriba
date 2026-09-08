"""Yiriba SaaS — Database connection and session management.

Provider-agnostic : fonctionne avec SQLite (dev) et PostgreSQL (prod),
quel que soit l'hébergeur (Render, Wanekoo, VPS, ...). L'URL de base de
données est fournie via DATABASE_URL et est automatiquement normalisée
pour le driver asynchrone (asyncpg).
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger("yiriba")


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# ── Normalisation de l'URL (driver asynchrone) ───────────────────

def normalize_database_url(url: str) -> str:
    """Convertit une URL de base de données en URL asynchrone SQLAlchemy.

    - `postgresql://...` (fournie par Render/Neon/Supabase/...) -> `postgresql+asyncpg://...`
    - `postgres://...`      -> `postgresql+asyncpg://...`
    - `sqlite:///...`       -> `sqlite+aiosqlite:///...`
    - Déjà au bon format     -> inchangée.

    Permet de coller directement l'URL fournie par l'hébergeur sans
    réfléchir au driver.
    """
    url = (url or "").strip()
    if not url:
        return "sqlite+aiosqlite:///./yiriba.db"

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+asyncpg://") or url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("sqlite+aiosqlite://"):
        return url
    return url


# ── Engine & Session Factory ──────────────────────────────────────

settings = get_settings()
DATABASE_URL = normalize_database_url(settings.DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    echo=settings.APP_DEBUG and not settings.is_production,
    pool_pre_ping=True,
    # pool_recycle évite les connexions périmées sur les bases gérées
    # (Render/Neon) qui coupent les connexions inactives.
    pool_recycle=1800,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def wait_for_db(retries: int = 15, delay: float = 2.0) -> None:
    """Attend que la base soit joignable (démarrage à froid des bases gérées).

    Idempotent et non bloquant en cas de succès immédiat.
    """
    import asyncio

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 — on retente quel que soit l'échec
            last_exc = exc
            logger.warning(
                "Base de données pas encore prête (tentative %d/%d) : %s",
                attempt, retries, exc,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"Base de données injoignable après {retries} tentatives : {last_exc}")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency — yields an async DB session, auto-commits on success, rolls back on error."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# SQLite pragma for performance (dev only) — inapplicable sur PostgreSQL
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
