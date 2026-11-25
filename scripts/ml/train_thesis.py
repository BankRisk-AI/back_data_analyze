"""Thesis training run (§3.5): hyperparameter search, OOF refit, final test, results JSON.

    python -m scripts.ml.train_thesis --out data/ml/T3_primary
    python -m scripts.ml.train_thesis --out data/ml/T3_E3 --label E3 --sensitivity E3

Calls app training with the SMOTE comparison hook; all other parameters come from config/ml.yaml.
Reads the database; writes only under --out and logs/.
"""
from __future__ import annotations

import argparse
from typing import Any

from app.core.config import get_schema
from app.core.database import connect
from app.modules.eba_ml.application.training.train import train
from scripts.ml.smote_comparison import smote_fold_comparison


def run_training(out_dir: str, label: str | None = None, models: list[str] | None = None,
                 tail_quantile: float | None = None, sensitivity: str | None = None,
                 grid: str = "semiannual", space: str = "table35", robustness: bool = True,
                 wall_clock_hours: float = 2.0, reuse_search: bool = False) -> dict[str, Any]:
    """Train on the production panel and write results_<label>_<grid>[_robust].json to out_dir."""
    conn = connect(get_schema())
    try:
        return train(conn, label=label, grid=grid, out_dir=out_dir, robustness=robustness,
                     models=models, wall_clock_hours=wall_clock_hours, space=space,
                     reuse_search=reuse_search, tail_quantile=tail_quantile,
                     sensitivity=sensitivity, fold_diagnostic=smote_fold_comparison)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Thesis training run (§3.5)")
    p.add_argument("--out", required=True, help="output directory, e.g. data/ml/T3_primary")
    p.add_argument("--label", help="E1, E2, E3 or E2_or_E3 (default: config/ml.yaml)")
    p.add_argument("--models", nargs="*", help="subset of LR RF XGB")
    p.add_argument("--tail-quantile", type=float, help="override config tail_quantile")
    p.add_argument("--sensitivity", help="tag stored in the results, e.g. E3 or q975")
    p.add_argument("--grid", default="semiannual", choices=["semiannual", "quarterly"])
    p.add_argument("--space", default="table35", choices=["table35", "extended"])
    p.add_argument("--no-robustness", action="store_true", help="drop the robustness feature set")
    p.add_argument("--wall-clock-hours", type=float, default=2.0)
    p.add_argument("--reuse-search", action="store_true",
                   help="reuse <out>/search.json when the panel hash matches")
    a = p.parse_args(argv)
    run_training(a.out, a.label, a.models, a.tail_quantile, a.sensitivity, a.grid, a.space,
                 not a.no_robustness, a.wall_clock_hours, a.reuse_search)


if __name__ == "__main__":
    main()
