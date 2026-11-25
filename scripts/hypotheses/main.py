"""Thesis hypotheses H1a-H5 on one training run (thesis §3.6).

    python -m scripts.hypotheses.main --run data/ml/T3_primary [--out DIR] [--quick]

Recipe: load run -> H1a -> H1b -> H2 -> H3 -> H5 -> report. Read-only on the database.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.core.config import get_schema
from app.core.database import connect
from app.modules.eba_ml.application.io import get_logger
from scripts.hypotheses.context import load_run, load_settings
from scripts.hypotheses.h1a import compute_h1a
from scripts.hypotheses.h1b import compute_h1b
from scripts.hypotheses.h2 import compute_h2
from scripts.hypotheses.h3 import compute_h3
from scripts.hypotheses.h5 import compute_h5
from scripts.hypotheses.report import build_report, write_report


def run_hypotheses(run_dir: str | Path, out_dir: str | Path | None = None,
                   quick: bool = False) -> dict[str, Any]:
    """Evaluate H1a-H5 for a training run and write the report (default: into the run dir)."""
    logger = get_logger()
    logger.info("hypotheses run=%s quick=%s", run_dir, quick)
    out = Path(out_dir) if out_dir else Path(run_dir)
    conn = connect(get_schema())
    try:
        ctx = load_run(run_dir, conn, load_settings(quick))
        sections = {"H1a": compute_h1a(ctx), "H1b": compute_h1b(ctx), "H2": compute_h2(ctx),
                    "H3": compute_h3(ctx), "H5": compute_h5(ctx)}
        report = build_report(ctx, sections)
        write_report(report, out, quick)
        logger.info("run finished")
        return report
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate thesis hypotheses H1a-H5 on a run")
    parser.add_argument("--run", required=True, help="directory with results_*.json")
    parser.add_argument("--out", help="output directory (default: the run directory)")
    parser.add_argument("--quick", action="store_true", help="reduced replicates and H3 budget")
    args = parser.parse_args(argv)
    run_hypotheses(args.run, args.out, args.quick)


if __name__ == "__main__":
    main()
