"""Endpoints about the application itself, shared by every module: health, enumerations for the client, and the state of any job."""
from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.api.schemas import problem_responses
from app.core.database import connect
from app.core.exceptions import AppError


class QueueState(BaseModel):
    pending: int
    processing: int
    failed_last_24h: int
    oldest_pending_seconds: float | None = Field(default=None, description="Age of the oldest job still waiting")


class Health(BaseModel):
    status: str = Field(description="ok, or degraded when the database or the worker looks wrong", examples=["ok"])
    version: str
    database: bool
    modules: list[str]
    queue: QueueState | None = None
    worker_hint: str | None = Field(default=None, description="Set when jobs wait and nothing is processing them: the worker process is probably not running")


class ProblemType(BaseModel):
    type: str
    status: int
    title: str


class Meta(BaseModel):
    import_statuses: list[str]
    job_statuses: list[str]
    job_kinds: list[str]
    file_types: list[str]
    problem_types: list[ProblemType] = Field(description="Every error `type` the API can return, with its HTTP status: lets the client map errors to messages")


class JobInfo(BaseModel):
    job_id: int
    import_id: int
    kind: str
    status: str
    progress: int
    message: str | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


IMPORT_STATUSES = ["uploaded", "validating", "validated", "approved", "loading", "loaded", "rejected", "cancelled", "failed"]
JOB_STATUSES = ["pending", "processing", "completed", "failed"]
FILE_TYPES = ["tr_oth", "tr_cre", "tr_mrk", "tr_sov", "SDD", "TR_Metadata", "unrecognised"]


def _all_subclasses(cls) -> list[type]:
    out = []
    for c in cls.__subclasses__():
        out.append(c)
        out += _all_subclasses(c)
    return out


def problem_catalogue() -> list[dict[str, Any]]:
    """Types of problem+json the application can answer, collected from the AppError classes of every loaded module."""
    seen: dict[str, dict] = {}
    for c in [AppError, *_all_subclasses(AppError)]:
        seen[c.kind] = {"type": c.kind, "status": c.status, "title": c.title}
    extra = [("invalid-request", 422, "Invalid request"), ("internal-error", 500, "Internal error"), ("http-error", 400, "Request failed")]
    for kind, status, title in extra:
        seen.setdefault(kind, {"type": kind, "status": status, "title": title})
    return sorted(seen.values(), key=lambda d: d["type"])


def build_system_router(schema: str, version: str, module_names: list[str], job_kinds: list[str]) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["system"])

    @router.get("/health", response_model=Health, operation_id="get_health", summary="Is the application usable?")
    def health():
        """Database reachability and queue state. `worker_hint` tells the interface to warn the user that the worker process is not running."""
        try:
            conn = connect(schema)
        except Exception:
            return Health(status="degraded", version=version, database=False, modules=module_names)
        try:
            with conn, conn.cursor() as cur:
                cur.execute("""SELECT count(*) FILTER (WHERE status = 'pending'), count(*) FILTER (WHERE status = 'processing'),
                                      count(*) FILTER (WHERE status = 'failed' AND finished_at > now() - interval '24 hours'),
                                      extract(epoch FROM now() - min(created_at) FILTER (WHERE status = 'pending'))
                               FROM job""")
                pending, processing, failed, oldest = cur.fetchone()
        finally:
            conn.close()
        hint = "jobs are waiting and none is running: start the worker (python -m app.worker)" if pending and not processing and oldest and oldest > 30 else None
        return Health(status="degraded" if hint else "ok", version=version, database=True, modules=module_names,
                      queue=QueueState(pending=pending, processing=processing, failed_last_24h=failed, oldest_pending_seconds=round(oldest, 1) if oldest is not None else None), worker_hint=hint)

    @router.get("/meta", response_model=Meta, operation_id="get_meta", summary="Enumerations and error types for the client")
    def meta():
        return Meta(import_statuses=IMPORT_STATUSES, job_statuses=JOB_STATUSES, job_kinds=sorted(job_kinds), file_types=FILE_TYPES,
                    problem_types=[ProblemType(**p) for p in problem_catalogue()])

    def _job(row) -> JobInfo:
        return JobInfo(job_id=row[0], import_id=row[1], kind=row[2], status=row[3], progress=row[4] or 0, message=row[5], error=row[6],
                       created_at=row[7].isoformat(), started_at=row[8].isoformat() if row[8] else None, finished_at=row[9].isoformat() if row[9] else None)

    cols = "job_id, import_id, kind, status, progress, message, error, created_at, started_at, finished_at"

    @router.get("/jobs/{job_id}", response_model=JobInfo, operation_id="get_job", summary="State of any job", responses=problem_responses(404))
    def get_job(job_id: int):
        """Generic polling endpoint: works for every job kind of every module."""
        conn = connect(schema)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(f"SELECT {cols} FROM job WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            raise StarletteHTTPException(404, f"job {job_id} does not exist")
        return _job(row)

    @router.get("/imports/{import_id}/jobs", response_model=list[JobInfo], operation_id="list_import_jobs", summary="Every job of an import, newest first")
    def import_jobs(import_id: int):
        conn = connect(schema)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(f"SELECT {cols} FROM job WHERE import_id = %s ORDER BY job_id DESC", (import_id,))
                rows = cur.fetchall()
        finally:
            conn.close()
        return [_job(r) for r in rows]

    return router


def call_with_options(factory, options: dict):
    """Calls a router factory with the options it accepts (each module declares only what it needs)."""
    accepted = inspect.signature(factory).parameters
    return factory(**{k: v for k, v in options.items() if k in accepted})
