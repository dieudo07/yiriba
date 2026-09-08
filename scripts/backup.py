"""Yiriba SaaS — Sauvegarde de la base de données et des fichiers uploadés.

Indépendant de l'hébergeur : fonctionne avec SQLite (dev) et PostgreSQL (prod).

Usage :
    python scripts/backup.py [--dest ./backups] [--keep 7]

- SQLite   : copie le fichier .db (dossier de backup).
- PostgreSQL : utilise `pg_dump` si présent, sinon exporte les tables via
  SQLAlchemy en JSON (fallback universel).
- Toujours copie le dossier UPLOAD_DIR (logos, photos, fichiers).

Un cron / tâche planifiée peut lancer ce script quotidiennement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.database import DATABASE_URL, normalize_database_url  # noqa: E402

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backup")


def _sqlite_path(url: str) -> Path:
    path = url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "").split("?", 1)[0]
    if not path:
        path = "yiriba.db"
    return Path(path).resolve()


def backup_sqlite(url: str, dest: Path) -> Path:
    src = _sqlite_path(url)
    if not src.exists():
        raise FileNotFoundError(f"Fichier SQLite introuvable : {src}")
    out = dest / f"yiriba_{dt.datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(src, out)
    logger.info("SQLite copié : %s -> %s", src, out)
    return out


def backup_postgres(url: str, dest: Path) -> Path:
    """pg_dump si dispo, sinon export JSON via SQLAlchemy (universel)."""
    out = dest / f"yiriba_{dt.datetime.now():%Y%m%d_%H%M%S}.dump"
    try:
        # Retire le driver async pour passer une URL valide à pg_dump.
        pg_url = url.replace("+asyncpg", "").replace("+psycopg", "")
        res = subprocess.run(
            ["pg_dump", "--no-owner", "--no-privileges", "--file", str(out), pg_url],
            capture_output=True, text=True, timeout=300,
        )
        if res.returncode == 0 and out.exists() and out.stat().st_size > 0:
            logger.info("PostgreSQL dump pg_dump : %s", out)
            return out
        logger.warning("pg_dump indisponible ou échec (%s), fallback JSON.", res.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("pg_dump non disponible (%s), fallback JSON.", exc)

    # Fallback : export JSON des données via SQLAlchemy
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _export() -> dict:
        engine = create_async_engine(normalize_database_url(url))
        data: dict[str, list] = {}
        try:
            async with engine.connect() as conn:
                tables = (await conn.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                ))).scalars().all()
                for tbl in tables:
                    rows = (await conn.execute(text(f"SELECT * FROM {tbl}"))).mappings().all()
                    data[tbl] = [dict(r) for r in rows]
        finally:
            await engine.dispose()
        return data

    payload = asyncio.run(_export())
    json_out = dest / f"yiriba_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=str)
    logger.info("PostgreSQL export JSON : %s (%d tables)", json_out, len(payload))
    return json_out


def backup_uploads(upload_dir: Path, dest: Path) -> None:
    if not upload_dir.exists():
        logger.warning("Dossier uploads introuvable : %s", upload_dir)
        return
    out = dest / f"uploads_{dt.datetime.now():%Y%m%d_%H%M%S}"
    shutil.copytree(upload_dir, out, dirs_exist_ok=True)
    logger.info("Uploads copiés : %s -> %s", upload_dir, out)


def cleanup_old(dest: Path, keep: int) -> None:
    """Supprime les sauvegardes les plus anciennes en conservant `keep` récentes."""
    files = sorted(dest.glob("yiriba_*"), key=lambda p: p.stat().st_mtime)
    uploads = sorted(dest.glob("uploads_*"), key=lambda p: p.stat().st_mtime)
    for group, n in ((files, keep), (uploads, keep)):
        for old in group[:-n]:
            try:
                if old.is_dir():
                    shutil.rmtree(old)
                else:
                    old.unlink()
                logger.info("Ancienne sauvegarde supprimée : %s", old)
            except OSError as exc:
                logger.warning("Suppression impossible %s : %s", old, exc)


def main() -> int:
    ap = argparse.ArgumentParser(description="Sauvegarde Yiriba (base + uploads)")
    ap.add_argument("--dest", default="./backups", help="Dossier de destination des sauvegardes")
    ap.add_argument("--keep", type=int, default=7, help="Nombre de sauvegardes à conserver")
    ap.add_argument("--skip-uploads", action="store_true", help="Ne pas copier les uploads")
    args = ap.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    url = DATABASE_URL

    try:
        if url.startswith("sqlite"):
            backup_sqlite(url, dest)
        else:
            backup_postgres(url, dest)
    except Exception as exc:  # noqa: BLE001
        logger.error("Échec de la sauvegarde base : %s", exc)

    if not args.skip_uploads:
        backup_uploads(settings.upload_path, dest)

    cleanup_old(dest, args.keep)
    logger.info("Sauvegarde terminée dans %s", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
