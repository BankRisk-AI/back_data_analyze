"""Histograms of the panel: coverage of banks and periods, and the distribution of the indicators."""
from __future__ import annotations

import os
from collections import Counter

import matplotlib.pyplot as plt
from app.core.panel_reader import INDICATORS

DEFAULT_INDICATORS = ("cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
                      "npl_ratio", "stage2_share", "roe_annualised", "loan_growth_yoy")


def _values(rows: list[dict], indicator: str) -> list[float]:
    """The non-missing values of one indicator."""
    if indicator not in INDICATORS:
        raise ValueError(f"unknown indicator {indicator!r}; choose one of {', '.join(INDICATORS)}")
    return [r[indicator] for r in rows if r[indicator] is not None]


def coverage_figure(rows: list[dict]):
    """Left: periods per bank. Right: banks per period. Returns (figure, summary)."""
    periods_per_bank = Counter(r["bank_id"] for r in rows)
    banks_per_period = Counter(str(r["period"])[:10] for r in rows)
    n_periods = len(banks_per_period)
    full = sum(1 for count in periods_per_bank.values() if count == n_periods)

    fig, (left, right) = plt.subplots(1, 2, figsize=(14, 5), gridspec_kw={"width_ratios": [1, 1.6]})
    left.hist(list(periods_per_bank.values()), bins=range(1, n_periods + 2), align="left",
              edgecolor="black", linewidth=0.3)
    left.set(title=f"{len(periods_per_bank)} banks, {full} present in all {n_periods} periods",
             xlabel="number of periods in the panel", ylabel="number of banks")
    periods = sorted(banks_per_period)
    right.bar(range(len(periods)), [banks_per_period[p] for p in periods])
    right.set_xticks(range(len(periods)))
    right.set_xticklabels(periods, rotation=90, fontsize=7)
    right.set(title=f"banks per period (mean {len(rows) / max(n_periods, 1):.0f})", ylabel="number of banks")
    fig.tight_layout()
    return fig, {"banks": len(periods_per_bank), "periods": n_periods, "full_coverage_banks": full}


def indicator_figure(rows: list[dict], indicator: str, bins: int = 30):
    """Distribution of one indicator over all rows. Returns (figure, number of values)."""
    values = _values(rows, indicator)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(values, bins=bins, edgecolor="black", linewidth=0.3)
    ax.set(title=f"{indicator}: {len(values)} values, {len({r['bank_id'] for r in rows})} banks",
           xlabel=indicator, ylabel="count")
    fig.tight_layout()
    return fig, len(values)


def indicators_figure(rows: list[dict], title: str, bins: int = 30,
                      indicators: tuple[str, ...] = DEFAULT_INDICATORS, clip: tuple[float, float] = (1, 99)):
    """One histogram per indicator, clipped to the given percentiles; the title says how many values fall outside."""
    import numpy as np
    columns = 2
    lines = (len(indicators) + 1) // columns
    fig, axes = plt.subplots(lines, columns, figsize=(11, 2.8 * lines))
    counts: dict[str, int] = {}
    for ax, indicator in zip(axes.flat, indicators):
        values = _values(rows, indicator)
        counts[indicator] = len(values)
        if values:
            low, high = np.percentile(values, clip)
            outside = sum(1 for v in values if v < low or v > high)
            ax.hist(values, bins=bins, range=(low, high), edgecolor="black", linewidth=0.3)
            ax.set(title=f"{indicator} (n={len(values)}, {outside} outside p{clip[0]:g}-p{clip[1]:g})", ylabel="count")
        else:
            ax.set(title=f"{indicator} (no values)")
    fig.suptitle(title)
    fig.tight_layout()
    return fig, counts


def show_or_save(figures: dict, graph_out: str | None) -> list[str]:
    """Show all figures in windows, or save them when graph_out is given (one file per figure)."""
    if graph_out is None:
        plt.show()
        return []
    base, extension = os.path.splitext(graph_out)
    extension = extension or ".png"
    paths = []
    for name, fig in figures.items():
        path = f"{base}{extension}" if len(figures) == 1 else f"{base}_{name}{extension}"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths.append(path)
    return paths

def print_outliers(rows: list[dict], top: int = 5, indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> None:
    """The most extreme values of each indicator (both ends), for manual review (thesis Table 3.7)."""
    for indicator in indicators:
        present = [r for r in rows if r[indicator] is not None]
        if not present:
            continue
        ordered = sorted(present, key=lambda r: r[indicator])
        print(f"\n{indicator}")
        for label, chosen in (("lowest", ordered[:top]), ("highest", ordered[-top:][::-1])):
            for r in chosen:
                print(f"  {label:7s} bank={r['bank_id']:<4} period={r['period']} value={r[indicator]:.4f} "
                      f"specialist={r['is_specialist']}")