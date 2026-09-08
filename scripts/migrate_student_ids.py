"""Migration : identifiants élèves uniques globalement (préfixe école).

- Attribue un sigle unique (School.short_name) à chaque école qui n'en a pas
- Réécrit les identifiants élèves YRB-XXXXXX en SIGLE-XXXXXX
- Les identifiants admin YIRIBA-XXXXXX sont globaux par construction : inchangés

Usage : .venv/Scripts/python.exe scripts/migrate_student_ids.py [--dry-run]
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TURNSTILE_SECRET_KEY", "")

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session_factory  # noqa: E402
from app.models.school import School  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.student_service import ensure_school_prefix  # noqa: E402


async def main(dry_run: bool) -> None:
    async with async_session_factory() as db:
        schools = (await db.execute(select(School))).scalars().all()
        print(f"{len(schools)} école(s)")

        # 1) Sigle unique pour chaque école
        prefixes = {}
        for school in schools:
            prefix = await ensure_school_prefix(db, school)
            prefixes[school.id] = prefix
            print(f"  école {school.id} « {school.name} » → sigle {prefix}")

        # 2) Réécrire les identifiants YRB-XXXXXX → SIGLE-XXXXXX
        renamed = 0
        for school in schools:
            prefix = prefixes[school.id]
            users = (await db.execute(
                select(User).where(
                    User.school_id == school.id,
                    User.username.like("YRB-%"),
                )
            )).scalars().all()
            for u in users:
                number = u.username.split("-", 1)[1]
                new_id = f"{prefix}-{number}"
                # unicité globale (au cas où un SIGLE- du même numéro existe déjà)
                n = 0
                base = new_id
                while (await db.execute(
                    select(User.id).where(User.username == new_id, User.id != u.id)
                )).scalar_one_or_none() is not None:
                    n += 1
                    new_id = f"{base}{n}"  # ex: CYA-0000012 (le compteur reste lisible)
                if new_id != u.username:
                    print(f"  {u.username} → {new_id}")
                    if not dry_run:
                        u.username = new_id
                    renamed += 1

        if dry_run:
            print(f"\n[DRY-RUN] {renamed} identifiant(s) serait(s) renommé(s). Relancez sans --dry-run pour appliquer.")
            await db.rollback()
        else:
            await db.commit()
            print(f"\nOK — {renamed} identifiant(s) élève(s) migré(s).")


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
