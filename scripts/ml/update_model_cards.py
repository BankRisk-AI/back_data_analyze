"""One-off registry operations for the thesis models (T-4): register T3_primary, add SHAP cards.

    python -m scripts.ml.update_model_cards --target test [--register]

WRITES to the database selected by --target (never run against prod by accident: pass it
explicitly). Both operations are idempotent and live in app registry.
"""
from __future__ import annotations

import argparse
import os

from scripts.common import select_target


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Register T3_primary / update SHAP model cards")
    p.add_argument("--target", choices=("test", "prod"), required=True)
    p.add_argument("--register", action="store_true",
                   help="also (re-)import the T3_primary experiment before updating the cards")
    p.add_argument("--result", default="data/ml/T3_primary/results_E2_or_E3_semiannual_robust.json")
    a = p.parse_args(argv)
    select_target(a.target)
    from app.core.config import get_schema
    from app.core.database import connect
    from app.modules.eba_ml.application.registry import (
        import_t3_primary_experiment, update_t3_shap_model_cards)
    conn = connect(get_schema())
    try:
        if a.register:
            print("experiment_id", import_t3_primary_experiment(conn, a.result))
        update_t3_shap_model_cards(conn, a.result)
        print("model cards updated on", os.environ["DATABASE_URL"].rsplit("/", 1)[-1])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
