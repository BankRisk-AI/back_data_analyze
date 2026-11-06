"""One place that renders every error as application/problem+json (RFC 9457); modules only raise AppError subclasses."""
from __future__ import annotations

from app.core.logging import get_logger

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError

logger = get_logger(__name__)


def problem(status: int, kind: str, title: str, detail: str | None = None, request_id: str = "") -> JSONResponse:
    response = JSONResponse(
        status_code=status,
        content={
            "code": kind,
            "message": title,
            "details": detail,
            "request_id": request_id,
            "type": kind,
            "title": title,
            "status": status,
            "detail": detail,
        },
        media_type="application/problem+json",
    )
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, e: AppError):
        logger.warning("%s: %s", e.kind, e.detail or e.title)
        return problem(e.status, e.kind, e.title, e.detail, getattr(request.state, "request_id", ""))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, e: StarletteHTTPException):
        not_found = e.status_code == 404
        kind = "not-found" if not_found else "http-error"
        title = "Not found" if not_found else "Request failed"
        logger.warning("%s: %s", kind, e.detail)
        return problem(e.status_code, kind, title, str(e.detail), getattr(request.state, "request_id", ""))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, e: RequestValidationError):
        detail = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        logger.warning("invalid request: %s", detail)
        return problem(422, "invalid-request", "Invalid request", detail, getattr(request.state, "request_id", ""))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, e: Exception):
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return problem(500, "internal-error", "Internal error", "The server could not complete the request; see the server log.",
                       getattr(request.state, "request_id", ""))
