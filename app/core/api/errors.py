"""One place that renders every error as application/problem+json (RFC 9457); modules only raise AppError subclasses."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


def problem(status: int, kind: str, title: str, detail: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"type": kind, "title": title, "status": status, "detail": detail}, media_type="application/problem+json")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError):
        return problem(e.status, e.kind, e.title, e.detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, e: StarletteHTTPException):
        not_found = e.status_code == 404
        return problem(e.status_code, "not-found" if not_found else "http-error", "Not found" if not_found else "Request failed", str(e.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, e: RequestValidationError):
        detail = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        return problem(422, "invalid-request", "Invalid request", detail)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, e: Exception):
        logger.exception("unhandled error on %s %s", request.method, request.url.path)          # details stay in the log, not in the answer
        return problem(500, "internal-error", "Internal error", "The server could not complete the request; see the server log.")
