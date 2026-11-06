"""Shared construction of FastAPI applications: error handlers, request id, optional CORS, optional built interface."""
from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .errors import install_error_handlers


class SpaStaticFiles(StaticFiles):
    """Serves the built interface; unknown paths fall back to index.html so client-side routes survive a reload."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404 and not path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}


def describe_errors_as_problem_json(schema: dict) -> dict:
    """FastAPI documents its own 422 as application/json (HTTPValidationError) and our declared errors with both content types,
    but every error of this API is application/problem+json with the `Problem` schema: make the description say so."""
    from app.core.api.schemas import Problem

    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.setdefault("Problem", Problem.model_json_schema())
    for methods in schema.get("paths", {}).values():
        for op in methods.values():
            if not isinstance(op, dict):
                continue
            for status, response in op.get("responses", {}).items():
                if status.isdigit() and int(status) >= 400:
                    response["content"] = {"application/problem+json": {"schema": PROBLEM_REF}}
                    if status == "422" and "description" in response and response["description"] == "Validation Error":
                        response["description"] = "Invalid request or parameter"
    text = str(schema.get("paths", {}))
    for unused in ("HTTPValidationError", "ValidationError"):
        if f"#/components/schemas/{unused}" not in text:
            components.pop(unused, None)
    return schema


def create_base_app(title: str, description: str, version: str = "0.1", cors_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title=title, description=description, version=version)
    install_error_handlers(app)
    original_openapi = app.openapi

    def openapi():
        if app.openapi_schema is None:
            describe_errors_as_problem_json(original_openapi())
        return app.openapi_schema

    app.openapi = openapi

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])
    return app


def mount_ui(app: FastAPI, ui_dir: str | None) -> None:
    """Must be called after every router is included (the static mount answers '/' and would hide later routes)."""
    if ui_dir and os.path.isdir(ui_dir):
        app.mount("/", SpaStaticFiles(directory=ui_dir, html=True), name="ui")
