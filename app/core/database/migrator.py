"""Numbered SQL migrations. The core owns migrations/core; every module may own a folder of its own (ModuleSpec.migrations_dir)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.database.connection import connect

CORE_DIR = Path(__file__).with_name("migrations") / "core"
LOCK_KEY = 7_302_026            # advisory lock: two processes never migrate at the same time


@dataclass(frozen=True)
class Migration:
    owner: str
    name: str
    path: Path

    @property
    def version(self) -> str:
        return f"{self.owner}/{self.name}"


def discover(modules: dict[str, Path] | None = None) -> list[Migration]:
    found = [Migration("core", p.stem, p) for p in sorted(CORE_DIR.glob("*.sql"))]
    for owner, directory in sorted((modules or {}).items()):
        found += [Migration(owner, p.stem, p) for p in sorted(Path(directory).glob("*.sql"))]
    return found


def migrate(schema: str = "public", modules: dict[str, Path] | None = None) -> list[str]:
    """Applies the pending migrations (each in its own transaction step) and returns their versions."""
    conn = connect(schema)
    applied_now: list[str] = []
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
            cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            cur.execute("SELECT version FROM schema_migrations")
            done = {r[0] for r in cur.fetchall()}
            if not done:                                                            # a database created before migrations existed
                cur.execute("SELECT to_regclass('import_batch') IS NOT NULL")
                if cur.fetchone()[0]:
                    cur.execute("INSERT INTO schema_migrations(version) VALUES ('core/001_baseline')"); done.add("core/001_baseline")
            for m in discover(modules):
                if m.version in done:
                    continue
                cur.execute(m.path.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (m.version,))
                applied_now.append(m.version)
    finally:
        conn.close()
    return applied_now
