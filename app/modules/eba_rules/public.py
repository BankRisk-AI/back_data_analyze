"""The only interface of eba_rules that other modules and scripts may import."""
from __future__ import annotations

from app.modules.eba_rules.application.evaluate import evaluate_panel, evaluate_rows
from app.modules.eba_rules.application.profiles import (
    ProfileIntegrityError, active_profile_name, load_profile, r1_margin_grid_pp, regulatory_levels)
from app.modules.eba_rules.domain.levels import (
    choose_r1_margin, compliant, r0_alert, r1_alert)

__all__ = [
    "ProfileIntegrityError", "active_profile_name", "load_profile", "evaluate_panel",
    "evaluate_rows", "regulatory_levels", "r1_margin_grid_pp",
    "compliant", "r0_alert", "r1_alert", "choose_r1_margin",
]
