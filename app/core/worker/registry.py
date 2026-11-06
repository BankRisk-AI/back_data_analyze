"""Registry for application job handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


ProgressReporter = Callable[[str, int], None]
JobHandler = Callable[["Job", ProgressReporter], None]


@dataclass(frozen=True)
class Job:
    job_id: int
    import_id: int
    kind: str
    schema: str = "public"            # the schema the worker runs on: handlers use it, so there is one source of truth


class JobHandlerRegistry:
    """Maps database job kinds to module-owned handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, kind: str, handler: JobHandler) -> None:
        if not kind:
            raise ValueError("job kind cannot be empty")
        if kind in self._handlers:
            raise ValueError(f"job handler already registered: {kind}")
        self._handlers[kind] = handler

    def resolve(self, kind: str) -> JobHandler:
        try:
            return self._handlers[kind]
        except KeyError as exc:
            raise LookupError(f"no job handler registered for: {kind}") from exc

    def __contains__(self, kind: str) -> bool:
        return kind in self._handlers
