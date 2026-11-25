"""After-panel-rebuild hook: evaluate the active profile for the new panel."""
from __future__ import annotations

from app.modules.eba_rules.application.evaluate import evaluate_panel
from app.modules.eba_rules.application.profiles import active_profile_name


def evaluate_active_profile(conn, event) -> None:
    """Recompute and upsert the alerts of the active profile (alert_ids of unchanged rows are kept)."""
    evaluate_panel(conn, active_profile_name())
