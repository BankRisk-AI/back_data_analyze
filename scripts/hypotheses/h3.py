"""H3: do trend features help? Levels-only model vs levels+trends (thesis §3.6).

The selected algorithm is re-searched on level columns only (no `_rank`, `_change12m`) with the
same folds and seed, then compared with the main OOF scores by bootstrap and fold-wise Wilcoxon.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.models import _search_configs, model_factory
from scripts.hypotheses.context import RunContext
from scripts.hypotheses.stats import bootstrap_metric_difference, wilcoxon_one_sided


def _fit_fold(X, y, train_idx, test_idx, algorithm: str, params: dict, space: str) -> np.ndarray:
    """Fit on one fold's training rows (class-weighted) and score its test rows."""
    weight = (len(train_idx) - y[train_idx].sum()) / max(1, y[train_idx].sum())
    model = model_factory(algorithm, params, weight, space=space)
    model.fit(X[train_idx], y[train_idx])
    return model.predict_proba(X[test_idx])[:, 1]


def _search_level_configs(X_level, y, rows, algorithm: str, configs: list, space: str) -> dict:
    """Return the config with the best mean fold PR-AUC on level columns."""
    best_mean_pr = -1.0
    best_params = configs[0] if configs else {}
    for params in configs:
        fold_prs = [
            average_precision_score(y[test_idx], _fit_fold(X_level, y, train_idx, test_idx,
                                                           algorithm, params, space))
            for train_idx, test_idx in folds(rows) if y[test_idx].any()]
        if fold_prs and np.mean(fold_prs) > best_mean_pr:
            best_mean_pr = float(np.mean(fold_prs))
            best_params = params
    return best_params


def _refit_level_folds(X_level, y, rows, keys, algorithm: str, params: dict, space: str):
    """Refit the levels-only model per fold; return (OOF scores by key, PR-AUC by fold)."""
    level_pred: dict[str, float] = {}
    level_fold: dict[int, float] = {}
    for fold_no, (train_idx, test_idx) in enumerate(folds(rows), 1):
        if len(test_idx) == 0 or not y[test_idx].any():
            continue
        scores = _fit_fold(X_level, y, train_idx, test_idx, algorithm, params, space)
        level_pred.update({keys[i]: float(v) for i, v in zip(test_idx, scores)})
        level_fold[fold_no] = float(average_precision_score(y[test_idx], scores))
    return level_pred, level_fold


def compute_h3(ctx: RunContext) -> dict[str, Any]:
    """H3: dPR of (levels+trends) minus (levels only) for the selected model."""
    s, algorithm, space = ctx.settings, ctx.selected, ctx.space
    valid = ctx.y >= 0
    rows = [ctx.rows[i] for i in np.flatnonzero(valid)]
    y, keys = ctx.y[valid], ctx.keys[valid]
    level_columns = [i for i, col in enumerate(ctx.dataset["columns"])
                     if "_rank" not in col and "_change12m" not in col]
    X_level = ctx.dataset["X"][valid][:, level_columns]

    configs = _search_configs(algorithm, space)[:s.h3_budget]
    best_params = _search_level_configs(X_level, y, rows, algorithm, configs, space)
    level_pred, level_fold = _refit_level_folds(X_level, y, rows, keys, algorithm,
                                                best_params, space)

    main_scores = ctx.arrays[algorithm][valid]
    level_scores = np.asarray([level_pred.get(key, np.nan) for key in keys])
    both = np.isfinite(main_scores) & np.isfinite(level_scores)
    primary_fold = {m["fold"]: m["pr_auc"] for m in ctx.artifact.get("fold_metrics", [])
                    if m.get("model") == algorithm}
    banks = np.asarray([rows[i]["bank_id"] for i in np.flatnonzero(both)])
    return {
        "level_params": best_params,
        "dPR": bootstrap_metric_difference(y[both], main_scores[both], level_scores[both],
                                           banks, "pr", s.seed, s.replicates),
        "fold_wilcoxon": wilcoxon_one_sided(
            [primary_fold[f] - level_fold[f] for f in level_fold if f in primary_fold],
            s.min_wilcoxon_n),
    }
