"""Statistics for the hypothesis tests (thesis §3.6).

Bank-cluster bootstrap, exact one-sided Wilcoxon signed-rank test, Holm adjustment.
Pure functions: numpy/sklearn/scipy only, no database, no app imports.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

_METRICS: dict[str, Callable] = {"pr": average_precision_score, "roc": roc_auc_score}


def _bank_groups(banks: np.ndarray) -> tuple[np.ndarray, ...]:
    """Row indices of each bank (the resampling unit of the cluster bootstrap)."""
    _, inverse = np.unique(banks, return_inverse=True)
    return tuple(np.flatnonzero(inverse == i) for i in range(inverse.max() + 1))


def bootstrap_metric_difference(y, candidate, reference, banks, metric: str,
                                seed: int, replicates: int) -> dict:
    """Bank-cluster bootstrap of metric(candidate) - metric(reference) (§3.6).

    metric: "pr" (PR-AUC) or "roc" (ROC-AUC). Returns the point estimate, the 95% percentile
    interval and the one-sided p-value P(difference <= 0).
    """
    score = _METRICS[metric]
    groups = _bank_groups(banks)
    rng = np.random.default_rng(seed)
    values = np.empty(replicates)
    for draw in range(replicates):
        chosen = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate(tuple(groups[i] for i in chosen))
        values[draw] = score(y[idx], candidate[idx]) - score(y[idx], reference[idx])
    return {"estimate": float(score(y, candidate) - score(y, reference)),
            "ci95": [float(np.quantile(values, .025)), float(np.quantile(values, .975))],
            "p_one_sided": float((np.count_nonzero(values <= 0) + 1) / (replicates + 1))}


def bootstrap_recall_difference(y, selected_a, selected_b, banks, seed: int,
                                replicates: int) -> list[float]:
    """95% bank-cluster bootstrap interval of recall(a) - recall(b) (H1b)."""
    rng = np.random.default_rng(seed)
    unique_banks = np.unique(banks)
    bank_indices = {b: np.flatnonzero(banks == b) for b in unique_banks}
    positives = y == 1
    values = np.empty(replicates)
    for draw in range(replicates):
        chosen = rng.integers(0, len(unique_banks), len(unique_banks))
        idx = np.concatenate([bank_indices[unique_banks[c]] for c in chosen])
        n_pos = int(positives[idx].sum())
        values[draw] = (0.0 if n_pos == 0 else
                        float((selected_a[idx] & positives[idx]).sum()) / n_pos -
                        float((selected_b[idx] & positives[idx]).sum()) / n_pos)
    return [float(np.quantile(values, .025)), float(np.quantile(values, .975))]


def wilcoxon_one_sided(values, min_n: int) -> dict:
    """Exact one-sided Wilcoxon signed-rank test (alternative: values > 0).

    Zero differences are dropped; fewer than min_n left -> status "exploratory", no p-value.
    """
    values = np.asarray(values, dtype=float)
    values = values[values != 0]
    if len(values) < min_n:
        return {"p": None, "n": int(len(values)), "status": "exploratory"}
    from scipy.stats import wilcoxon
    return {"p": float(wilcoxon(values, alternative="greater", method="exact").pvalue),
            "n": int(len(values)), "status": "exact"}


def holm_adjust(pvalues: list[float]) -> list[float]:
    """Return Holm step-down adjusted p-values in the original order."""
    indexed = sorted(enumerate(pvalues), key=lambda item: item[1])
    adjusted = [0.0] * len(pvalues)
    running = 0.0
    for rank, (index, value) in enumerate(indexed):
        running = max(running, min(1.0, (len(pvalues) - rank) * value))
        adjusted[index] = running
    return adjusted
