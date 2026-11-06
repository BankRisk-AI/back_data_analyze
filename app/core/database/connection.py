
"""PostgreSQL connection management."""

import psycopg2
from psycopg2 import sql

from app.core.config import get_database_url


def connect(schema: str = "public"):
    """Create a PostgreSQL connection."""

    conn = psycopg2.connect(get_database_url())
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(schema)
                )
            )

        return conn

    except Exception:
        conn.rollback()
        conn.close()
        raise
