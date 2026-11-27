"""Figures and tables on the panel: coverage, distributions, per-bank views, variance and change over time."""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import date, timedelta

import matplotlib.pyplot as plt
import numpy as np
from app.core.panel_reader import INDICATORS

DEFAULT_INDICATORS = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
)
QUARTERLY_FROM = date(2018, 9, 30)      # EBA data are quarterly from this period on
NPL_BREAK = date(2020, 6, 30)           # NPL definition change (series break)


# ---------- helpers ----------

def _values(rows: list[dict], indicator: str) -> list[float]:
    """The non-missing values of one indicator."""
    if indicator not in INDICATORS:
        raise ValueError(f"unknown indicator {indicator!r}; choose one of {', '.join(INDICATORS)}")
    return [r[indicator] for r in rows if r[indicator] is not None]


def _month_end(period: date, months: int) -> date:
    """The month-end date `months` months after (or before) `period`."""
    index = period.year * 12 + period.month - 1 + months
    year, month0 = divmod(index, 12)
    first_of_next = date(year + (month0 + 1) // 12, (month0 + 1) % 12 + 1, 1)
    return first_of_next - timedelta(days=1)


def winsorised_rows(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS,
                    clip: tuple[float, float] = (1, 99)) -> list[dict]:
    """Copy of the rows with each indicator clipped to its p1-p99 range (robustness checks only)."""
    bounds = {}
    for indicator in indicators:
        values = _values(rows, indicator)
        if values:
            bounds[indicator] = tuple(np.percentile(values, clip))
    clipped = []
    for r in rows:
        copy = dict(r)
        for indicator, (low, high) in bounds.items():
            if copy[indicator] is not None:
                copy[indicator] = min(max(copy[indicator], low), high)
        clipped.append(copy)
    return clipped


# ---------- coverage and distributions ----------

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
    """One histogram per indicator, clipped to percentiles; the title says how many values fall outside."""
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


# ---------- per bank ----------

def boxplot_per_bank_figure(rows: list[dict], indicator: str, min_periods: int = 8, clip: tuple[float, float] = (1, 99)):
    """One box per bank (banks with at least min_periods values), sorted by median. Returns (figure, number of banks)."""
    by_bank = defaultdict(list)
    for r in rows:
        if r[indicator] is not None:
            by_bank[r["bank_id"]].append(r[indicator])
    kept = {bank: vs for bank, vs in by_bank.items() if len(vs) >= min_periods}
    order = sorted(kept, key=lambda bank: np.median(kept[bank]))
    low, high = np.percentile([v for vs in kept.values() for v in vs], clip)
    fig, ax = plt.subplots(figsize=(16, 5))
    ax.boxplot([kept[bank] for bank in order], widths=0.6)
    ax.set_ylim(low, high)
    ax.set_xticks(range(1, len(order) + 1))
    ax.set_xticklabels([str(bank) for bank in order], rotation=90, fontsize=6)
    ax.set(title=f"{indicator} per bank ({len(order)} banks with >= {min_periods} periods, sorted by median)",
           xlabel="bank_id", ylabel=indicator)
    fig.tight_layout()
    return fig, len(order)


def timeseries_bank_figure(rows: list[dict], bank_id: int,
                           indicators: tuple[str, ...] = ("cet1_ratio", "total_capital_ratio", "npl_ratio", "roe_annualised")):
    """The indicators of one bank over time (one panel per indicator). Returns (figure, number of periods)."""
    bank_rows = sorted((r for r in rows if r["bank_id"] == bank_id), key=lambda r: r["period"])
    periods = [r["period"] for r in bank_rows]
    fig, axes = plt.subplots(len(indicators), 1, figsize=(10, 2.2 * len(indicators)), sharex=True)
    for ax, indicator in zip(axes, indicators):
        ax.plot(periods, [r[indicator] for r in bank_rows], marker="o", markersize=3)
        ax.set_ylabel(indicator)
        ax.grid(alpha=0.3)
    fig.suptitle(f"Bank {bank_id}: indicators over time ({len(periods)} periods)")
    fig.tight_layout()
    return fig, len(periods)


# ---------- change over time ----------

def indicator_over_time_figure(rows: list[dict], indicator: str, highlight_bank: int | None = None):
    """Median, 25-75% and 10-90% bands across banks per period; optional line of one bank. Returns (figure, periods)."""
    by_period = defaultdict(list)
    for r in rows:
        if r[indicator] is not None:
            by_period[r["period"]].append(r[indicator])
    periods = sorted(by_period)
    bands = {q: [np.percentile(by_period[p], q) for p in periods] for q in (10, 25, 50, 75, 90)}
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.fill_between(periods, bands[10], bands[90], color="grey", alpha=0.15, label="10-90% of banks")
    ax.fill_between(periods, bands[25], bands[75], color="grey", alpha=0.35, label="25-75% of banks")
    ax.plot(periods, bands[50], color="black", linewidth=1.5, label="median bank")
    if highlight_bank is not None:
        bank_rows = sorted((r for r in rows if r["bank_id"] == highlight_bank and r[indicator] is not None),
                           key=lambda r: r["period"])
        ax.plot([r["period"] for r in bank_rows], [r[indicator] for r in bank_rows],
                color="tab:blue", marker="o", markersize=3, label=f"bank {highlight_bank}")
    ax.axvline(QUARTERLY_FROM, color="grey", linestyle=":", linewidth=1)
    ax.text(QUARTERLY_FROM, ax.get_ylim()[1], " quarterly data from here", va="top", fontsize=8, color="grey")
    if indicator == "npl_ratio":
        ax.axvline(NPL_BREAK, color="tab:red", linestyle="--", linewidth=1)
        ax.text(NPL_BREAK, ax.get_ylim()[1], " NPL definition change", va="top", fontsize=8, color="tab:red")
    ax.set(title=f"{indicator} over time across banks", ylabel=indicator)
    ax.legend(loc="upper left", fontsize=8, frameon=False, bbox_to_anchor=(1.0, 1.0))
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig, len(periods)


def variance_decomposition_three_way(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> list[dict]:
    """Shares of variance: between banks, common to a period, and bank-specific change over time."""
    result = []
    for indicator in indicators:
        present = [r for r in rows if r[indicator] is not None]
        if len(present) < 2:
            continue
        values = np.array([r[indicator] for r in present])
        grand = values.mean()
        total = ((values - grand) ** 2).sum()
        by_bank = defaultdict(list)
        for r in present:
            by_bank[r["bank_id"]].append(r[indicator])
        bank_mean = {bank: np.mean(vs) for bank, vs in by_bank.items()}
        by_period = defaultdict(list)
        for r in present:
            by_period[r["period"]].append(r[indicator] - bank_mean[r["bank_id"]])
        between_bank = sum(len(vs) * (bank_mean[bank] - grand) ** 2 for bank, vs in by_bank.items())
        common_period = sum(len(ds) * np.mean(ds) ** 2 for ds in by_period.values())
        bank_specific = max(total - between_bank - common_period, 0.0)
        result.append({"indicator": indicator, "between_bank": between_bank / total,
                       "common_period": common_period / total, "bank_specific": bank_specific / total})
    return result


def variance_shares_figure(items: list[dict], title: str):
    """Horizontal stacked bars: between banks, common in time, bank-specific change. Returns (figure, rows)."""
    names = [item["indicator"] for item in items][::-1]
    parts = (("between_bank", "between banks (bank profile)", "lightgrey"),
             ("common_period", "common to all banks in a period", "grey"),
             ("bank_specific", "bank-specific change over time", "tab:blue"))
    fig, ax = plt.subplots(figsize=(10, 0.5 * len(names) + 1.8))
    left = np.zeros(len(names))
    for key, label, colour in parts:
        shares = np.array([item[key] for item in items][::-1])
        ax.barh(names, shares, left=left, color=colour, label=label)
        for y, (start, share) in enumerate(zip(left, shares)):
            if share >= 0.06:
                ax.text(start + share / 2, y, f"{share:.0%}", ha="center", va="center", fontsize=8)
        left += shares
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_title(title, loc="left")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.35), ncol=3, fontsize=8, frameon=False)
    fig.tight_layout()
    return fig, len(items)


def _change_pairs(rows: list[dict], indicator: str) -> tuple[list[float], list[float]]:
    """(past 12-month change, next 12-month change) for every bank-period where both exist."""
    series = defaultdict(dict)
    for r in rows:
        if r[indicator] is not None:
            series[r["bank_id"]][r["period"]] = r[indicator]
    past, future = [], []
    for values in series.values():
        for period, now in values.items():
            before, after = values.get(_month_end(period, -12)), values.get(_month_end(period, 12))
            if before is not None and after is not None:
                past.append(now - before)
                future.append(after - now)
    return past, future


def change_persistence(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> list[dict]:
    """Spearman correlation between past and next 12-month changes (positive = momentum, negative = reversion)."""
    from scipy.stats import spearmanr
    result = []
    for indicator in indicators:
        past, future = _change_pairs(rows, indicator)
        if len(past) >= 30:
            rho, p_value = spearmanr(past, future)
            result.append({"indicator": indicator, "pairs": len(past), "rho": rho, "p": p_value})
    return result


def persistence_figure(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS,
                       clip: tuple[float, float] = (1, 99)):
    """Scatter of past vs next 12-month change per indicator, axes clipped to percentiles. Returns (figure, panels)."""
    from scipy.stats import spearmanr
    columns = 2
    lines = (len(indicators) + 1) // columns
    fig, axes = plt.subplots(lines, columns, figsize=(11, 3.2 * lines))
    for ax, indicator in zip(axes.flat, indicators):
        past, future = _change_pairs(rows, indicator)
        if len(past) < 30:
            ax.set(title=f"{indicator}: too few pairs")
            continue
        rho, _ = spearmanr(past, future)
        ax.scatter(past, future, s=4, alpha=0.3, color="tab:blue")
        ax.axhline(0, color="grey", linewidth=0.8)
        ax.axvline(0, color="grey", linewidth=0.8)
        ax.set_xlim(*np.percentile(past, clip))
        ax.set_ylim(*np.percentile(future, clip))
        ax.set(title=f"{indicator}: rho = {rho:+.2f} ({len(past)} pairs)",
               xlabel="change over the past 12 months", ylabel="change over the next 12 months")
    fig.suptitle("Does the past change predict the next one? (rho > 0 momentum, < 0 reversion, ~0 none)")
    fig.tight_layout()
    return fig, len(indicators)


# ---------- output ----------

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
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(path)
    return paths


E1_THRESHOLDS = {"cet1_ratio": 0.07, "tier1_ratio": 0.085, "total_capital_ratio": 0.105}


def period_bands(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> dict:
    """Per indicator: (periods, p25, median, p75) across banks, computed once for all bank pages."""
    bands = {}
    for indicator in indicators:
        by_period = defaultdict(list)
        for r in rows:
            if r[indicator] is not None:
                by_period[r["period"]].append(r[indicator])
        periods = sorted(by_period)
        p25, p50, p75 = ([np.percentile(by_period[p], q) for p in periods] for q in (25, 50, 75))
        bands[indicator] = (periods, p25, p50, p75)
    return bands


def bank_page_figure(bank_rows: list[dict], bands: dict, bank_id: int,
                     indicators: tuple[str, ...] = DEFAULT_INDICATORS):
    """One page for one bank: each indicator over time against the median and 25-75% band of all banks."""
    bank_rows = sorted(bank_rows, key=lambda r: r["period"])
    columns = 2
    lines = (len(indicators) + 1) // columns
    fig, axes = plt.subplots(lines, columns, figsize=(12, 2.4 * lines), sharex=True)
    legend = {}
    for ax, indicator in zip(axes.flat, indicators):
        periods, p25, p50, p75 = bands[indicator]
        legend["25-75% of banks"] = ax.fill_between(periods, p25, p75, color="grey", alpha=0.25)
        legend["median bank"], = ax.plot(periods, p50, color="grey", linestyle="--", linewidth=1)
        points = [(r["period"], r[indicator]) for r in bank_rows if r[indicator] is not None]
        if points:
            xs, ys = zip(*points)
            legend[f"bank {bank_id}"], = ax.plot(xs, ys, color="tab:blue", marker="o", markersize=3)
        if indicator in E1_THRESHOLDS:
            legend["E1 threshold"] = ax.axhline(E1_THRESHOLDS[indicator], color="tab:red", linestyle=":", linewidth=1)
        if indicator == "npl_ratio":
            ax.axvline(NPL_BREAK, color="tab:red", linestyle="--", linewidth=0.8)
        ax.set_title(f"{indicator} ({len(points)} values)", fontsize=9)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.3)
    for ax in list(axes.flat)[len(indicators):]:
        ax.set_visible(False)
    first, last = bank_rows[0]["period"], bank_rows[-1]["period"]
    specialist = " (specialist)" if bank_rows[0]["is_specialist"] else ""
    fig.suptitle(f"Bank {bank_id}{specialist}: {len(bank_rows)} periods, {first} to {last}")
    fig.legend(legend.values(), legend.keys(), loc="lower center", ncol=len(legend), fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    return fig


def write_per_bank(rows: list[dict], path: str, min_periods: int = 1,
                   indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> int:
    """All banks: one PDF page each (path ends in .pdf) or one PNG each in a folder. Returns number of banks."""
    from matplotlib.backends.backend_pdf import PdfPages
    bands = period_bands(rows, indicators)
    by_bank = defaultdict(list)
    for r in rows:
        by_bank[r["bank_id"]].append(r)
    banks = sorted(bank for bank, bank_rows in by_bank.items() if len(bank_rows) >= min_periods)
    if path.endswith(".pdf"):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with PdfPages(path) as pdf:
            for bank in banks:
                fig = bank_page_figure(by_bank[bank], bands, bank, indicators)
                pdf.savefig(fig)
                plt.close(fig)
    else:
        os.makedirs(path, exist_ok=True)
        for bank in banks:
            fig = bank_page_figure(by_bank[bank], bands, bank, indicators)
            fig.savefig(os.path.join(path, f"bank_{bank}.png"), dpi=120)
            plt.close(fig)
    return len(banks)
