"""Initialisation of the application database (compatibility entry point; the work is done by the migrator)."""
from __future__ import annotations

from pathlib import Path

from app.core.database.connection import connect
from app.core.database.migrator import migrate


def initialize_schema(schema: str = "public", modules: dict[str, Path] | None = None) -> list[str]:
    """Creates or upgrades the application tables; returns the migrations applied now."""
    return migrate(schema, modules)


def init_database(schema: str = "public", modules: dict[str, Path] | None = None) -> list[str]:
    """Migrations plus the staging schema where the loaded files live."""
    from app.shared.staging import STAGING_SCHEMA

    applied = migrate(schema, modules)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{STAGING_SCHEMA}"')
    finally:
        conn.close()
    return applied
