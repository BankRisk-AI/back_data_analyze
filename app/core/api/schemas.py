"""Schemas shared by every module's API (so that the OpenAPI file describes errors once)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Problem(BaseModel):
    """Stable frontend error envelope, retaining RFC 9457 fields for compatibility."""

    code: str = Field(examples=["duplicate-file"])
    message: str = Field(examples=["File already loaded"])
    details: str | None = Field(default=None, examples=["tr_cre_2.csv was already loaded"])
    request_id: str = Field(examples=["f4e3a2b1c0d9"])
    type: str = Field(examples=["duplicate-file"])
    title: str = Field(examples=["File already loaded"])
    status: int = Field(examples=[409])
    detail: str | None = Field(default=None, examples=["tr_cre_2.csv was already loaded in import 1 (same sha256)"])


def problem_responses(*statuses: int) -> dict:
    """`responses=` argument for a route: documents the problem+json answer of each status."""
    names = {400: "Bad request", 404: "Not found", 409: "Conflict", 413: "Payload too large", 422: "Invalid request or parameter", 500: "Internal error"}
    return {s: {"model": Problem, "description": names.get(s, "Error"), "content": {"application/problem+json": {}}} for s in statuses}
