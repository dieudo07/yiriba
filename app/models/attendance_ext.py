"""Yiriba SaaS — Migration runtime SQLite pour les colonnes Attendance ajoutées.

(justification_status, validated, validated_by, validated_at, comment)
Sur PostgreSQL, utiliser Alembic.
"""
import os
import sqlite3

from app.core.database import engine


def add_missing_columns() -> None:
    """ALTER TABLE ADD COLUMN idempotent (SQLite dev)."""
    url = str(engine.url)
    if not url.startswith("sqlite"):
        return  # migration gérée par Alembic sur PostgreSQL
    path = url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "") or "yiriba.db"
    path = os.path.abspath(path)
    conn = sqlite3.connect(path)
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(attendances)")}
        stmts = {
            "justification_status": "ALTER TABLE attendances ADD COLUMN justification_status VARCHAR(20) NOT NULL DEFAULT 'none'",
            "validated": "ALTER TABLE attendances ADD COLUMN validated BOOLEAN NOT NULL DEFAULT 0",
            "validated_by": "ALTER TABLE attendances ADD COLUMN validated_by INTEGER",
            "validated_at": "ALTER TABLE attendances ADD COLUMN validated_at DATETIME",
            "comment": "ALTER TABLE attendances ADD COLUMN comment TEXT",
        }
        for col, ddl in stmts.items():
            if col not in existing:
                conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()


add_missing_columns()
