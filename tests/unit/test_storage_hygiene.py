import re
from pathlib import Path

import pytest


def test_repository_test_storage_is_not_prepared_storage():
    root = Path(__file__).resolve().parents[2]
    prepared_storage = (root / "eba_prepared" / "storage").resolve()
    assert not prepared_storage.exists()


def test_fixture_storage_is_outside_prepared_data(tmp_path):
    root = Path(__file__).resolve().parents[2]
    assert (root / "eba_prepared").resolve() not in tmp_path.resolve().parents


_DATABASE_URL_DIRECT_READ = re.compile(
    r'os\.environ\s*\[\s*["\']DATABASE_URL["\']'
    r'|os\.environ\.get\s*\(\s*["\']DATABASE_URL["\']'
    r'|os\.getenv\s*\(\s*["\']DATABASE_URL["\']',
)


def test_no_test_module_reads_database_url_directly():
    """No test file (non-conftest) may read DATABASE_URL from the environment.

    All DB access in tests must go through the fixture infrastructure or
    TEST_DATABASE_URL explicitly. DATABASE_URL is redirected to the test DB
    by the data_processing fixtures and is an unreachable sentinel elsewhere; direct reads are a signal that
    a test might bypass that redirect or accidentally reach prod.
    """
    tests_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted(tests_root.rglob("*.py")):
        if path.name == "conftest.py":
            continue
        text = path.read_text(encoding="utf-8")
        if _DATABASE_URL_DIRECT_READ.search(text):
            offenders.append(str(path.relative_to(tests_root)))
    assert not offenders, (
        "These test files read DATABASE_URL directly — use TEST_DATABASE_URL "
        "or the db fixture instead:\n  " + "\n  ".join(offenders)
    )


def test_unit_and_integration_tests_can_never_reach_a_database():
    """DATABASE_URL is an unreachable sentinel in every session and psycopg2.connect fails the test."""
    from urllib.parse import urlparse
    import psycopg2
    from app.core.config import get_database_url
    assert urlparse(get_database_url()).hostname == "invalid-host"
    with pytest.raises(AssertionError, match="database access in a unit/integration test"):
        psycopg2.connect("postgresql://invalid-host/x")


def test_database_fixtures_exist_only_under_data_processing():
    """Unit and integration folders neither use database fixtures nor psycopg2."""
    tests_root = Path(__file__).resolve().parents[1]
    forbidden = re.compile(r"\bdatabase_url\b|import psycopg2|from psycopg2|def test_\w+\([^)]*\bdb\b")
    offenders = [str(p.relative_to(tests_root)) for folder in ("unit", "integration")
                 for p in (tests_root / folder).rglob("test_*.py")
                 if p.name != "test_storage_hygiene.py" and forbidden.search(p.read_text(encoding="utf-8"))]
    assert not offenders, offenders
