"""Standalone application of the ingest module (the module can run alone) and the compatibility factory used by the tests."""
from __future__ import annotations

from fastapi import FastAPI

from app.core.api import create_base_app, mount_ui
from app.core.config import get_cors_origins, get_max_upload_bytes, get_schema, get_storage_dir, get_ui_dir, get_user_id
from app.modules.eba_ingest.presentation.api.router import build_router
from app.modules.eba_ingest.presentation.api.schemas import (  # noqa: F401  (re-exported for existing imports)
    FileModel as FileModel,
    ImportDetail as ImportDetail,
    ImportSummary as ImportSummary,
    PairModel as PairModel,
)


def create_app(storage_dir: str | None = None, schema: str | None = None, max_bytes: int | None = None, user_id: int | None = None, ui_dir: str | None = None) -> FastAPI:
    app = create_base_app("EBA Data Explorer: ingest", "Upload of the original EBA files and management of imports.", cors_origins=get_cors_origins())
    app.include_router(build_router(storage_dir or get_storage_dir(), schema or get_schema(), max_bytes or get_max_upload_bytes(), user_id))
    mount_ui(app, ui_dir)
    return app


def app_from_env() -> FastAPI:
    return create_app(get_storage_dir(), get_schema(), get_max_upload_bytes(), get_user_id(), get_ui_dir())
