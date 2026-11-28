"""Look at the panel (read-only): counts, distributions, per-bank views, variance, change over time,
train/test split, missing values, correlations, events, event study, features, feature cards
and validity checks.

    python -m scripts.analyses.main --events --feature-cards --semiannual --label recommended --report
    python -m scripts.analyses.main --validity --semiannual --report       # validity checks
    python -m scripts.analyses.main --all --semiannual --report  # full report, ML grid
    python -m scripts.analyses.main --feature-cards --semiannual --report
    python -m scripts.analyses.main --events --label weak --horizon 24     # other label
    python -m scripts.analyses.main --features                   # quick drift + AUC per variant
    python -m scripts.analyses.main --event-study                # indicators before events
    python -m scripts.analyses.main --missing                    # missing values per period
    python -m scripts.analyses.main --correlation                # correlations between indicators
    python -m scripts.analyses.main --split                      # train (<= 2020) vs test (2022-2024)
    python -m scripts.analyses.main --per-bank --report          # PDF, one page per bank
    python -m scripts.analyses.main --per-bank --bank 68         # bank 68's page on screen
    python -m scripts.analyses.main --min-periods-table --no-plot
    python -m scripts.analyses.main --over-time                  # one chart per indicator
    python -m scripts.analyses.main --variance
    python -m scripts.analyses.main --persistence
    python -m scripts.analyses.main --boxplot cet1_ratio
    python -m scripts.analyses.main --timeseries 68
    python -m scripts.analyses.main --outliers --no-plot
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

from scripts.analyses.data_quality import (
    correlation_figure,
    missing_figure,
    print_correlations,
    print_missing,
)
from scripts.analyses.dataset import print_split, split_figures
from scripts.analyses.draw_graph import (
    DEFAULT_INDICATORS,
    bank_page_figure,
    boxplot_per_bank_figure,
    change_persistence,
    coverage_figure,
    indicator_figure,
    indicator_over_time_figure,
    indicators_figure,
    period_bands,
    persistence_figure,
    print_outliers,
    show_or_save,
    timeseries_bank_figure,
    variance_decomposition_three_way,
    variance_shares_figure,
    winsorised_rows,
    write_per_bank,
)
from scripts.analyses.events import (
    ORIGINAL,
    RECOMMENDED,
    LabelSpec,
    event_profiles,
    event_study_figure,
    events_figure,
    label_rows,
    print_event_study,
    print_events,
)
from scripts.analyses.feature_cards import (
    cards_figure,
    feature_cards,
    feature_correlation_figure,
    print_cards,
    print_feature_correlation,
    write_cards_csv,
)
from scripts.analyses.features import (
    build_features,
    feature_evidence,
    features_figure,
    print_feature_evidence,
)
from scripts.analyses.panel_data import get_panel
from scripts.analyses.validity import validity_analyses

PER_BANK_DEFAULT = "/tmp/eba/per_bank.pdf"
REPORT_DIR = str(Path(__file__).resolve().parent / "report")
# analyses switched on by --all, in the order they are printed
ANALYSES = (
    "outliers", "missing", "correlation", "variance", "persistence", "min_periods_table",
    "split", "events", "event_study", "features", "feature_cards", "validity", "over_time",
)


# ---------- input / output ----------

def write_csv(rows: list[dict], path: str) -> None:
    """CSV with one column per key; `flags` is written as JSON."""
    if not rows:
        open(path, "w").close()
        return
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "flags": json.dumps(r.get("flags"), sort_keys=True)})


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Command-line options."""
    p = argparse.ArgumentParser(description="Panel rows from load_panel (read-only)")
    p.add_argument("--bank", type=int, help="bank_id for histograms, --over-time, --per-bank")
    p.add_argument("--period", help="one period end: YYYY-MM-DD or YYYYMM")
    p.add_argument("--from", dest="date_from", help="first period end (inclusive)")
    p.add_argument("--to", dest="date_to", help="last period end (inclusive)")
    p.add_argument("--indicator", help="also show one indicator's histogram")
    p.add_argument("--bins", type=int, default=30, help="number of histogram bins")
    p.add_argument("--show", type=int, default=0, help="number of rows to print")
    p.add_argument("--out", help="write all rows to this CSV file")
    p.add_argument("--graph-out", help="save the figures to this PNG instead of showing them")
    p.add_argument("--report", nargs="?", const=REPORT_DIR, metavar="DIR",
                   help="save figures, tables and CSV to DIR (default scripts/analyses/report)")
    p.add_argument("--all", action="store_true", help="run every analysis (use with --report)")
    p.add_argument("--no-plot", action="store_true", help="print only, no figures")
    p.add_argument("--with-specialists", action="store_true", help="keep specialist institutions")
    p.add_argument("--outliers", action="store_true", help="most extreme values per indicator")
    p.add_argument("--missing", action="store_true", help="missing values per indicator and period")
    p.add_argument("--correlation", action="store_true", help="correlations between indicators")
    p.add_argument("--variance", action="store_true", help="between banks / in time / bank-specific")
    p.add_argument("--persistence", action="store_true", help="past change vs next change")
    p.add_argument("--over-time", nargs="?", const="all", metavar="INDICATOR",
                   help="one chart per indicator over time ('all' or one name)")
    p.add_argument("--per-bank", nargs="?", const=PER_BANK_DEFAULT, metavar="PATH",
                   help="one page per bank: a .pdf file or a folder of PNGs")
    p.add_argument("--min-periods", type=int, default=1, help="--per-bank: skip shorter banks")
    p.add_argument("--min-periods-table", action="store_true",
                   help="what each minimum-periods filter would keep")
    p.add_argument("--split", action="store_true", help="train (<= 2020) vs test (2022-2024)")
    p.add_argument("--semiannual", action="store_true",
                   help="split/events/event study/features/cards/validity: June/December only")
    p.add_argument("--label", choices=("abs", "rel", "weak", "recommended"), default="abs",
                   help="E2 definition: abs (original), rel, weak, or recommended "
                        "(weak + exit events + no merger windows)")
    p.add_argument("--horizon", type=int, default=12, help="event window in months")
    p.add_argument("--exit-events", action="store_true",
                   help="add E4: the bank leaves the sample in a weak state")
    p.add_argument("--drop-scope-changes", action="store_true",
                   help="unknown label for windows with a loan-book change >= 30%%")
    p.add_argument("--events", action="store_true", help="events per year, episodes, banks, E1")
    p.add_argument("--event-study", action="store_true", help="indicators before and after events")
    p.add_argument("--features", action="store_true", help="candidate features: drift and AUC")
    p.add_argument("--feature-cards", action="store_true",
                   help="evidence per feature and decision by the fixed rule")
    p.add_argument("--cards-out", metavar="PATH", help="--feature-cards: also write a CSV")
    p.add_argument("--validity", action="store_true",
                   help="ten validity checks (leavers, publication lag, known cases, ...)")
    p.add_argument("--boxplot", metavar="INDICATOR", help="one box per bank for this indicator")
    p.add_argument("--timeseries", type=int, metavar="BANK_ID", help="one bank over time")
    return p.parse_args(argv)


def label_spec(args: argparse.Namespace) -> LabelSpec:
    """The label asked for on the command line."""
    if args.label == "recommended":
        return replace(RECOMMENDED, horizon=args.horizon)
    return LabelSpec(kind=args.label, horizon=args.horizon, exits=args.exit_events,
                     drop_scope_changes=args.drop_scope_changes)


def apply_all(args: argparse.Namespace) -> None:
    """--all: switch on every analysis in ANALYSES."""
    for name in ANALYSES:
        if name == "over_time":
            args.over_time = args.over_time or "all"
        else:
            setattr(args, name, True)


def suffix(args: argparse.Namespace) -> str:
    """File-name ending: grid, then the label when it is not the original one."""
    end = "_semiannual" if args.semiannual else ""
    spec = label_spec(args)
    return end if spec == ORIGINAL else f"{end}_{spec.name()}"


def run_name(args: argparse.Namespace) -> str:
    """File name of the report text, from the analyses that were asked for."""
    if args.all:
        name = "all"
    else:
        active = [n for n in ANALYSES if getattr(args, n)]
        name = "-".join(active) if active else "overview"
    return name + suffix(args)


def load_rows(args: argparse.Namespace) -> list[dict]:
    """Whole panel for cross-bank views; one bank for --timeseries or plain --bank."""
    cross_bank = any([
        args.over_time, args.variance, args.persistence, args.boxplot, args.per_bank,
        args.split, args.min_periods_table, args.missing, args.correlation,
        args.events, args.event_study, args.features, args.feature_cards, args.validity,
    ])
    if args.timeseries is not None:
        bank = args.timeseries
    elif cross_bank:
        bank = None
    else:
        bank = args.bank
    rows = get_panel(bank, args.period, args.date_from, args.date_to)
    if args.with_specialists or args.timeseries is not None:
        return rows
    return [r for r in rows if not r["is_specialist"]]


class _Tee:
    """Write printed text both to the terminal and to the report file."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def save_figures(figures: dict, directory: str, end: str) -> list[str]:
    """One PNG per figure in the report folder, named after the figure."""
    os.makedirs(directory, exist_ok=True)
    paths = []
    for name, fig in figures.items():
        path = os.path.join(directory, f"{name}{end}.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(path)
    return paths


# ---------- printed tables ----------

def print_summary(rows: list[dict], show: int) -> None:
    """Counts, then the first rows without the flags column."""
    banks = len({r["bank_id"] for r in rows})
    periods = len({r["period"] for r in rows})
    print(f"rows={len(rows)} banks={banks} periods={periods}")
    for row in rows[:show]:
        print({key: value for key, value in row.items() if key != "flags"})


def print_variance(rows: list[dict]) -> None:
    """Variance shares on raw values and on values clipped to p1-p99."""
    for label, data in (("raw values", rows), ("clipped to p1-p99", winsorised_rows(rows))):
        print(f"\n{label}")
        print("indicator              between banks  common in time  bank-specific change")
        for item in variance_decomposition_three_way(data):
            print(f"{item['indicator']:22s} {item['between_bank']:13.0%} "
                  f"{item['common_period']:15.0%} {item['bank_specific']:21.0%}")


def print_persistence(rows: list[dict]) -> None:
    """Correlation between past and next 12-month changes."""
    print("\nindicator              pairs   rho     p")
    for item in change_persistence(rows):
        print(f"{item['indicator']:22s} {item['pairs']:5d} {item['rho']:+.2f}  {item['p']:.3f}")


def print_min_periods_table(rows: list[dict], thresholds=(1, 4, 8, 12, 16, 20, 25)) -> None:
    """What a minimum-number-of-periods filter would keep."""
    by_bank = defaultdict(list)
    for r in rows:
        by_bank[r["bank_id"]].append(r["period"])
    last = max(r["period"] for r in rows)
    print("\nmin periods  banks kept  rows kept   banks dropped  of which left early")
    for threshold in thresholds:
        kept = [b for b, periods in by_bank.items() if len(periods) >= threshold]
        dropped = [b for b in by_bank if b not in kept]
        exited = sum(1 for b in dropped if max(by_bank[b]) < last)
        rows_kept = sum(len(by_bank[b]) for b in kept)
        print(f"{threshold:11d} {len(kept):11d} {rows_kept:10d} {len(dropped):15d} {exited:16d}")


# ---------- event analyses (events, event study, features, cards, validity) ----------

def event_analyses(rows: list[dict], args: argparse.Namespace) -> dict:
    """Print the event, feature and validity tables and return their figures."""
    figures = {}
    asked = (args.events or args.event_study or args.features or args.feature_cards
             or args.validity)
    if not asked:
        return figures
    items, info = label_rows(rows, args.semiannual, label_spec(args))
    print(f"\nlabel used: {info['label']}")
    if args.events:
        print_events(items, info)
        figures["events"], _ = events_figure(items)
    if args.event_study:
        profiles, n_events, n_controls = event_profiles(rows, items)
        print_event_study(profiles, n_events, n_controls)
        figures["event_study"], _ = event_study_figure(profiles, n_events)
    if args.features or args.feature_cards:
        features = build_features(rows)
        if args.features:
            evidence = feature_evidence(features, items)
            print_feature_evidence(evidence)
            figures["features"], _ = features_figure(evidence)
        if args.feature_cards:
            cards = feature_cards(features, items)
            print_cards(cards)
            print_feature_correlation(features, items, cards)
            if args.cards_out:
                write_cards_csv(cards, args.cards_out)
                print(f"written {args.cards_out}")
            figures["feature_cards"], _ = cards_figure(cards)
            figures["feature_correlation"], _ = feature_correlation_figure(features, items, cards)
    if args.validity:
        figures.update(validity_analyses(rows, items, args.semiannual))
    return figures


# ---------- figures ----------

def special_figures(rows: list[dict], args: argparse.Namespace) -> dict:
    """Figures for the specific views asked for (empty if none was asked)."""
    figures = {}
    if args.per_bank and args.bank is not None:
        bank_rows = [r for r in rows if r["bank_id"] == args.bank]
        if bank_rows:
            bands = period_bands(rows)
            figures[f"bank_{args.bank}"] = bank_page_figure(bank_rows, bands, args.bank)
        else:
            print(f"bank {args.bank} not in the panel (specialist? add --with-specialists)")
    if args.timeseries is not None:
        figures["timeseries"], _ = timeseries_bank_figure(rows, args.timeseries)
    if args.boxplot:
        figures["boxplot"], _ = boxplot_per_bank_figure(rows, args.boxplot)
    if args.missing:
        figures["missing"], _ = missing_figure(rows)
    if args.correlation:
        figures["correlation"], _ = correlation_figure(rows)
    if args.over_time:
        chosen = DEFAULT_INDICATORS if args.over_time == "all" else (args.over_time,)
        for indicator in chosen:
            fig, _ = indicator_over_time_figure(rows, indicator, args.bank)
            figures[f"over_time_{indicator}"] = fig
    if args.variance:
        items = variance_decomposition_three_way(winsorised_rows(rows))
        title = "Where the variation comes from (values clipped to p1-p99)"
        figures["variance"], _ = variance_shares_figure(items, title)
    if args.persistence:
        figures["persistence"], _ = persistence_figure(rows)
    if args.split:
        figures.update(split_figures(rows, args.semiannual, args.bins))
    return figures


def default_figures(rows: list[dict], args: argparse.Namespace) -> dict:
    """Coverage + all indicator histograms, or one bank's histograms."""
    figures = {}
    if args.bank is None:
        figures["coverage"], summary = coverage_figure(rows)
        print(f"coverage: {summary}")
        title = f"Indicators over all banks ({len(rows)} rows)"
        figures["indicators"], _ = indicators_figure(rows, title, args.bins)
    else:
        title = f"Bank {args.bank}: indicators over {len(rows)} periods"
        figures["bank"], _ = indicators_figure(rows, title, min(args.bins, 15))
    if args.indicator:
        figures["indicator"], _ = indicator_figure(rows, args.indicator, args.bins)
    return figures


# ---------- recipe ----------

def run(args: argparse.Namespace) -> int:
    """Read the panel, print what was asked, then show, save or report the figures."""
    rows = load_rows(args)
    print_summary(rows, args.show)
    if not rows:
        return 0
    if args.outliers:
        print_outliers(rows)
    if args.missing:
        print_missing(rows)
    if args.correlation:
        print_correlations(rows)
    if args.variance:
        print_variance(rows)
    if args.persistence:
        print_persistence(rows)
    if args.min_periods_table:
        print_min_periods_table(rows)
    if args.split:
        print_split(rows, args.semiannual)
    event_figures = event_analyses(rows, args)
    if args.out:
        write_csv(rows, args.out)
        print(f"written {args.out}")
    if args.per_bank and args.bank is None:
        count = write_per_bank(rows, args.per_bank, args.min_periods)
        print(f"written {count} bank pages to {args.per_bank}")
        return 0
    if args.no_plot:
        return 0
    figures = {**event_figures, **special_figures(rows, args)} or default_figures(rows, args)
    if args.report:
        paths = save_figures(figures, args.report, suffix(args))
    else:
        paths = show_or_save(figures, args.graph_out)
    for path in paths:
        print(f"saved {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the analyses; with --report also keep the printed tables in a text file."""
    args = parse_args(argv)
    if args.all:
        apply_all(args)
    if args.report is None:
        return run(args)
    os.makedirs(args.report, exist_ok=True)
    if args.feature_cards and not args.cards_out:
        args.cards_out = os.path.join(args.report, f"feature_cards{suffix(args)}.csv")
    if args.per_bank == PER_BANK_DEFAULT:
        args.per_bank = os.path.join(args.report, "per_bank.pdf")
    command = " ".join(argv if argv is not None else sys.argv[1:])
    text_path = os.path.join(args.report, f"{run_name(args)}.txt")
    with open(text_path, "w", encoding="utf-8") as text, redirect_stdout(_Tee(sys.stdout, text)):
        print(f"# generated {datetime.now():%Y-%m-%d %H:%M}")
        print(f"# command: python -m scripts.analyses.main {command}")
        code = run(args)
    print(f"report text: {text_path}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())