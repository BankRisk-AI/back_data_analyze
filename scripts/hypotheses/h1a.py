"""H1a: do RF / XGB beat LR? Pairwise comparison on pooled OOF scores (thesis §3.6, Table 3.6).

Bank-cluster bootstrap of dPR-AUC and dROC-AUC, Holm adjustment of the dPR p-values,
fold-wise Wilcoxon on the per-fold PR-AUC differences.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from scripts.hypotheses.context import RunContext
from scripts.hypotheses.stats import bootstrap_metric_difference, holm_adjust, wilcoxon_one_sided

CHALLENGERS = ("RF", "XGB")


def _bootstrap_pair(ctx: RunContext, name: str, mask: np.ndarray) -> dict[str, Any]:
    """dPR and dROC of challenger `name` against LR on the rows in mask."""
    banks = np.asarray([ctx.rows[i]["bank_id"] for i in np.flatnonzero(mask)])
    s = ctx.settings
    args = (ctx.y[mask], ctx.arrays[name][mask], ctx.arrays["LR"][mask], banks)
    return {"dPR": bootstrap_metric_difference(*args, "pr", s.seed, s.replicates),
            "dROC": bootstrap_metric_difference(*args, "roc", s.seed + 1, s.replicates)}


def _fold_pr_auc(ctx: RunContext) -> dict[int, dict[str, float]]:
    """{fold: {model: PR-AUC}} from the artefact's fold metrics."""
    fold: dict[int, dict] = {}
    for item in ctx.artifact.get("fold_metrics", []):
        fold.setdefault(item["fold"], {})[item["model"]] = item["pr_auc"]
    return fold


def compute_h1a(ctx: RunContext) -> dict[str, Any]:
    """H1a: RF_vs_LR and XGB_vs_LR with Holm-adjusted dPR p-values and fold Wilcoxon."""
    result: dict[str, Any] = {}
    common = ctx.valid.get("LR", np.zeros(len(ctx.y), bool))
    for name in CHALLENGERS:
        mask = common & ctx.valid.get(name, np.zeros(len(ctx.y), bool))
        if mask.any():
            result[f"{name}_vs_LR"] = _bootstrap_pair(ctx, name, mask)

    present = [f"{n}_vs_LR" for n in CHALLENGERS if f"{n}_vs_LR" in result]
    adjusted = holm_adjust([result[k]["dPR"]["p_one_sided"] for k in present])
    for key, p_holm in zip(present, adjusted):
        result[key]["dPR"]["p_holm"] = p_holm

    fold = _fold_pr_auc(ctx)
    for name in CHALLENGERS:
        differences = [v[name] - v["LR"] for v in fold.values() if name in v and "LR" in v]
        result.setdefault(f"{name}_vs_LR", {})["fold_wilcoxon"] = wilcoxon_one_sided(
            differences, ctx.settings.min_wilcoxon_n)
    return result
