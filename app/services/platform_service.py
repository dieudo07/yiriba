"""Yiriba SaaS — Services niveau plateforme (Super Admin).

- get_setting / set_setting : paramètres globaux (table platform_settings)
- is_maintenance : mode maintenance global de la plateforme
- ensure_school_not_frozen : levée 423 si l'école est gelée (Super Admin)
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import PlatformSetting

MAINTENANCE_KEY = "maintenance_mode"
DEFAULT_SETTINGS = {
    "maintenance_mode": "false",
    "platform_name": "YIRIBA",
    "contact_email": "contact@yiriba.com",
}


async def get_setting(db: AsyncSession, key: str, default: str | None = None) -> str | None:
    row = (await db.execute(
        PlatformSetting.__table__.select().where(PlatformSetting.key == key)
    )).first()
    return row.value if row else default


async def set_setting(
    db: AsyncSession, key: str, value: str | None, updated_by: int | None = None
) -> None:
    row = (await db.execute(
        PlatformSetting.__table__.select().where(PlatformSetting.key == key)
    )).first()
    if row:
        await db.execute(
            PlatformSetting.__table__.update()
            .where(PlatformSetting.key == key)
            .values(value=value, updated_by=updated_by)
        )
    else:
        await db.execute(
            PlatformSetting.__table__.insert().values(
                key=key, value=value, updated_by=updated_by
            )
        )


async def is_maintenance(db: AsyncSession) -> bool:
    """True si le mode maintenance global est activé."""
    val = await get_setting(db, MAINTENANCE_KEY, "false")
    return (val or "false").lower() == "true"


async def get_all_settings(db: AsyncSession) -> dict[str, str | None]:
    rows = (await db.execute(
        PlatformSetting.__table__.select().order_by(PlatformSetting.key)
    )).all()
    out = dict(DEFAULT_SETTINGS)
    for row in rows:
        out[row.key] = row.value
    return out
