"""Thesis regression: v1.1 alerts on the fixed synthetic panel must not change (no database). Run: pytest -m thesis."""
import json
from pathlib import Path

import pytest

from thesis_panel import panel_rows

pytestmark = pytest.mark.thesis
EXPECTED_ALERTS = Path(__file__).resolve().parents[1] / "data" / "eu_eba_v1_1_expected_alerts.json"


def test_v1_1_alerts_on_the_fixed_synthetic_panel_match_the_stored_file():
    from app.modules.eba_rules.public import evaluate_rows, load_profile
    results = evaluate_rows(load_profile("eu_eba")[0], panel_rows())
    actual = [{"bank_id": r["bank_id"], "version_id": r["dataset_version"], "level": r["level"],
               "score": r["score"], "reason": r["rule_results"]["level_reason"],
               "family_scores": r["rule_results"]["family_scores"],
               "triggered": sorted(x["rule_id"] for x in r["rule_results"]["rules"] if x["triggered"])}
              for r in results]
    assert json.loads(json.dumps(actual)) == json.loads(EXPECTED_ALERTS.read_text())
