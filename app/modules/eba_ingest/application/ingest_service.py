"""Public functions of the module (kept as one import point for the command line, the tests and other code)."""
from app.core.database import init_database
from app.modules.eba_ingest.application.queries import drop_staging, get_import, list_imports, show
from app.modules.eba_ingest.application.staging_service import ingest, process_import
from app.modules.eba_ingest.application.upload_service import DEFAULT_MAX_BYTES, enqueue_import


def init_db(schema: str = "public") -> None:
    """Creates or upgrades the application tables (core migrations) and the staging schema. The composition root
    (`python -m app init-db`) also applies the migrations of every module."""
    init_database(schema)


__all__ = ["DEFAULT_MAX_BYTES", "ingest", "init_db", "drop_staging", "show", "list_imports", "get_import", "enqueue_import", "process_import"]
