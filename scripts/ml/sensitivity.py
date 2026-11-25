"""Thesis sensitivity runs (§3.5, T-3): alternative label E3, or tail quantile 0.975.

    python -m scripts.ml.sensitivity --which E3 --out data/ml/T3_E3
    python -m scripts.ml.sensitivity --which q975 --out data/ml/T3_q975

The primary run is `scripts.ml.train_thesis`; these two change one parameter of it.
Quantile values come from `sensitivity_quantiles` in config/ml.yaml.
"""
from __future__ import annotations

import argparse

from app.modules.eba_ml.application.config import load_ml_config
from scripts.ml.train_thesis import run_training


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Thesis sensitivity run")
    p.add_argument("--which", required=True, choices=["E3", "q975"])
    p.add_argument("--out", required=True)
    p.add_argument("--reuse-search", action="store_true")
    a = p.parse_args(argv)
    if a.which == "E3":
        run_training(a.out, label="E3", sensitivity="E3", reuse_search=a.reuse_search)
    else:
        quantile = load_ml_config()["sensitivity_quantiles"][0]
        run_training(a.out, tail_quantile=quantile, sensitivity="q975",
                     reuse_search=a.reuse_search)


if __name__ == "__main__":
    main()
