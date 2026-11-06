from pathlib import Path

from app.core.module import ModuleSpec
from app.modules.eba_ingest.application.worker_handler import register_handlers
from app.modules.eba_ingest.presentation.api.router import TAG, build_router

SPEC = ModuleSpec(
    name="eba_ingest",
    description="Receives the original EBA files, stores them untouched and loads them into staging tables.",
    router_factory=build_router,
    register_handlers=register_handlers,
    migrations_dir=None,
    tags=[{"name": TAG, "description": "Upload of the original files, import list and report, staging tables."}],
)
