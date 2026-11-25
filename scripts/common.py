"""Helpers shared by the terminal scripts: database target selection and import-job plumbing."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

EDITIONS = ("2015", "2016", "2017", "2018", "2019", "2020S", "2020A",
            "2021", "2022", "2023", "2024", "2025")


def select_target(target: str) -> tuple[str, str]:
    """Point DATABASE_URL at the test or prod database; abort when it is not configured."""
    from app.core.config import get_database_url
    if target == "test":
        url = os.getenv("TEST_DATABASE_URL")
        os.environ["EBA_STORAGE"] = os.getenv("EBA_TEST_STORAGE", "storage_test")
    else:
        url = get_database_url()
    if not url:
        raise SystemExit(f"{target}: database URL is not configured")
    os.environ["DATABASE_URL"] = url
    return target, url


def target_summary(target: str, outcome: str) -> str:
    """One line naming the database, server and schema the command ran against."""
    import psycopg2
    from psycopg2 import sql
    from app.core.config import get_schema
    url = os.environ["DATABASE_URL"]
    parsed = urlparse(url)
    conn = psycopg2.connect(url)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(get_schema())))
            cur.execute("SELECT current_database(), current_setting('server_version'), "
                        "current_setting('search_path')")
            database, _, search_path = cur.fetchone()
    finally:
        conn.close()
    return (f"target={target} database={database} server={parsed.hostname or 'localhost'}:"
            f"{parsed.port or 5432} search_path={search_path} schema={get_schema()} outcome={outcome}")


def init_all_modules() -> None:
    """Create or upgrade the tables of the core and of every module (migrations)."""
    from app.core.config import get_schema
    from app.core.database import init_database
    from app.modules import MODULES
    init_database(get_schema(), {m.name: m.migrations_dir for m in MODULES if m.migrations_dir})


def edition_files(directory: Path) -> list[str]:
    """Sorted data files of an edition directory (README excluded)."""
    return sorted(str(p) for p in directory.iterdir()
                  if p.is_file() and p.name.lower() != "readme.md")


def make_import_worker():
    """In-process worker with the ingest and validation handlers registered."""
    from app.core.config import get_schema, get_storage_dir
    from app.core.worker import JobHandlerRegistry
    from app.modules.eba_ingest.application.job_worker import ImportWorker
    from app.modules.eba_ingest.application.worker_handler import register_handlers
    from app.modules.eba_processing.application.worker_handler import (
        register_handlers as register_validation_handlers)
    registry = JobHandlerRegistry()
    register_handlers(registry, get_storage_dir(), get_schema())
    register_validation_handlers(registry, get_schema())
    worker = ImportWorker(get_storage_dir(), schema=get_schema())
    worker.registry = registry
    return worker


def stage_job_id(import_id: int) -> int:
    """Newest staging job of an import."""
    from app.core.config import get_schema
    from app.core.database import connect
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute("SELECT job_id FROM job WHERE import_id=%s AND kind='stage' "
                    "ORDER BY job_id DESC LIMIT 1", (import_id,))
        return cur.fetchone()[0]


def job_status(job_id: int) -> tuple[str, str | None]:
    """(status, error) of a job."""
    from app.core.config import get_schema
    from app.core.database import connect
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute("SELECT status, error FROM job WHERE job_id=%s", (job_id,))
        return cur.fetchone()


def run_job(worker, job_id: int) -> None:
    """Process the next job in-process; raise RuntimeError unless the job completed."""
    if not worker.process_one():
        raise RuntimeError("job was not available")
    status, error = job_status(job_id)
    if status != "completed":
        raise RuntimeError(error or status)
