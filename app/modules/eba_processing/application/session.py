"""One read-only database session with a statement timeout: a slow analytic query becomes a clear 504, never a hung request."""
from __future__ import annotations

import time
from contextlib import contextmanager

import psycopg2.errors

from app.core.database import connect
from app.core.exceptions import AppError
from app.modules.eba_processing.domain import QUERY_TIMEOUT_SECONDS


class QueryTooSlow(AppError):
    kind = "query-too-slow"
    status = 504
    title = "Query too slow"


@contextmanager
def read_session(schema: str):
    """Yields (cursor, timer). The transaction is always rolled back: nothing here writes."""
    conn = connect(schema)
    started = time.perf_counter()
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = %s", (f"{QUERY_TIMEOUT_SECONDS}s",))
        yield cur, lambda: round((time.perf_counter() - started) * 1000, 1)
    except psycopg2.errors.QueryCanceled as e:
        raise QueryTooSlow(f"the query took more than {QUERY_TIMEOUT_SECONDS} s; narrow it with period, item or dim filters") from e
    finally:
        conn.rollback()
        conn.close()
