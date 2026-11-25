"""Look at the panel: counts, first rows and histograms (read-only, SELECT only).

    python -m scripts.analyses.main                          # summary + coverage and indicator histograms
    python -m scripts.analyses.main --bank 68                # histograms of one bank
    python -m scripts.analyses.main --indicator npl_ratio    # adds one indicator in detail
    python -m scripts.analyses.main --out /tmp/panel.csv --no-plot
    python -m scripts.analyses.main --graph-out /tmp/panel.png   # save instead of showing
"""
from __future__ import annotations

import argparse
import csv
import json

from scripts.analyses.draw_graph import (
    coverage_figure,
    indicator_figure,
    indicators_figure,
    print_outliers,
    show_or_save,
)
from scripts.analyses.panel_data import get_panel


def write_csv(rows: list[dict], path: str) -> None:
    """CSV with one column per key; `flags` is written as JSON."""
    if not rows:
        open(path, "w").close()
        return
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({**r, "flags": json.dumps(r.get("flags"), sort_keys=True)} for r in rows)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Command-line options."""
    parser = argparse.ArgumentParser(description="Panel rows from load_panel (read-only)")
    parser.add_argument("--bank", type=int, help="bank_id: show this bank's histograms")
    parser.add_argument("--period", help="one period end: YYYY-MM-DD or YYYYMM")
    parser.add_argument("--from", dest="date_from", help="first period end (inclusive)")
    parser.add_argument("--to", dest="date_to", help="last period end (inclusive)")
    parser.add_argument("--indicator", help="also show one indicator in detail, e.g. cet1_ratio")
    parser.add_argument("--bins", type=int, default=30, help="number of histogram bins")
    parser.add_argument("--show", type=int, default=5, help="number of rows to print")
    parser.add_argument("--out", help="write all rows to this CSV file")
    parser.add_argument("--graph-out", help="save the figures to this PNG instead of showing them")
    parser.add_argument("--no-plot", action="store_true", help="print only, no figures")
    parser.add_argument(
        "--with-specialists",
        action="store_true",
        help="keep specialist institutions (excluded by default)",
    )
    parser.add_argument(
        "--outliers", action="store_true", help="print the most extreme values per indicator"
    )
    return parser.parse_args(argv)


def print_summary(rows: list[dict], show: int) -> None:
    """Counts, then the first rows without the flags column."""
    print(f"rows={len(rows)} banks={len({r['bank_id'] for r in rows})} "
          f"periods={len({r['period'] for r in rows})}")
    for row in rows[:show]:
        print({key: value for key, value in row.items() if key != "flags"})


def build_figures(rows: list[dict], args: argparse.Namespace) -> dict:
    """Coverage + all indicators for the whole panel, or the indicators of one bank."""
    figures = {}
    if args.bank is None:
        figures["coverage"], summary = coverage_figure(rows)
        print(f"coverage: {summary}")
        figures["indicators"], _ = indicators_figure(rows, f"Indicators over all banks ({len(rows)} rows)", args.bins)
    else:
        figures["bank"], counts = indicators_figure(rows, f"Bank {args.bank}: indicators over {len(rows)} periods",
                                                    min(args.bins, 15))
        print(f"bank {args.bank}: values per indicator {counts}")
    if args.indicator:
        figures["indicator"], n_values = indicator_figure(rows, args.indicator, args.bins)
        print(f"{args.indicator}: {n_values} values")
    return figures


def main(argv: list[str] | None = None) -> int:
    """Recipe: read the panel, summarise, optionally write CSV, then show (or save) the histograms."""
    args = parse_args(argv)
    rows = get_panel(args.bank, args.period, args.date_from, args.date_to)
    if not args.with_specialists:
        rows = [r for r in rows if not r["is_specialist"]]
    if args.outliers:
        print_outliers(rows)
    print_summary(rows, args.show)
    if args.out:
        write_csv(rows, args.out)
        print(f"written {args.out}")
    if not args.no_plot and rows:
        saved = show_or_save(build_figures(rows, args), args.graph_out)
        for path in saved:
            print(f"saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())