"""R0 and R1 benchmark alert rules on the capital ratios (thesis §3.5, Table 3.8).

R0: at least one capital ratio is below its regulatory alert level (the bank is non-compliant).
R1: at least one ratio is below (alert level + margin). Levels and margins are fractions
(0.01 = 1 pp). Pure functions: rows are dicts with cet1_ratio, tier1_ratio, total_capital_ratio.
"""
from __future__ import annotations

import numpy as np


def ratios_present(row: dict) -> bool:
    """True when the three capital ratios are all reported."""
    return (row.get("cet1_ratio") is not None and
            row.get("tier1_ratio") is not None and
            row.get("total_capital_ratio") is not None)


def compliant(row: dict, r0_levels: dict) -> bool:
    """R0-compliant: all three ratios present and at or above their alert levels (§3.5)."""
    return (ratios_present(row) and
            row["cet1_ratio"] >= r0_levels["cet1"] and
            row["tier1_ratio"] >= r0_levels["tier1"] and
            row["total_capital_ratio"] >= r0_levels["total_capital"])


def r0_alert(row: dict, r0_levels: dict) -> bool:
    """R0 alert: ratios present and at least one below its alert level."""
    return (ratios_present(row) and
            (row["cet1_ratio"] < r0_levels["cet1"] or
             row["tier1_ratio"] < r0_levels["tier1"] or
             row["total_capital_ratio"] < r0_levels["total_capital"]))


def r1_alert(row: dict, r0_levels: dict, margin: float) -> bool:
    """R1 alert: at least one ratio below (alert level + margin); False when a ratio is missing."""
    if not ratios_present(row):
        return False
    return (row["cet1_ratio"] < r0_levels["cet1"] + margin or
            row["tier1_ratio"] < r0_levels["tier1"] + margin or
            row["total_capital_ratio"] < r0_levels["total_capital"] + margin)


def choose_r1_margin(rows: list[dict], y: np.ndarray, r0_levels: dict,
                     margins_pp: list[float]) -> tuple[float, float]:
    """Margin (fraction) from the grid (percentage points) that maximises F2 on training rows.

    Returns (best_margin, best_f2); the first margin wins ties.
    """
    from sklearn.metrics import fbeta_score
    best_margin, best_f2 = 0.0, -1.0
    for margin_pp in margins_pp:
        margin = margin_pp / 100.0
        predicted = np.asarray([int(r1_alert(row, r0_levels, margin)) for row in rows])
        f2 = fbeta_score(y, predicted, beta=2.0, zero_division=0)
        if f2 > best_f2:
            best_f2, best_margin = f2, margin
    return best_margin, float(best_f2)
