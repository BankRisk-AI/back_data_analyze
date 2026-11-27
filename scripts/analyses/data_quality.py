"""Data quality and relations between indicators: missing values per period, correlations."""
from __future__ import annotations

from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np

from scripts.analyses.draw_graph import DEFAULT_INDICATORS, QUARTERLY_FROM

SHORT = {"cet1_ratio": "cet1", "tier1_ratio": "tier1", "total_capital_ratio": "tcr", "leverage_ratio": "lev",
         "npl_ratio": "npl", "stage2_share": "stage2", "roe_annualised": "roe", "loan_growth_yoy": "loans"}


def _short(indicator: str) -> str:
    return SHORT.get(indicator, indicator[:8])


# ---------- 7. missing values ----------

def _missing_share(rows: list[dict], indicator: str) -> float:
    """Share of rows without a value for this indicator."""
    return sum(1 for r in rows if r[indicator] is None) / len(rows) if rows else float("nan")


def missing_by_period(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS):
    """(periods, matrix) where matrix[i][j] = share of banks in period j without indicator i."""
    by_period = defaultdict(list)
    for r in rows:
        by_period[r["period"]].append(r)
    periods = sorted(by_period)
    matrix = np.array([[_missing_share(by_period[p], indicator) for p in periods] for indicator in indicators])
    return periods, matrix


def print_missing(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> None:
    """Missing share overall, before and after the switch to quarterly data, and the first period with values."""
    before = [r for r in rows if r["period"] < QUARTERLY_FROM]
    after = [r for r in rows if r["period"] >= QUARTERLY_FROM]
    print("\nindicator              missing  before 2018-09  from 2018-09  first period with values")
    for indicator in indicators:
        present = [r["period"] for r in rows if r[indicator] is not None]
        first = min(present) if present else "-"
        print(f"{indicator:22s} {_missing_share(rows, indicator):7.0%} {_missing_share(before, indicator):15.0%} "
              f"{_missing_share(after, indicator):13.0%}  {first}")


def missing_figure(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS):
    """Heat map indicator x period: % of banks without a value. Returns (figure, matrix shape)."""
    periods, matrix = missing_by_period(rows, indicators)
    fig, ax = plt.subplots(figsize=(14, 0.5 * len(indicators) + 2))
    image = ax.imshow(matrix, aspect="auto", cmap="Reds", vmin=0, vmax=1)
    ax.set_yticks(range(len(indicators)))
    ax.set_yticklabels(indicators, fontsize=8)
    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels([str(p)[:7] for p in periods], rotation=90, fontsize=7)
    for y in range(len(indicators)):
        for x in range(len(periods)):
            share = matrix[y, x]
            if share >= 0.005:
                ax.text(x, y, f"{share * 100:.0f}", ha="center", va="center", fontsize=6,
                        color="white" if share > 0.5 else "black")
    ax.axvline(sum(1 for p in periods if p < QUARTERLY_FROM) - 0.5, color="black", linestyle=":", linewidth=1)
    fig.colorbar(image, ax=ax, fraction=0.02, label="share of banks without a value")
    ax.set_title("Missing values per indicator and period (% of banks in that period; dotted line = quarterly from)")
    fig.tight_layout()
    return fig, matrix.shape


# ---------- 8. correlations ----------

def _bank_demeaned(rows: list[dict], indicators: tuple[str, ...]) -> list[dict]:
    """Each value minus the bank's own mean of that indicator: only the movement over time is left."""
    values = defaultdict(list)
    for r in rows:
        for indicator in indicators:
            if r[indicator] is not None:
                values[(r["bank_id"], indicator)].append(r[indicator])
    means = {key: np.mean(vs) for key, vs in values.items()}
    return [{indicator: (r[indicator] - means[(r["bank_id"], indicator)] if r[indicator] is not None else None)
             for indicator in indicators} for r in rows]


def correlation_matrix(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS,
                       within_bank: bool = False) -> np.ndarray:
    """Spearman correlations on pairwise complete rows; within_bank removes each bank's own mean first."""
    from scipy.stats import spearmanr
    data = _bank_demeaned(rows, indicators) if within_bank else rows
    n = len(indicators)
    matrix = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            both = [(r[indicators[i]], r[indicators[j]]) for r in data
                    if r[indicators[i]] is not None and r[indicators[j]] is not None]
            rho = spearmanr(*zip(*both))[0] if len(both) >= 30 else np.nan
            matrix[i, j] = matrix[j, i] = rho
    return matrix


def print_correlations(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS,
                       strong: float = 0.7) -> None:
    """Both matrices (levels across banks, movement within banks) and the strongly related pairs."""
    names = [_short(i) for i in indicators]
    for label, within in (("levels (banks compared with each other)", False),
                          ("within bank (movement over time, bank mean removed)", True)):
        matrix = correlation_matrix(rows, indicators, within)
        print(f"\nSpearman correlation, {label}")
        print(" " * 8 + "".join(f"{name:>8s}" for name in names))
        for name, line in zip(names, matrix):
            print(f"{name:8s}" + "".join(f"{v:8.2f}" for v in line))
        pairs = [(names[i], names[j], matrix[i, j]) for i in range(len(names)) for j in range(i + 1, len(names))
                 if abs(matrix[i, j]) >= strong]
        print("strong pairs (|rho| >= %.1f): " % strong + (", ".join(f"{a}-{b} {v:+.2f}" for a, b, v in pairs) or "none"))


def correlation_figure(rows: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS):
    """Two heat maps side by side: levels and within-bank movement. Returns (figure, number of indicators)."""
    names = [_short(i) for i in indicators]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for ax, (title, within) in zip(axes, (("Levels: banks compared with each other", False),
                                          ("Within bank: movement over time", True))):
        matrix = correlation_matrix(rows, indicators, within)
        image = ax.imshow(matrix, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=8)
        for y in range(len(names)):
            for x in range(len(names)):
                if not np.isnan(matrix[y, x]):
                    ax.text(x, y, f"{matrix[y, x]:.2f}", ha="center", va="center", fontsize=7,
                            color="white" if abs(matrix[y, x]) > 0.6 else "black")
        ax.set_title(title, fontsize=10)
    fig.colorbar(image, ax=axes, fraction=0.025, label="Spearman rho")
    fig.suptitle("Correlations between indicators")
    return fig, len(indicators)