"""H5: out-of-fold SHAP importance by feature family (thesis §3.6).

Each fold's model explains its own test rows. Families come from config/ml.yaml (`shap_families`);
a column without a family is an error. LinearExplainer for LR, TreeExplainer for RF/XGB.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.eba_ml.application.config import load_ml_config
from app.modules.eba_ml.application.dataset import folds
from app.modules.eba_ml.application.models import model_factory
from scripts.hypotheses.context import RunContext


def _base_name(column: str) -> str:
    """Feature name without its _rank / _change12m / _missing suffix."""
    return column.replace("_rank", "").replace("_change12m", "").replace("_missing", "")


def _validate_families(columns: list[str], families: dict) -> None:
    """Raise when a base feature belongs to no family."""
    known = {f for features in families.values() for f in features}
    unknown = {_base_name(c) for c in columns} - known
    if unknown:
        raise ValueError(f"H5: columns not in any shap_families entry: {sorted(unknown)}. "
                         f"Update shap_families in config/ml.yaml.")


def _group_by_family(shap_matrix: np.ndarray, columns: list[str], families: dict) -> dict:
    """Columns of the SHAP matrix per family (first matching family wins)."""
    indices: dict[str, list[int]] = {name: [] for name in families}
    for col_idx, col in enumerate(columns):
        for family, features in families.items():
            if _base_name(col) in features:
                indices[family].append(col_idx)
                break
    return {name: shap_matrix[:, idx] for name, idx in indices.items() if idx}


def _linear_shap(model, X_train, X_test, columns: list[str]) -> np.ndarray:
    """SHAP of a fitted LR pipeline, aligned to the dataset columns (indicators dropped)."""
    import shap
    prep = lambda X: model.named_steps["scale"].transform(model.named_steps["imputer"].transform(X))
    background = shap.sample(X_train, min(100, len(X_train)))
    explainer = shap.LinearExplainer(model.named_steps["model"], prep(background))
    values = np.asarray(explainer.shap_values(prep(X_test)))
    names_out = model.named_steps["imputer"].get_feature_names_out(np.asarray(columns))
    col_to_idx = {col: j for j, col in enumerate(columns)}
    aligned = np.zeros((values.shape[0], len(columns)))
    for i, name in enumerate(names_out):
        if i < values.shape[1] and name in col_to_idx:
            aligned[:, col_to_idx[name]] = values[:, i]
    return aligned


def _tree_shap(model, X_test, n_base: int) -> np.ndarray:
    """SHAP of a fitted tree model for the positive class."""
    import shap
    values = shap.TreeExplainer(model)(X_test).values
    if isinstance(values, list):
        values = values[-1]
    elif values.ndim == 3:
        values = values[:, :, 1]
    return np.asarray(values)[:, :n_base]


def _best_params(ctx: RunContext) -> dict:
    """Search parameters of the selected model with the best mean PR-AUC."""
    search = ctx.artifact.get("search", {})
    return max(search.get(ctx.selected, [{"mean_pr_auc": 0, "parameters": {}}]),
               key=lambda x: x["mean_pr_auc"])["parameters"]


def _oof_shap(ctx: RunContext) -> tuple[list[np.ndarray], list[int]]:
    """Per-fold SHAP matrices and, for LR, the non-zero coefficient count per fold."""
    X, y, columns = ctx.dataset["X"], ctx.y, ctx.dataset["columns"]
    params = _best_params(ctx)
    matrices, nonzero = [], []
    for train_idx, test_idx in folds(ctx.rows):
        train_valid = train_idx[y[train_idx] >= 0]
        test_valid = test_idx[y[test_idx] >= 0]
        if not len(train_valid) or not len(test_valid):
            continue
        positives = int(y[train_valid].sum())
        weight = (len(train_valid) - positives) / max(1, positives)
        model = model_factory(ctx.selected, params, weight, space=ctx.space)
        model.fit(X[train_valid], y[train_valid])
        if ctx.selected == "LR":
            nonzero.append(int(np.count_nonzero(model.named_steps["model"].coef_.ravel())))
            matrices.append(_linear_shap(model, X[train_valid], X[test_valid], columns))
        else:
            matrices.append(_tree_shap(model, X[test_valid], len(columns)))
    return matrices, nonzero


def compute_h5(ctx: RunContext) -> dict[str, Any]:
    """H5: mean |SHAP| per family; supported if Capital and Earnings rank 1-2."""
    cfg = load_ml_config()
    families, sensitivity = cfg.get("shap_families", {}), cfg.get("shap_sensitivity_groups", {})
    columns = ctx.dataset["columns"]
    _validate_families(columns, families)

    matrices, nonzero = _oof_shap(ctx)
    if not matrices:
        return {"status": "no_valid_folds"}
    shap_matrix = np.vstack(matrices)
    grouped = _group_by_family(shap_matrix, columns, families)
    primary = {name: float(np.mean(np.abs(v))) for name, v in grouped.items()}
    ranks = [n for n, _ in sorted(primary.items(), key=lambda x: -x[1])]
    result: dict[str, Any] = {
        "status": "computed",
        "primary": primary,
        "sensitivity": {g: sum(primary.get(f, 0) for f in subs) for g, subs in sensitivity.items()},
        "capital_earnings_rank_1_2": {"Capital", "Earnings"}.issubset(set(ranks[:2])),
        "n_explained_rows": int(shap_matrix.shape[0]),
        "indicator_columns": "dropped from family sums (not assigned to any base feature)",
    }
    if nonzero:
        result["lr_nonzero_per_fold"] = nonzero
    return result
