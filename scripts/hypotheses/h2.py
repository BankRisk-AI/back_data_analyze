"""H2: lead time of the ML alert before an R0 capital breach (thesis §3.6, Table 3.2).

For each bank with an R0 breach: t_B = first breach period, t_A = first period before t_B whose
score reaches the frozen operating point. L = t_B - t_A in quarters (positive = ML leads).
Banks without a breach in the sample are right-censored.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from app.modules.eba_ml.domain.rules import r0_alert
from scripts.hypotheses.context import RunContext
from scripts.hypotheses.stats import wilcoxon_one_sided


def quarters_between(t_a: date, t_b: date) -> int:
    """Quarters from t_a to t_b (positive when t_b is later)."""
    return (t_b.year * 4 + (t_b.month - 1) // 3) - (t_a.year * 4 + (t_a.month - 1) // 3)


def _scores_by_key(ctx: RunContext) -> dict[str, float]:
    """OOF and final-test scores of the selected model, keyed 'bank_id:period'."""
    scores: dict[str, float] = {}
    scores.update((ctx.artifact.get("predictions") or {}).get(ctx.selected, {}))
    scores.update((ctx.artifact.get("test_predictions") or {}).get(ctx.selected, {}))
    return scores


def _rows_by_bank(ctx: RunContext) -> dict[int, list[dict]]:
    """Dataset rows grouped by bank, sorted by period."""
    by_bank: dict[int, list] = {}
    for row in ctx.rows:
        by_bank.setdefault(row["bank_id"], []).append(row)
    for bank_rows in by_bank.values():
        bank_rows.sort(key=lambda r: r["period"])
    return by_bank


def _bank_lead_time(bank_id: int, bank_rows: list[dict], breach_period: date,
                    scores: dict[str, float], threshold: float) -> dict[str, Any]:
    """Lead-time record of one bank that breaches R0 at breach_period."""
    t_b = breach_period.isoformat()
    pre = [(r["period"], scores.get(f"{bank_id}:{r['period'].isoformat()}"))
           for r in bank_rows if r["period"] < breach_period]
    pre = sorted((p, s) for p, s in pre if s is not None)
    if not pre:
        return {"bank_id": bank_id, "t_B": t_b, "status": "no_pre_breach_predictions"}
    if pre[0][1] >= threshold:
        return {"bank_id": bank_id, "t_B": t_b, "status": "censored_first_already_alerts",
                "first_pred_period": pre[0][0].isoformat()}
    alerts = [p for p, s in pre if s >= threshold]
    if not alerts:
        return {"bank_id": bank_id, "t_B": t_b, "status": "no_alert_before_breach"}
    t_a = min(alerts)
    return {"bank_id": bank_id, "t_B": t_b, "t_A": t_a.isoformat(),
            "L_quarters": quarters_between(t_a, breach_period), "status": "evaluated",
            "op_fitted_includes_breach_period": breach_period.year <= 2021}


def compute_h2(ctx: RunContext) -> dict[str, Any]:
    """H2: per-bank lead time; Wilcoxon only with enough non-zero L, else 'exploratory'."""
    scores = _scores_by_key(ctx)
    threshold = ctx.operating_point_threshold
    by_bank = _rows_by_bank(ctx)
    per_bank, right_censored = [], 0
    for bank_id, bank_rows in by_bank.items():
        breaches = [r for r in bank_rows if r0_alert(r, ctx.settings.r0_levels)]
        if not breaches:
            right_censored += 1
            continue
        per_bank.append(_bank_lead_time(bank_id, bank_rows, breaches[0]["period"],
                                        scores, threshold))
    lead = [float(b["L_quarters"]) for b in per_bank if b["status"] == "evaluated"]
    return {
        "per_bank": per_bank,
        "n_breach_banks": len(per_bank),
        "n_right_censored": right_censored,
        "right_censored_proportion": right_censored / len(by_bank) if by_bank else None,
        "n_evaluated": len(lead),
        "median_L_quarters": float(np.median(lead)) if lead else None,
        "wilcoxon": wilcoxon_one_sided([v for v in lead if v != 0], ctx.settings.min_wilcoxon_n),
        "operating_point_threshold": threshold,
        "note": ("Operating point fitted on OOF (2017-2021); breach periods within that "
                 "window are flagged in per_bank.op_fitted_includes_breach_period"),
    }
