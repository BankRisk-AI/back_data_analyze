"""Thesis regression (needs the thesis panel in the test database): stored T3_primary hypotheses are reproduced. Run: pytest -m thesis."""
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.thesis
RUN = Path("data/ml/T3_primary")


def test_t3_primary_hypotheses_are_reproduced(tmp_path, db):
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
