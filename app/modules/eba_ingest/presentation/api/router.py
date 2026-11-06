"""HTTP methods of the ingest module. The router carries no application state: settings are bound when it is built."""
from __future__ import annotations

import os
import shutil
import tempfile

from fastapi import APIRouter, File, Form, UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.api import problem_responses
from app.core.config import get_max_upload_bytes, get_schema, get_storage_dir, get_user_id
from app.modules.eba_ingest.application.queries import drop_staging, get_import, list_imports
from app.modules.eba_ingest.application.upload_service import enqueue_import
from app.modules.eba_ingest.domain import FileTooLarge, UnreadableFile
from app.modules.eba_ingest.presentation.api.schemas import DroppedStaging, ImportDetail, ImportSummary, IngestConfig

TAG = "ingest"


def build_router(storage_dir: str | None = None, schema: str | None = None, max_bytes: int | None = None, user_id: int | None = None) -> APIRouter:
    storage_dir = storage_dir or get_storage_dir()
    schema = schema or get_schema()
    max_bytes = max_bytes or get_max_upload_bytes()
    user_id = user_id if user_id is not None else get_user_id()
    router = APIRouter(prefix="/api", tags=[TAG])

    @router.get("/config", response_model=IngestConfig, operation_id="get_ingest_config", summary="Upload limits")
    def config():
        """What the interface needs before offering an upload: the size limit and the accepted extensions."""
        return IngestConfig(max_upload_mb=round(max_bytes / 1024 / 1024, 3), accepted_extensions=[".csv", ".xlsx"])

    @router.post("/imports", status_code=201, response_model=ImportDetail, operation_id="create_import", summary="Upload the original files of one import",
                 responses=problem_responses(409, 413, 422))
    def create_import(files: list[UploadFile] = File(..., description="The original .csv or .xlsx files, exactly as downloaded"),
                      edition: str | None = Form(None, description="Optional label, e.g. 2020")):
        """Stores the files untouched (sha256, read-only), registers the import and queues the loading job.
        The answer is immediate: poll `GET /api/imports/{id}` until `job_status` is `completed` or `failed`."""
        tmp = tempfile.mkdtemp(prefix="eba_upload_")
        try:
            paths = []
            for i, uf in enumerate(files):
                name = os.path.basename((uf.filename or "").replace("\\", "/"))
                if not name:
                    raise UnreadableFile("a file arrived without a name")
                directory = os.path.join(tmp, str(i))
                os.makedirs(directory)
                dest = os.path.join(directory, name)
                written = 0
                with open(dest, "wb") as out:                       # copied in 1 MB chunks, never read whole into memory
                    for chunk in iter(lambda: uf.file.read(1 << 20), b""):
                        written += len(chunk)
                        if written > max_bytes:
                            raise FileTooLarge(f"{name} is larger than {max_bytes / 1024 / 1024:.0f} MB")
                        out.write(chunk)
                paths.append(dest)
            import_id = enqueue_import(paths, storage_dir, user_id=user_id, edition_label=edition or None, max_bytes=max_bytes, schema=schema)
            return get_import(import_id, schema)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @router.get("/imports", response_model=list[ImportSummary], operation_id="list_imports", summary="List imports, newest first")
    def imports():
        return list_imports(schema)

    @router.get("/imports/{import_id}", response_model=ImportDetail, operation_id="get_import", summary="Report and live state of one import", responses=problem_responses(404))
    def one(import_id: int):
        report = get_import(import_id, schema)
        if report is None:
            raise StarletteHTTPException(404, f"import {import_id} does not exist")
        return report

    @router.delete("/imports/{import_id}/staging", response_model=DroppedStaging, operation_id="drop_staging", summary="Drop the staging tables of an import",
                   responses=problem_responses(404))
    def drop(import_id: int):
        """The stored original files are never touched."""
        if get_import(import_id, schema) is None:
            raise StarletteHTTPException(404, f"import {import_id} does not exist")
        return {"dropped": drop_staging(import_id, schema)}

    return router
