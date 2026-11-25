"""Root conftest: only what every test category shares. No database fixtures live here.

Safety rules for the whole session:
- DATABASE_URL is replaced by an unreachable sentinel before any application module is imported
  (the application loads .env without overriding existing variables), so a unit or integration test can
  never reach the production database, whatever the environment or .env contains.
- While a test outside tests/data_processing runs, psycopg2.connect is replaced by a function that fails
  the test: a unit/integration test that touches PostgreSQL is a CI failure, not a silent skip.
- The test database is only used by tests/data_processing (see its conftest.py).
"""
import os

import psycopg2
import pytest

UNREACHABLE_DATABASE_URL = "postgresql://invalid-host/no-test-database"
os.environ["DATABASE_URL"] = UNREACHABLE_DATABASE_URL


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: performance-sensitive tests")
    config.addinivalue_line("markers", "thesis: regression on the stored thesis run data/ml/T3_primary")
    config.addinivalue_line("markers", "data_processing: local-only tests (real EBA files, test database)")


@pytest.fixture(autouse=True)
def _no_database_outside_data_processing(request, monkeypatch):
    """Fail any attempt to open a PostgreSQL connection from a unit or integration test."""
    if "data_processing" in request.node.path.parts:
        return

    def refuse(*args, **kwargs):
        raise AssertionError("database access in a unit/integration test: move it to tests/data_processing/database/")

    monkeypatch.setattr(psycopg2, "connect", refuse)
