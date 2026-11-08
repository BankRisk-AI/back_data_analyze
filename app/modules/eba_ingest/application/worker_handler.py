"""Job handlers owned by the EBA ingest module."""
from __future__ import annotations

from app.core.config import get_schema
from app.core.database import connect
from app.core.worker import Job, JobHandlerRegistry, ProgressReporter
from app.modules.eba_ingest.application.staging_service import process_import
from app.modules.eba_ingest.domain import IngestError
from app.modules.eba_ingest.infrastructure.database import repositories as repo
from app.modules.eba_ingest.application.load_service import run_load


def handle_validate(job: Job, progress: ProgressReporter, schema: str | None = None) -> None:
    """Reads the files registered for the import and loads them into staging tables, reporting real progress."""
    schema = schema or job.schema or get_schema()
    try:
        process_import(job.import_id, schema, emit=progress, job_id=job.job_id)
    except IngestError:
        _mark_import(job.import_id, schema, "rejected")          # the user's files are the problem
        raise
    except Exception:
        _mark_import(job.import_id, schema, "failed")            # something unexpected: see the job error and the log
        raise


def _mark_import(import_id: int, schema: str, status: str) -> None:
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            repo.set_import_status(cur, import_id, status)
    finally:
        conn.close()


def register_handlers(registry: JobHandlerRegistry, storage_dir: str | None = None, schema: str | None = None, max_bytes: int | None = None) -> None:
    """storage_dir and max_bytes are accepted for compatibility: the worker no longer stores files, the API does."""
    registry.register("validate", lambda job, progress: handle_validate(job, progress, schema))
    registry.register("load", lambda job, progress: run_load(job.import_id, schema or job.schema, progress))
