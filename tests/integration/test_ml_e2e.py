"""Integration e2e: seeded synthetic panel in eba_test -> build_dataset -> train -> hypotheses --quick.

Seeds and removes its own rows (10 synthetic banks); never reads production data.
"""
from __future__ import annotations

import pytest
from ml_synthetic import clear_panel, seed_panel

@pytest.fixture()
def seeded(db):
    seed_panel(db.cur)
    yield db
    clear_panel(db.cur)


@pytest.mark.slow
def test_ml_train_and_hypotheses_quick(seeded, tmp_path):
    """build_dataset -> labels -> train (LR) -> run_hypotheses(quick) on the seeded panel."""
    from app.modules.eba_ml.application.training.train import train
    from scripts.hypotheses.main import run_hypotheses

    out_dir = tmp_path / "ml_e2e"
    result = train(seeded.conn, label="E2_or_E3", grid="semiannual", out_dir=out_dir,
                   robustness=False, models=["LR"], wall_clock_hours=2.0 / 60)
    assert list(out_dir.glob("results_*.json"))
    assert result["label"] == "E2_or_E3"
    assert {"predictions", "operating_point_threshold", "r1_margin"} <= set(result)
    assert result["label_meta"]["n_included"] > 0

    report = run_hypotheses(out_dir, quick=True)
    assert {"H1a", "H1b", "H2", "H3", "H5"} <= set(report)
    assert (out_dir / "hypotheses_quick.json").exists()
