"""Job handler of the processing module (kind 'validate_data')."""
from __future__ import annotations

from app.core.worker import Job, JobHandlerRegistry, ProgressReporter
from app.modules.eba_processing.application.validation import run_validation
from app.modules.eba_processing.domain import VALIDATION_JOB_KIND


def handle_validate_data(job: Job, progress: ProgressReporter, schema: str | None = None) -> None:
    run_validation(job.import_id, schema or job.schema, emit=progress)


def register_handlers(registry: JobHandlerRegistry, schema: str | None = None) -> None:
    registry.register(VALIDATION_JOB_KIND, lambda job, progress: handle_validate_data(job, progress, schema))
