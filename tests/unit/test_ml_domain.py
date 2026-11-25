"""Unit tests for pure ML domain metrics."""
import numpy as np


# ---------------------------------------------------------------------------
# domain/metrics.py
# ---------------------------------------------------------------------------
from app.modules.eba_ml.domain.metrics import classification_metrics


def test_classification_metrics_perfect():
    actual = np.array([1, 0, 1, 0])
    scores = np.array([0.9, 0.1, 0.8, 0.2])
    result = classification_metrics(actual, scores)
    assert result["pr_auc"] == 1.0
    assert result["roc_auc"] == 1.0


def test_classification_metrics_no_positives_roc_none():
    actual = np.array([0, 0, 0])
    scores = np.array([0.1, 0.5, 0.9])
    result = classification_metrics(actual, scores)
    assert result["roc_auc"] is None
