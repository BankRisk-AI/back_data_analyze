"""Read-only database session with a statement timeout (shared by the analysis and alert APIs)."""
from __future__ import annotations

from contextlib import contextmanager

import psycopg2.errors

from app.core.database import connect
from app.core.exceptions import AppError

QUERY_TIMEOUT_SECONDS = 10   # statement timeout of read queries


class QueryTooSlow(AppError):
    kind = "query-too-slow"
    status = 504
    title = "Query too slow"


@contextmanager
def read_session(schema: str):
    """Yield (connection, cursor); the transaction is always rolled back, nothing here writes."""
    conn = connect(schema)
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = %s", (f"{QUERY_TIMEOUT_SECONDS}s",))
        yield conn, cur
    except psycopg2.errors.QueryCanceled as exc:
        raise QueryTooSlow(f"the query took more than {QUERY_TIMEOUT_SECONDS} seconds") from exc
    finally:
        conn.rollback()
        conn.close()
