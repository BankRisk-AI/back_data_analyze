"""Registry for application job handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


ProgressReporter = Callable[[str, int], None]
JobHandler = Callable[["Job", ProgressReporter], None]
GiveUpHandler = Callable[["Job"], None]


@dataclass(frozen=True)
class Job:
    job_id: int
    import_id: int
    kind: str
    attempts: int = 0
    schema: str = "public"            # the schema the worker runs on: handlers use it, so there is one source of truth


class JobHandlerRegistry:
    """Maps database job kinds to module-owned handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self._give_up: dict[str, GiveUpHandler | None] = {}

    def register(self, kind: str, handler: JobHandler, on_give_up: GiveUpHandler | None = None) -> None:
        if not kind:
            raise ValueError("job kind cannot be empty")
        if kind in self._handlers:
            raise ValueError(f"job handler already registered: {kind}")
        self._handlers[kind] = handler
        self._give_up[kind] = on_give_up

    def resolve(self, kind: str) -> JobHandler:
        try:
            return self._handlers[kind]
        except KeyError as exc:
            raise LookupError(f"no job handler registered for: {kind}") from exc

    def __contains__(self, kind: str) -> bool:
        return kind in self._handlers

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    def give_up_handler(self, kind: str) -> GiveUpHandler | None:
        return self._give_up.get(kind)
