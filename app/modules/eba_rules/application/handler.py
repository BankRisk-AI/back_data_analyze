"""Worker job `evaluate_rules`: evaluate the profile in env EBA_RULE_PROFILE (default: active)."""
from __future__ import annotations

import os

from app.core.database import connect
from app.core.worker import JobHandlerRegistry
from app.modules.eba_rules.application.evaluate import evaluate_panel
from app.modules.eba_rules.application.profiles import active_profile_name


def register_handlers(registry: JobHandlerRegistry) -> None:
    """Register the job handler on the worker registry."""

    def handle(job, progress) -> None:
        profile_name = os.getenv("EBA_RULE_PROFILE", active_profile_name())
        progress(f"evaluating rules profile={profile_name}", 5)
        conn = connect(job.schema)
        try:
            count = len(evaluate_panel(conn, profile_name))
        finally:
            conn.close()
        progress(f"evaluated {count} alerts", 99)

    registry.register("evaluate_rules", handle)
