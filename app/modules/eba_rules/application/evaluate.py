"""Compute alerts for the active panel and a profile (thesis §3.4); persist them atomically."""
from __future__ import annotations

from typing import Any

from app.modules.eba_rules.application.profiles import load_profile
from app.modules.eba_rules.domain.alert_level import evaluate_rows as _evaluate_rows
from app.modules.eba_rules.domain.profile_schema import validate_profile
from app.modules.eba_rules.infrastructure.alert_repository import fetch_active_panel, replace_alerts


def evaluate_rows(profile: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate the profile, then evaluate panel rows (in memory, deterministic)."""
    validate_profile(profile)
    return _evaluate_rows(profile, rows)


def evaluate_panel(conn, profile_name: str | None = None, persist: bool = True) -> list[dict[str, Any]]:
    """Alerts of the active panel for a profile; persist=True replaces the profile's alert rows."""
    profile, sha = load_profile(profile_name)
    with conn:
        with conn.cursor() as cur:
            results = evaluate_rows(profile, fetch_active_panel(cur))
            if persist:
                replace_alerts(cur, profile_name or profile["profile"], sha, results)
    return results
