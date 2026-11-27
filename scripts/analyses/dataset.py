"""Train / test split of the panel with the same dates as the ML pipeline, and how the two parts compare."""
from __future__ import annotations

from collections import Counter
from datetime import date

import matplotlib.pyplot as plt
import numpy as np

from scripts.analyses.draw_graph import DEFAULT_INDICATORS, _values

TRAIN_END = date(2020, 12, 31)                              # last training period
TEST_START, TEST_END = date(2022, 1, 1), date(2024, 12, 31)  # 2021 = 12-month embargo (label horizon)


# ---------- split ----------

def split_rows(rows: list[dict], semiannual: bool = False) -> tuple[list[dict], list[dict]]:
    """Train rows (<= 2020-12) and test rows (2022-2024); optionally June/December only (the ML grid)."""
    if semiannual:
        rows = [r for r in rows if r["period"].month in (6, 12)]
    train = [r for r in rows if r["period"] <= TRAIN_END]
    test = [r for r in rows if TEST_START <= r["period"] <= TEST_END]
    return train, test


def bank_overlap(train: list[dict], test: list[dict]) -> dict:
    """How many banks are only in train, only in test, or in both."""
    a, b = {r["bank_id"] for r in train}, {r["bank_id"] for r in test}
    return {"train_banks": len(a), "test_banks": len(b), "both": len(a & b),
            "only_train": len(a - b), "only_test": len(b - a)}


def split_summary(train: list[dict], test: list[dict],
                  indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> list[dict]:
    """Per indicator: counts, missing share, median, p10/p90 in train and test, and the KS distance."""
    from scipy.stats import ks_2samp
    result = []
    for indicator in indicators:
        a, b = _values(train, indicator), _values(test, indicator)
        item = {"indicator": indicator, "n_train": len(a), "n_test": len(b),
                "missing_train": 1 - len(a) / max(len(train), 1),
                "missing_test": 1 - len(b) / max(len(test), 1)}
        if a and b:
            item.update({"median_train": np.median(a), "median_test": np.median(b),
                         "p10_train": np.percentile(a, 10), "p90_train": np.percentile(a, 90),
                         "p10_test": np.percentile(b, 10), "p90_test": np.percentile(b, 90),
                         "ks": ks_2samp(a, b).statistic})
        result.append(item)
    return result


def print_split(rows: list[dict], semiannual: bool = False) -> None:
    """Train / test sizes, bank overlap and the per-indicator comparison table."""
    train, test = split_rows(rows, semiannual)
    total = max(len(train) + len(test), 1)
    print(f"\ntrain rows={len(train)}  test rows={len(test)}  share train={len(train) / total:.0%}"
          f"{'  (June/December only)' if semiannual else ''}")
    print(f"banks: {bank_overlap(train, test)}")
    print("\nindicator              n_tr  n_te  miss_tr miss_te   med_tr  med_te    p10-p90 train      p10-p90 test     KS")
    for s in split_summary(train, test):
        if "ks" not in s:
            print(f"{s['indicator']:22s} {s['n_train']:5d} {s['n_test']:5d}  (no values on one side)")
            continue
        print(f"{s['indicator']:22s} {s['n_train']:5d} {s['n_test']:5d} {s['missing_train']:7.0%} {s['missing_test']:7.0%} "
              f"{s['median_train']:8.3f} {s['median_test']:7.3f}  "
              f"[{s['p10_train']:6.3f}, {s['p90_train']:6.3f}]  [{s['p10_test']:6.3f}, {s['p90_test']:6.3f}]  {s['ks']:.2f}")


# ---------- figures ----------

def split_timeline_figure(rows: list[dict], semiannual: bool = False):
    """Rows per period, coloured train / not used / test. Returns (figure, number of periods)."""
    if semiannual:
        rows = [r for r in rows if r["period"].month in (6, 12)]
    counts = Counter(r["period"] for r in rows)
    periods = sorted(counts)

    def colour(period):
        if period <= TRAIN_END:
            return "tab:blue"
        if TEST_START <= period <= TEST_END:
            return "tab:orange"
        return "lightgrey"

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(range(len(periods)), [counts[p] for p in periods], color=[colour(p) for p in periods])
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels([str(p)[:7] for p in periods], rotation=90, fontsize=7)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in ("tab:blue", "lightgrey", "tab:orange")]
    ax.legend(handles, ["train (<= 2020)", "not used (2021 embargo, 2025)", "test (2022-2024)"],
              fontsize=8, frameon=False)
    ax.set(title="Rows per period in the train / test split", ylabel="number of banks")
    fig.tight_layout()
    return fig, len(periods)


def split_distributions_figure(train: list[dict], test: list[dict],
                               indicators: tuple[str, ...] = DEFAULT_INDICATORS,
                               bins: int = 30, clip: tuple[float, float] = (1, 99)):
    """Overlaid train / test histograms per indicator (density, common p1-p99 range). Returns (figure, panels)."""
    from scipy.stats import ks_2samp
    columns = 2
    lines = (len(indicators) + 1) // columns
    fig, axes = plt.subplots(lines, columns, figsize=(11, 2.8 * lines))
    for ax, indicator in zip(axes.flat, indicators):
        a, b = _values(train, indicator), _values(test, indicator)
        if not a or not b:
            ax.set(title=f"{indicator}: no values in {'train' if not a else 'test'}")
            continue
        low, high = np.percentile(a + b, clip)
        ax.hist(a, bins=bins, range=(low, high), density=True, alpha=0.5, color="tab:blue", label=f"train (n={len(a)})")
        ax.hist(b, bins=bins, range=(low, high), density=True, alpha=0.5, color="tab:orange", label=f"test (n={len(b)})")
        ax.axvline(np.median(a), color="tab:blue", linestyle="--", linewidth=1)
        ax.axvline(np.median(b), color="tab:orange", linestyle="--", linewidth=1)
        ax.set_title(f"{indicator}  KS = {ks_2samp(a, b).statistic:.2f}", fontsize=9)
        ax.legend(fontsize=7, frameon=False)
    for ax in list(axes.flat)[len(indicators):]:
        ax.set_visible(False)
    fig.suptitle("Train (<= 2020) vs test (2022-2024): dashed lines are medians")
    fig.tight_layout()
    return fig, len(indicators)


def split_figures(rows: list[dict], semiannual: bool = False, bins: int = 30) -> dict:
    """Both split figures, keyed for show_or_save."""
    train, test = split_rows(rows, semiannual)
    timeline, _ = split_timeline_figure(rows, semiannual)
    distributions, _ = split_distributions_figure(train, test, bins=bins)
    return {"split_timeline": timeline, "split_distributions": distributions}