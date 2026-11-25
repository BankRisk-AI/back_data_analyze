"""Pure classification metrics used when training (no application/infrastructure imports)."""
from __future__ import annotations

import numpy as np


def classification_metrics(actual, scores) -> dict:
    """Hit rate, false-alarm rate, PR-AUC and ROC-AUC at the 0.5 cut-off."""
    from sklearn.metrics import average_precision_score, roc_auc_score
    actual = np.asarray(actual, dtype=int)
    scores = np.asarray(scores, dtype=float)
    return {"hit_rate": float(((scores >= .5) & (actual == 1)).sum() / max(1, actual.sum())),
            "false_alarm_rate": float(((scores >= .5) & (actual == 0)).sum() /
                                      max(1, (actual == 0).sum())),
            "pr_auc": float(average_precision_score(actual, scores)),
            "roc_auc": float(roc_auc_score(actual, scores)) if len(set(actual)) > 1 else None}
