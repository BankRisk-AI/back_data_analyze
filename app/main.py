"""Composition root of the HTTP application: one FastAPI app with the router of every module. Each module can also run alone
(python -m app.modules.<module> serve, or its presentation/api/api.py:create_app)."""
from __future__ import annotations

from fastapi import FastAPI

from app.core.api import create_base_app, mount_ui
from app.core.api.system import build_system_router, call_with_options
from app.core.config import get_cors_origins, get_max_upload_bytes, get_schema, get_storage_dir, get_ui_dir, get_user_id
from app.core.module import ModuleSpec
from app.core.worker import JobHandlerRegistry
from app.core.logging import get_logger

logger = get_logger(__name__)

VERSION = "0.2"
DESCRIPTION = (
    "EBA Data Explorer API. Modules: **ingest** (upload and staging), **processing** (staging analysis and validation), "
    "**public-analysis** (analysis and chart data for promoted facts). "
    "Errors are `application/problem+json` (RFC 9457); long operations are jobs processed by `python -m app.worker`."
)


def create_app(modules: list[ModuleSpec] | None = None, schema: str | None = None, storage_dir: str | None = None, max_bytes: int | None = None,
               user_id: int | None = None, ui_dir: str | None = None) -> FastAPI:
    from app.modules import MODULES

    modules = MODULES if modules is None else modules
    schema = schema or get_schema()
    options = {"schema": schema, "storage_dir": storage_dir or get_storage_dir(), "max_bytes": max_bytes or get_max_upload_bytes(),
               "user_id": user_id if user_id is not None else get_user_id()}
    app = create_base_app("EBA Data Explorer", DESCRIPTION, VERSION, cors_origins=get_cors_origins())
    def log_database() -> None:
        from app.core.database import connect
        conn = connect(schema)
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                logger.info("API started database=%s schema=%s", cur.fetchone()[0], schema)
        finally:
            conn.close()
    app.router.add_event_handler("startup", log_database)
    app.openapi_tags = [{"name": "system", "description": "Health, enumerations and the state of any job."}] + [t for m in modules for t in m.tags]
    registry = JobHandlerRegistry()
    from app.core.rules import register_handler as register_rules_handler
    register_rules_handler(registry, schema)
    for module in modules:
        if module.register_handlers:
            module.register_handlers(registry)
    job_kinds = sorted(registry.kinds())
    app.include_router(build_system_router(schema, VERSION, [m.name for m in modules], job_kinds))
    for spec in modules:
        if spec.router_factory:
            app.include_router(call_with_options(spec.router_factory, options))
    mount_ui(app, ui_dir if ui_dir is not None else get_ui_dir())
    return app


def app_from_env() -> FastAPI:
    return create_app()
