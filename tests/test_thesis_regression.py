"""Thesis regression: stored T3_primary hypotheses and v1.1 alerts must not change. Run: pytest -m thesis."""
import json
from pathlib import Path

import pytest

from thesis_panel import panel_rows

pytestmark = pytest.mark.thesis
RUN = Path("data/ml/T3_primary")
EXPECTED_ALERTS = Path(__file__).parent / "data" / "eu_eba_v1_1_expected_alerts.json"


def test_v1_1_alerts_on_the_fixed_synthetic_panel_match_the_stored_file():
    from app.modules.eba_rules.public import evaluate_rows, load_profile
    results = evaluate_rows(load_profile("eu_eba")[0], panel_rows())
    actual = [{"bank_id": r["bank_id"], "version_id": r["version_id"], "level": r["level"],
               "score": r["score"], "reason": r["rule_results"]["level_reason"],
               "family_scores": r["rule_results"]["family_scores"],
               "triggered": sorted(x["rule_id"] for x in r["rule_results"]["rules"] if x["triggered"])}
              for r in results]
    assert json.loads(json.dumps(actual)) == json.loads(EXPECTED_ALERTS.read_text())


def test_t3_primary_hypotheses_are_reproduced(tmp_path):
    if not RUN.is_dir():
        pytest.skip("data/ml/T3_primary is absent")
    from app.core.config import get_schema
    from app.core.database import connect
    from app.modules.eba_ml.application.dataset import build_dataset
    from scripts.hypotheses.main import run_hypotheses
    stored = json.loads((RUN / "hypotheses.json").read_text())
    artifact = json.loads(next(RUN.glob("results_*.json")).read_text())
    conn = connect(get_schema())
    try:
        live_hash = build_dataset(conn, artifact.get("grid", "semiannual"), artifact.get("robustness", True))["panel_hash"]
    finally:
        conn.close()
    if live_hash != artifact["panel_hash"]:
        pytest.skip("the test database does not hold the thesis panel (panel_hash differs)")
    run_hypotheses(RUN, tmp_path)
    new = json.loads((tmp_path / "hypotheses.json").read_text())
    stored.pop("run"), new.pop("run")
    assert new == stored
