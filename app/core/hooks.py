"""Registry of "after panel rebuild" hooks. Modules register theirs through their ModuleSpec."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PanelRebuilt:
    """What a hook is told about the panel that was just written (already committed)."""
    rows: int
    version_ids: list[int] = field(default_factory=list)


PanelHook = Callable[[object, PanelRebuilt], None]   # (connection, event) -> None
_HOOKS: dict[str, PanelHook] = {}


class PanelHookError(RuntimeError):
    """One or more hooks failed; the panel itself was written and committed."""


def register_after_panel_rebuild(name: str, hook: PanelHook) -> None:
    """Register a hook under a unique name (re-registering the same name replaces it)."""
    _HOOKS[name] = hook


def register_module_hooks(modules) -> None:
    """Register the `after_panel_rebuild` hook of every ModuleSpec that has one (call at startup)."""
    for module in modules:
        if module.after_panel_rebuild:
            register_after_panel_rebuild(module.name, module.after_panel_rebuild)


def registered_hooks() -> list[str]:
    """Names of the registered hooks, in registration order."""
    return list(_HOOKS)


def run_after_panel_rebuild(conn, event: PanelRebuilt) -> None:
    """Run every hook; a failing hook is logged and does not stop the others; failures are raised at the end."""
    failed = []
    for name, hook in _HOOKS.items():
        try:
            hook(conn, event)
        except Exception as exc:                       # noqa: BLE001 - isolate hooks from each other
            logger.exception("after-panel-rebuild hook %s failed", name)
            failed.append(f"{name}: {exc}")
    if failed:
        raise PanelHookError("; ".join(failed))
