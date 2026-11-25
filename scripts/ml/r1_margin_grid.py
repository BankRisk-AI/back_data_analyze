"""R1 margin diagnostic grid (thesis §3.5): F2 / precision / recall / alert share per margin.

    python -m scripts.ml.r1_margin_grid --run data/ml/T3_primary

Evaluates rule R1 on the final-test rows of a run for every margin in `r1_margin_grid_pp`
(eba_rules regulatory_levels.yaml). Diagnostic only: the margin used by the run is chosen on training rows.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import fbeta_score, precision_score, recall_score

from app.core.config import get_schema
from app.core.database import connect
from app.modules.eba_ml.application.config import load_ml_config
from app.modules.eba_ml.application.dataset import build_dataset
from app.modules.eba_rules.public import r1_alert, r1_margin_grid_pp


def grid_rows(rows: list[dict], y: np.ndarray, r0_levels: dict, margins_pp: list[float]) -> list[dict]:
    """Metrics of R1 on (rows, y) for each margin in percentage points."""
    out = []
    for mp in margins_pp:
        alerts = np.array([int(r1_alert(r, r0_levels, mp / 100.0)) for r in rows])
        entry = {"margin_pp": mp, "alerts": int(alerts.sum())}
        if alerts.sum():
            entry.update(
                f2=float(fbeta_score(y, alerts, beta=2, zero_division=0)),
                precision=float(precision_score(y, alerts, zero_division=0)),
                recall=float(recall_score(y, alerts, zero_division=0)),
                alert_share=float(alerts.mean()))
        out.append(entry)
    return out


def test_rows(run_dir: Path, years: tuple[int, int]) -> tuple[list[dict], np.ndarray, dict]:
    """Final-test rows of the run (periods in years) with their labels, plus the run's r0 levels."""
    artifact = json.loads(next(run_dir.glob("results_*.json")).read_text())
    conn = connect(get_schema())
    try:
        dataset = build_dataset(conn, artifact.get("grid", "semiannual"),
                                artifact.get("robustness", True))
    finally:
        conn.close()
    labels = {(r["bank_id"], r["period"]): int(r["label"]) for r in artifact["rows"]}
    rows = [r for r in dataset["rows"]
            if years[0] <= r["period"].year <= years[1]
            and (r["bank_id"], r["period"].isoformat()) in labels]
    y = np.array([labels[(r["bank_id"], r["period"].isoformat())] for r in rows])
    return rows, y, artifact["label_meta"]["r0_levels"]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="R1 margin diagnostic grid on the final test")
    p.add_argument("--run", required=True)
    a = p.parse_args(argv)
    cfg = load_ml_config()
    years = (cfg["final_test"]["test_start"], cfg["final_test"]["test_end"])
    rows, y, r0_levels = test_rows(Path(a.run), years)
    print(f"rows={len(y)} positives={int(y.sum())}")
    for e in grid_rows(rows, y, r0_levels, r1_margin_grid_pp()):
        print(json.dumps(e))


if __name__ == "__main__":
    main()
