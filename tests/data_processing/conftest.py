"""Local-only tests: real EBA files (real_files/) and the PostgreSQL test database (database/).

Database rules (the only place where a database is touched):
- TEST_DATABASE_URL (environment or .env) is required; without it every test that needs the database is
  skipped. DATABASE_URL is never used and never read here.
- Before anything is modified, the database name must be exactly `eba_test`; otherwise the session aborts.
- During a test the application's DATABASE_URL points at the test database; it is restored afterwards.
"""
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import psycopg2
import pytest
from dotenv import dotenv_values
from psycopg2 import sql

from app.core.database import init_database

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL") or dotenv_values(PROJECT_ROOT / ".env").get("TEST_DATABASE_URL")
REQUIRED_DATABASE = "eba_test"
NO_DB_REASON = "no test database (TEST_DATABASE_URL not set)"
SCHEMA = "public"


def pytest_collection_modifyitems(items):
    """Every test below this folder carries the data_processing marker."""
    for item in items:
        if "data_processing" in item.path.parts:
            item.add_marker(pytest.mark.data_processing)


def _abort(message: str) -> None:
    pytest.exit(f"SAFETY ABORT: {message}", returncode=2)


def _verify_test_database(url: str) -> None:
    """Abort unless the URL names, and the server confirms, the database `eba_test`."""
    named = urlparse(url).path.lstrip("/")
    if named != REQUIRED_DATABASE:
        _abort(f"TEST_DATABASE_URL names database '{named}', not '{REQUIRED_DATABASE}'.")
    try:
        conn = psycopg2.connect(url)
    except Exception as exc:
        _abort(f"cannot connect to TEST_DATABASE_URL: {exc}")
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            actual = cur.fetchone()[0]
    finally:
        conn.close()
    if actual != REQUIRED_DATABASE:
        _abort(f"TEST_DATABASE_URL resolves to '{actual}', not '{REQUIRED_DATABASE}'.")


@pytest.fixture(scope="session")
def database_url():
    """The verified test database, reset once per session (schemas recreated, migrations applied)."""
    if not TEST_DATABASE_URL:
        pytest.skip(NO_DB_REASON)
    _verify_test_database(TEST_DATABASE_URL)          # nothing is modified before this passes
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
            cur.execute("CREATE SCHEMA public")
            cur.execute("CREATE SCHEMA staging")
    finally:
        conn.close()
    with _application_database(TEST_DATABASE_URL):
        init_database(SCHEMA)
    yield TEST_DATABASE_URL


@contextmanager
def _application_database(url: str):
    """Point the application's DATABASE_URL at the test database only while it is needed, then restore it."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture()
def db(database_url, tmp_path):
    """Clean application data and temporary storage for one test (cursor, connection, paths)."""
    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(SCHEMA)))
    cur.execute("""TRUNCATE audit_log, decision_log, job, source_file, import_batch, app_user RESTART IDENTITY CASCADE""")
    cur.execute("INSERT INTO app_user(username, password_hash, role) VALUES ('admin', 'x', 'administrator')")
    cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    cur.execute("CREATE SCHEMA staging")
    helper = SimpleNamespace(cur=cur, conn=conn, database_url=database_url, storage=str(tmp_path / "storage"),
                             dir=tmp_path, schema=SCHEMA)
    with _application_database(database_url):
        yield helper
    cur.close()
    conn.close()
