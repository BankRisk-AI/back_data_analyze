"""Empty the application data while keeping the schema and migrations (audited).

    python -m scripts.data.reset_data --target test --confirm <database-name>

DESTRUCTIVE: truncates every table except schema_migrations, audit_log and app_user, and
recreates the staging schema. --confirm must equal the connected database name.
"""
from __future__ import annotations

import argparse

from scripts.common import select_target, target_summary


def _check_confirmation(confirm: str) -> None:
    """Abort unless --confirm equals the name of the database DATABASE_URL points to."""
    import psycopg2
    from app.core.config import get_database_url
    conn = psycopg2.connect(get_database_url())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            database = cur.fetchone()[0]
    finally:
        conn.close()
    if confirm != database:
        raise SystemExit(f"refusing reset: --confirm must equal {database!r}")


def _truncate_with_audit() -> dict[str, int]:
    """Audit the row counts, then truncate all application tables; return the counts before."""
    from psycopg2 import sql
    from psycopg2.extras import Json
    from app.core.config import get_schema, get_user_id
    from app.core.database import connect
    conn = connect(get_schema())
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT tablename FROM pg_tables
                           WHERE schemaname = current_schema()
                             AND tablename NOT IN ('schema_migrations', 'audit_log', 'app_user')""")
            tables = [row[0] for row in cur.fetchall()]
            before = {}
            for table in tables:
                cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
                before[table] = cur.fetchone()[0]
            cur.execute("INSERT INTO audit_log(user_id, action, entity, detail) VALUES (%s,%s,%s,%s)",
                        (get_user_id(), "data reset", "database", Json({"row_counts_before": before})))
            if tables:
                cur.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(t) for t in tables)))
        return before
    finally:
        conn.close()


def recreate_staging_schema() -> None:
    """Drop and recreate the staging schema."""
    from app.core.database import connect
    with connect("staging") as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
        cur.execute("CREATE SCHEMA staging")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Empty application data (destructive)")
    p.add_argument("--confirm", required=True, help="must equal the connected database name")
    p.add_argument("--target", choices=("test", "prod"), required=True)
    a = p.parse_args(argv)
    target, _ = select_target(a.target)
    _check_confirmation(a.confirm)
    before = _truncate_with_audit()
    recreate_staging_schema()
    print(target_summary(target, f"reset before_rows={sum(before.values())} after_rows=0"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
