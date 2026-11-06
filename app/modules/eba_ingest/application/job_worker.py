"""Backward-compatible adapter for the shared worker."""

from app.core.worker import JobHandlerRegistry, Worker
from app.modules.eba_ingest.application.worker_handler import register_handlers


class ImportWorker(Worker):
    def __init__(
        self,
        storage_dir: str,
        schema: str = "public",
        max_bytes: int = 100 * 1024 * 1024,
        poll_interval: float = 1.0,
        stale_after: int = 900,
    ):
        registry = JobHandlerRegistry()
        register_handlers(registry, storage_dir, schema, max_bytes)
        super().__init__(registry, poll_interval, stale_after, schema)
