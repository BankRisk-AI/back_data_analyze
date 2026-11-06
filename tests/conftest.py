
import os
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import pytest

from dotenv import load_dotenv
from psycopg2 import sql
from urllib.parse import urlsplit, urlunsplit

from app.modules.eba_ingest import init_db


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

TEST_DATABASE = "eba_test"
SCHEMA = "ing_test"

HEADER = "LEI_Code,NSA,Period,Item,Label,Amount,footnote\n"


# ---------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------

@pytest.fixture(scope="session")
def database_url():
    """
    Creates an isolated PostgreSQL database for the test session.
    Removes it after all tests have finished.
    """

    if not DATABASE_URL:
        pytest.fail("DATABASE_URL is missing from .env")

    config = urlsplit(DATABASE_URL)

    if config.path.lstrip("/") == TEST_DATABASE:
        pytest.fail(
            "DATABASE_URL points to the test database. "
            "Tests must use a separate development database."
        )

    # Connect to PostgreSQL maintenance database.
    admin_database_url = urlunsplit(config._replace(path="/postgres"))

    try:
        admin_conn = psycopg2.connect(admin_database_url)
    except psycopg2.Error as exc:
        pytest.fail(f"Cannot connect to PostgreSQL: {exc}")

    admin_conn.autocommit = True

    try:
        with admin_conn.cursor() as cur:
            # Remove an old test database, if it exists.
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                """,
                (TEST_DATABASE,),
            )

            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(TEST_DATABASE)
                )
            )

            # Create a fresh test database.
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(TEST_DATABASE)
                )
            )

    except psycopg2.Error as exc:
        pytest.fail(
            "Could not create the test database. "
            "The PostgreSQL user needs CREATEDB permission. "
            f"Details: {exc}"
        )
    finally:
        admin_conn.close()

    test_database_url = urlunsplit(config._replace(path=f"/{TEST_DATABASE}"))

    try:
        # Create the application schema.
        conn = psycopg2.connect(test_database_url)
        conn.autocommit = True

        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE SCHEMA {}").format(
                    sql.Identifier(SCHEMA)
                )
            )

        conn.close()

        # Initialize application tables and staging schema.
        previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = test_database_url
        init_db(SCHEMA)

        yield test_database_url

    finally:
        # Drop the test database after the test session.
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        cleanup_conn = psycopg2.connect(admin_database_url)
        cleanup_conn.autocommit = True

        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s
                      AND pid <> pg_backend_pid()
                    """,
                    (TEST_DATABASE,),
                )

                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(
                        sql.Identifier(TEST_DATABASE)
                    )
                )
        finally:
            cleanup_conn.close()


# ---------------------------------------------------------
# Per-test database fixture
# ---------------------------------------------------------

@pytest.fixture()
def db(database_url, tmp_path):
    """
    Prepares clean application data and temporary storage
    for every individual test.
    """

    conn = psycopg2.connect(database_url)
    conn.autocommit = True

    cur = conn.cursor()

    cur.execute(
        sql.SQL("SET search_path TO {}, public").format(
            sql.Identifier(SCHEMA)
        )
    )

    cur.execute(
        """
        TRUNCATE
            audit_log,
            decision_log,
            job,
            source_file,
            import_batch,
            app_user
        RESTART IDENTITY CASCADE
        """
    )

    cur.execute(
        """
        INSERT INTO app_user(username, password_hash, role)
        VALUES ('admin', 'x', 'administrator')
        """
    )

    cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    cur.execute("CREATE SCHEMA staging")

    helper = SimpleNamespace(
        cur=cur,
        conn=conn,
        database_url=database_url,
        storage=str(tmp_path / "storage"),
        dir=tmp_path,
        schema=SCHEMA,
    )

    yield helper

    cur.close()
    conn.close()


# ---------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------

def write_csv(path, rows, encoding="cp1252", header=HEADER):
    with open(path, "w", encoding=encoding, newline="") as file:
        file.write(header)

        for row in rows:
            file.write(row + "\n")

    return str(path)
