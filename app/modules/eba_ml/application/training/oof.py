"""Out-of-fold refitting: build OOF predictions and fold metrics (§3.5).

Refits each model on each fold's training split (with correct class weight)
and records per-fold PR-AUC, ROC-AUC, Brier score, and optionally SMOTE comparison.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.models import model_factory

FoldDiagnostic = Callable[..., dict[str, Any] | None]


def refit_folds(
    dataset: dict[str, Any],
    y: np.ndarray,
    algorithm_names: tuple[str, ...],
    selected_params: dict[str, dict],
    space: str,
    seed: int,
    wall_clock_started: float,
    wall_clock_hours: float,
    logger,
    fold_diagnostic: FoldDiagnostic | None = None,
) -> tuple[dict, list, list]:
    """Refit each model on each fold; return (predictions, fold_metrics, diagnostics).

    predictions: {model_name: {"bank_id:period": float}}.
    fold_diagnostic: optional thesis hook called per fitted fold model as
    (X_train, y_train, X_test, y_test, model, fold_number, model_name, seed) -> dict | None;
    non-None results are collected in `diagnostics` (the SMOTE comparison, scripts/ml).
    """
    predictions: dict[str, dict[str, float]] = {}
    fold_metrics: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for fold_number, (train_idx, test_idx) in enumerate(folds(dataset["rows"]), 1):
        if not len(test_idx) or not len(train_idx):
            continue
        if len(np.unique(y[train_idx])) < 2 or len(np.unique(y[test_idx])) < 2:
            continue
        for name in algorithm_names:
            if time.monotonic() - wall_clock_started > wall_clock_hours * 3600:
                raise TimeoutError("ML search exceeded wall-clock limit")
            positives = int(y[train_idx].sum())
            weight = (len(train_idx) - positives) / positives if positives else 1.0
            model = model_factory(name, selected_params[name], weight, space=space)
            model.fit(dataset["X"][train_idx], y[train_idx])
            probability = model.predict_proba(dataset["X"][test_idx])[:, 1]
            fold_metrics.append({
                "fold": fold_number,
                "model": name,
                "pr_auc": float(average_precision_score(y[test_idx], probability)),
                "roc_auc": (float(roc_auc_score(y[test_idx], probability))
                            if len(set(y[test_idx])) > 1 else None),
                "brier": float(brier_score_loss(y[test_idx], probability)),
            })
            predictions.setdefault(name, {}).update({
                f"{dataset['rows'][i]['bank_id']}:{dataset['rows'][i]['period'].isoformat()}": float(p)
                for i, p in zip(test_idx, probability)
            })
            if fold_diagnostic and (extra := fold_diagnostic(
                    dataset["X"][train_idx], y[train_idx], dataset["X"][test_idx],
                    y[test_idx], model, fold_number, name, seed)):
                diagnostics.append(extra)

    return predictions, fold_metrics, diagnostics
