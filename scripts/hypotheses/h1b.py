"""H1b: equal-alert-volume recall of the selected ML model vs rule R1 (thesis §3.6, Table 3.2).

Primary window: final test. Sensitivity: validation OOF, fixed 10%/20% alert shares.
v1.1 red-alert recall is reported as descriptive only.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.domain.rules import r1_alert
from scripts.hypotheses.context import RunContext
from scripts.hypotheses.stats import bootstrap_recall_difference


def _window_mask(ctx: RunContext, years: tuple[int, int]) -> np.ndarray:
    """Rows inside the inclusive year window that belong to the prediction sample."""
    return np.asarray([years[0] <= r["period"].year <= years[1] and ctx.y[i] >= 0
                       for i, r in enumerate(ctx.rows)], dtype=bool)


def _scores_for(ctx: RunContext, idx: np.ndarray, predictions: dict) -> np.ndarray:
    """ML scores of the rows idx (NaN when the row has no prediction)."""
    return np.asarray([predictions.get(f"{ctx.rows[i]['bank_id']}:{ctx.rows[i]['period'].isoformat()}",
                                       np.nan) for i in idx], dtype=float)


def _equal_volume_selection(periods, scores, r1_alerts) -> np.ndarray:
    """Per period, flag the top-scored rows, as many as R1 flags in that period."""
    selected = np.zeros(len(scores), dtype=bool)
    for period in np.unique(periods):
        idx = np.flatnonzero(periods == period)
        count = int(r1_alerts[idx].sum())
        if count and np.isfinite(scores[idx]).any():
            finite = idx[np.isfinite(scores[idx])]
            selected[finite[np.argsort(-scores[finite], kind="stable")][:count]] = True
    return selected


def _recall_comparison(ctx: RunContext, mask: np.ndarray, predictions: dict,
                       seed: int, window: str) -> dict[str, Any]:
    """ML vs R1 recall at R1's per-period alert volume, with bootstrap CI."""
    if not mask.any():
        return {"status": "no_rows", "window": window}
    idx = np.flatnonzero(mask)
    y = ctx.y[mask]
    n_pos = int((y == 1).sum())
    if n_pos == 0:
        return {"status": "no_positives", "window": window}
    rows = ctx.rows
    periods = np.asarray([rows[i]["period"].isoformat() for i in idx])
    r1 = np.asarray([int(r1_alert(rows[i], ctx.r0_levels, ctx.r1_margin)) for i in idx])
    banks = np.asarray([rows[i]["bank_id"] for i in idx])

    ml_sel = _equal_volume_selection(periods, _scores_for(ctx, idx, predictions), r1)
    pos = y == 1
    r1_recall = float((r1.astype(bool) & pos).sum()) / n_pos
    ml_recall = float((ml_sel & pos).sum()) / n_pos
    ci = bootstrap_recall_difference(y, ml_sel, r1.astype(bool), banks, seed,
                                     ctx.settings.replicates)
    return {"window": window, "n_rows": int(mask.sum()), "n_positives": n_pos,
            "r1_recall": r1_recall, "ml_recall": ml_recall,
            "recall_diff": ml_recall - r1_recall, "ci95": ci, "supported": ci[0] > 0}


def _r1_headroom(row: dict, r0_levels: dict) -> float:
    """Smallest headroom over the capital ratios (negative = already breaching)."""
    cet1, t1, tc = row.get("cet1_ratio"), row.get("tier1_ratio"), row.get("total_capital_ratio")
    if cet1 is None or t1 is None or tc is None:
        return float("inf")
    return min(cet1 - r0_levels["cet1"], t1 - r0_levels["tier1"],
               tc - r0_levels["total_capital"])


def _top_k(order_key: np.ndarray, k: int, candidates: np.ndarray) -> np.ndarray:
    """Boolean selection of the k first candidates when sorted by order_key ascending."""
    selected = np.zeros(len(order_key), dtype=bool)
    selected[candidates[np.argsort(order_key[candidates], kind="stable")][:k]] = True
    return selected


def _fixed_share_row(y, ml_scores, headroom, banks, share_pct, seed, replicates) -> dict:
    """ML vs headroom-ranked R1 recall when both flag share_pct% of the rows."""
    pos = y == 1
    n_pos = int(pos.sum())
    k = max(1, round(len(ml_scores) * share_pct / 100))
    ml_sel = _top_k(-ml_scores, k, np.flatnonzero(np.isfinite(ml_scores)))
    r1_sel = _top_k(headroom, k, np.arange(len(headroom)))
    ml_recall = float((ml_sel & pos).sum()) / n_pos
    r1_recall = float((r1_sel & pos).sum()) / n_pos
    return {"k_alerts": k, "ml_recall": ml_recall, "r1_recall": r1_recall,
            "recall_diff": ml_recall - r1_recall,
            "ci95": bootstrap_recall_difference(y, ml_sel, r1_sel, banks, seed + share_pct,
                                                replicates)}


def _fixed_share_sensitivity(ctx: RunContext, mask: np.ndarray, predictions: dict) -> dict:
    """Post-hoc recall at fixed alert shares; R1 ranks rows by smallest headroom."""
    if not mask.any():
        return {"status": "no_rows"}
    idx = np.flatnonzero(mask)
    y = ctx.y[mask]
    if not (y == 1).any():
        return {"status": "no_positives"}
    rows, s = ctx.rows, ctx.settings
    r1 = np.asarray([int(r1_alert(rows[i], ctx.r0_levels, ctx.r1_margin)) for i in idx])
    headroom = np.asarray([_r1_headroom(rows[i], ctx.r0_levels) for i in idx], dtype=float)
    ml_scores = _scores_for(ctx, idx, predictions)
    banks = np.asarray([rows[i]["bank_id"] for i in idx])
    result: dict[str, Any] = {"r1_alert_share_pct": float(100 * r1.sum() / len(r1))}
    for share in s.fixed_alert_shares_pct:
        result[f"share_{share}pct"] = _fixed_share_row(
            y, ml_scores, headroom, banks, share, s.seed, s.replicates)
    return result


def _v11_red_alerts(ctx: RunContext) -> set:
    """(bank_id, period_end) pairs with a red alert of the comparator v1.1 profile."""
    with ctx.conn.cursor() as cur:
        cur.execute("""
            SELECT a.bank_id, v.period_end
            FROM alert a
            JOIN dataset_version v USING(version_id)
            WHERE a.level = 'red'
              AND v.is_active
              AND a.profile_sha256 = %s
            ORDER BY v.period_end, a.bank_id
        """, (ctx.settings.comparator_profile_sha,))
        return {(bid, p) for bid, p in cur.fetchall()}


def _v11_recall(ctx: RunContext) -> dict[str, Any]:
    """Recall of the v1.1 red alerts on the test window (descriptive, volume not matched)."""
    try:
        red = _v11_red_alerts(ctx)
    except Exception as exc:
        return {"status": f"query_failed: {exc}"}
    lo, hi = ctx.settings.test_years
    test_idx = np.asarray([i for i, r in enumerate(ctx.rows) if lo <= r["period"].year <= hi])
    if not len(test_idx):
        return {"status": "no_test_rows"}
    pos = ctx.y[test_idx] == 1
    n_pos = int(pos.sum())
    if n_pos == 0:
        return {"status": "no_positives"}
    v11 = np.asarray([int((ctx.rows[i]["bank_id"], ctx.rows[i]["period"]) in red)
                      for i in test_idx], dtype=int)
    return {"n_alerts": int(v11.sum()),
            "recall": float((v11.astype(bool) & pos).sum()) / n_pos,
            "note": "descriptive only; v1.1 alert volume not matched to ML"}


def compute_h1b(ctx: RunContext) -> dict[str, Any]:
    """H1b: ML recall minus R1 recall at equal alert volume; supported if CI lower bound > 0."""
    s = ctx.settings
    test_preds = (ctx.artifact.get("test_predictions") or {}).get(ctx.selected, {})
    test_mask = _window_mask(ctx, s.test_years)
    result = _recall_comparison(ctx, test_mask, test_preds, s.seed, "final_test")

    oof_preds = dict((ctx.artifact.get("predictions") or {}).get(ctx.selected, {}))
    result["sensitivity_oof"] = _recall_comparison(
        ctx, _window_mask(ctx, s.validation_years), oof_preds,
        s.seed + s.validation_seed_offset, "validation_oof")
    result["v1_1_descriptive"] = _v11_recall(ctx)
    result["fixed_share_sensitivity"] = _fixed_share_sensitivity(ctx, test_mask, test_preds)
    return result
