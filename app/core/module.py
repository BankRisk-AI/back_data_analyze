"""What a module gives to the application. The composition root (app/main.py, app/worker.py, the migrator) only talks to this."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter

from app.core.worker import JobHandlerRegistry


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    description: str
    router_factory: Callable[[], APIRouter] | None = None          # HTTP methods of the module
    register_handlers: Callable[[JobHandlerRegistry], None] | None = None   # job kinds the module processes in the worker
    migrations_dir: Path | None = None                              # numbered .sql files owned by the module
    tags: list[dict] = field(default_factory=list)                  # OpenAPI tag descriptions
