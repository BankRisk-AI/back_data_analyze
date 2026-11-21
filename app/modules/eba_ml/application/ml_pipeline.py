"""Deterministic Stage 5b dataset and model evaluation pipeline."""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

FEATURES = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
)
TARGETS = ("T1", "T2", "T3", "T4", "T5", "T5_noT1")
SEED = 20261121


SEARCH_CONFIGURATIONS = 60


def model_factory(algorithm=None, params=None, pos_weight=None):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier
    params = params or {}
    models = {
        "LR": Pipeline([("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                        ("model", LogisticRegression(max_iter=2000,
                         class_weight="balanced", solver=params.get("solver", "liblinear"),
                         penalty=params.get("penalty", "l2"), C=params.get("C", 1.0)))]),
        "RF": RandomForestClassifier(n_estimators=params.get("n_estimators", 150), class_weight="balanced",
                                     random_state=SEED, n_jobs=1,
                                     max_depth=params.get("max_depth"),
                                     min_samples_leaf=params.get("min_samples_leaf", 1),
                                     max_features=params.get("max_features", "sqrt"),
                                     oob_score=True, bootstrap=True),
        "XGB": XGBClassifier(n_estimators=params.get("n_estimators", 100),
                             max_depth=params.get("max_depth", 3),
                             learning_rate=params.get("learning_rate", .05),
                             min_child_weight=params.get("min_child_weight", 1),
                             subsample=params.get("subsample", .8),
                             colsample_bytree=params.get("colsample_bytree", .8),
                             eval_metric="logloss", scale_pos_weight=pos_weight or 1.0,
                             random_state=SEED, n_jobs=1, verbosity=0),
    }
    return models if algorithm is None else models[algorithm]


def _search_configs(name: str) -> list[dict[str, Any]]:
    rng = random.Random(SEED + sum(ord(char) for char in name))
    if name == "LR":
        space = {"penalty": ["l1", "l2"], "solver": ["liblinear"],
                 "C": [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100]}
    elif name == "RF":
        space = {"max_depth": [None, 3, 5, 8, 12, 20],
                 "min_samples_leaf": [1, 2, 4, 8, 12],
                 "max_features": ["sqrt", "log2", 0.5, 1.0]}
    else:
        space = {"n_estimators": [100], "max_depth": [2, 3, 4, 5],
                 "learning_rate": [.02, .05, .1, .2],
                 "min_child_weight": [1, 3, 6], "subsample": [.7, .85, 1.0],
                 "colsample_bytree": [.7, .85, 1.0]}
    configs = []
    for _ in range(SEARCH_CONFIGURATIONS):
        configs.append({key: rng.choice(values) for key, values in space.items()})
    return configs


def _classification_metrics(actual, scores):
    from sklearn.metrics import average_precision_score, roc_auc_score
    actual = np.asarray(actual, dtype=int)
    scores = np.asarray(scores, dtype=float)
    return {"hit_rate": float(((scores >= .5) & (actual == 1)).sum() / max(1, actual.sum())),
            "false_alarm_rate": float(((scores >= .5) & (actual == 0)).sum() /
                                      max(1, (actual == 0).sum())),
            "pr_auc": float(average_precision_score(actual, scores)),
            "roc_auc": float(roc_auc_score(actual, scores)) if len(set(actual)) > 1 else None}


def _cluster_bootstrap(actual, candidate, reference, banks, seed=SEED, n=2000):
    from sklearn.metrics import average_precision_score
    rng = np.random.default_rng(seed)
    groups = np.unique(banks)
    values = []
    for _ in range(n):
        chosen = rng.choice(groups, len(groups), replace=True)
        mask = np.concatenate([np.flatnonzero(banks == bank) for bank in chosen])
        values.append(average_precision_score(actual[mask], candidate[mask]) -
                      average_precision_score(actual[mask], reference[mask]))
    return [float(np.quantile(values, .025)), float(np.quantile(values, .975))]


def fit_final_model(conn, algorithm: str, target: str = "T5",
                    grid: str = "semiannual", robustness: bool = True):
    dataset = build_dataset(conn, grid, robustness)
    y = np.asarray([(row["bank_id"], row["period"]) in dataset["targets"][target]
                    for row in dataset["rows"]], dtype=int)
    train_idx = np.asarray([i for i, row in enumerate(dataset["rows"])
                            if row["period"].year <= 2020])
    model = model_factory()[algorithm]
    model.fit(dataset["X"][train_idx], y[train_idx])
    return model, dataset, y, train_idx


def holm_adjust(pvalues: list[float]) -> list[float]:
    """Return Holm step-down adjusted p-values in the original order."""
    indexed = sorted(enumerate(pvalues), key=lambda item: item[1])
    adjusted = [0.0] * len(pvalues)
    running = 0.0
    for rank, (index, value) in enumerate(indexed):
        running = max(running, min(1.0, (len(pvalues) - rank) * value))
        adjusted[index] = running
    return adjusted


def equal_alert_volume_recall(periods, labels, scores, benchmark):
    """Recall when each period receives exactly the benchmark's alert volume."""
    periods = np.asarray(periods)
    labels = np.asarray(labels, dtype=int)
    scores = np.asarray(scores, dtype=float)
    benchmark = np.asarray(benchmark, dtype=bool)
    selected = np.zeros(len(labels), dtype=bool)
    for period in np.unique(periods):
        indices = np.flatnonzero(periods == period)
        count = int(benchmark[indices].sum())
        if count:
            order = indices[np.argsort(-scores[indices], kind="stable")[:count]]
            selected[order] = True
    positives = labels == 1
    return float((selected & positives).sum() / positives.sum()) if positives.any() else 0.0


def lead_time_quarters(event_date, observations, ml_alerts, rule_alerts):
    """Compute t_rule - t_ml in quarters, including first-observation censoring."""
    before = sorted((p for p in observations if p < event_date))
    if not before:
        return None

    def first_run(alerts):
        eligible = [p for p in before if p in alerts]
        if not eligible:
            return None, False
        start = eligible[0]
        first = before[0]
        return start, start == first

    ml_start, ml_censored = first_run(set(ml_alerts))
    rule_start, rule_censored = first_run(set(rule_alerts))
    if ml_start is None or rule_start is None:
        return {"lead_quarters": None, "censored": ml_censored or rule_censored}
    return {"lead_quarters": (rule_start.year * 4 + (rule_start.month - 1) // 3) -
            (ml_start.year * 4 + (ml_start.month - 1) // 3),
            "censored": ml_censored or rule_censored}


def _months(date_value: date, count: int) -> date:
    absolute = date_value.year * 12 + date_value.month - 1 + count
    year, month = divmod(absolute, 12)
    return date(year, month + 1, date_value.day)


def _approved_ids(conn) -> dict[str, set[int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT bank_id,trim(lei) FROM bank")
        bank_ids = {lei: bank_id for bank_id, lei in cur.fetchall()}
    config = yaml.safe_load(Path("config/bank_crosswalk.yaml").read_text()) or {}
    result: dict[str, set[int]] = {}
    for group in config.get("crosswalks", []):
        if group.get("status") != "approved":
            continue
        ids = {bank_ids[m["lei"]] for m in group.get("members", []) if m["lei"] in bank_ids}
        for member in group.get("members", []):
            result[member["lei"]] = ids
    return result


def _event_ids(conn) -> dict[str, set[int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT bank_id,trim(lei) FROM bank")
        bank_ids = {lei: bank_id for bank_id, lei in cur.fetchall()}
    result = {lei: {bank_id} for lei, bank_id in bank_ids.items()}
    result.update(_approved_ids(conn))
    return result


def _target_rows(rows: list[dict[str, Any]], conn, event_start_months: int = 3) -> dict[str, set[tuple[int, date]]]:
    catalogue = yaml.safe_load(Path("config/events.yaml").read_text()) or {}
    events = [e for e in catalogue.get("events", [])
              if e.get("set") == "primary" and e.get("status") == "included"]
    event_ids = _event_ids(conn)
    by_bank: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_bank.setdefault(row["bank_id"], []).append(row)
    result = {target: set() for target in TARGETS}
    for bank_id, bank_rows in by_bank.items():
        bank_rows.sort(key=lambda row: row["period"])
        for row in bank_rows:
            period = row["period"]
            future = [x for x in bank_rows if period < x["period"] <= _months(period, 12)]
            event = any(
                bank_id in event_ids.get(e["bank_lei"].strip(), set())
                and _months(period, event_start_months) <= date.fromisoformat(e["event_date"]) <= _months(period, 12)
                for e in events
            )
            cet1 = row["cet1_ratio"]
            t2 = cet1 is not None and cet1 >= 0.11 and any(
                x["cet1_ratio"] is not None and x["cet1_ratio"] < 0.11 for x in future)
            t3 = cet1 is not None and any(
                x["cet1_ratio"] is not None and cet1 - x["cet1_ratio"] >= 0.03 for x in future)
            t4 = any(x["roe_annualised"] is not None and x["npl_ratio"] is not None
                     and x["roe_annualised"] < 0 and x["npl_ratio"] > 0.08 for x in future)
            t4 = t4 and not (row["roe_annualised"] is not None and row["npl_ratio"] is not None
                             and row["roe_annualised"] < 0 and row["npl_ratio"] > 0.08)
            values = {"T1": event, "T2": t2, "T3": t3, "T4": t4,
                      "T5": event or t2 or t3 or t4, "T5_noT1": t2 or t3 or t4}
            for target, positive in values.items():
                if positive:
                    result[target].add((bank_id, period))
    return result


def build_dataset(conn, grid: str = "semiannual", robustness: bool = False) -> dict[str, Any]:
    if grid not in {"semiannual", "quarterly"}:
        raise ValueError("grid must be semiannual or quarterly")
    with conn.cursor() as cur:
        cur.execute("""SELECT p.bank_id,v.period_end,p.flags,
                              p.cet1_ratio,p.tier1_ratio,p.total_capital_ratio,p.leverage_ratio,
                              p.npl_ratio,p.stage2_share,p.roe_annualised,p.nace_hhi,
                              p.sovereign_hhi,p.loan_growth_qoq,p.loan_growth_yoy
                       FROM panel_row p JOIN dataset_version v USING(version_id)
                       WHERE v.is_active ORDER BY v.period_end,p.bank_id""")
        raw = cur.fetchall()
    rows = []
    for values in raw:
        bank_id, period, flags, *feature_values = values
        if any("specialist_institution" in value for value in (flags or {}).values()):
            continue
        if grid == "semiannual" and period.month not in (6, 12):
            continue
        rows.append({"bank_id": bank_id, "period": period, **dict(zip(FEATURES, feature_values))})
    by_period: dict[date, list[dict[str, Any]]] = {}
    by_bank: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_period.setdefault(row["period"], []).append(row)
        by_bank.setdefault(row["bank_id"], []).append(row)
    active_features = tuple(feature for feature in FEATURES
                            if not (robustness and feature == "loan_growth_qoq"))
    structural = {"stage2_share", "nace_hhi", "leverage_ratio", "loan_growth_qoq",
                  "cet1_ratio", "tier1_ratio", "total_capital_ratio"}
    columns = []
    for feature in active_features:
        columns += [feature, f"{feature}_rank", f"{feature}_change12m"]
        if not (robustness and feature in structural):
            columns.append(f"{feature}_missing")
    matrix = []
    for row in rows:
        values = []
        peers = [x[feature] for x in by_period[row["period"]] if x[feature] is not None]
        for feature in active_features:
            value = row[feature]
            values.append(value)
            values.append(sum(x <= value for x in peers) / len(peers) if value is not None and peers else np.nan)
            previous = next((x[feature] for x in by_bank[row["bank_id"]]
                             if x["period"] == _months(row["period"], -12)), None)
            values.append(value - previous if value is not None and previous is not None else np.nan)
            if not (robustness and feature in structural):
                values.append(0.0 if value is not None else 1.0)
        matrix.append(values)
    targets = _target_rows(rows, conn, 3)
    old_targets = _target_rows(rows, conn, 0)
    panel_hash = hashlib.sha256(json.dumps(
        [(r["bank_id"], r["period"].isoformat(), [r[f] for f in FEATURES]) for r in rows],
        default=str, sort_keys=True).encode()).hexdigest()
    return {"rows": rows, "X": np.asarray(matrix, dtype=float), "columns": columns,
            "targets": targets, "panel_hash": panel_hash, "grid": grid,
            "robustness": robustness,
            "target_counts_before": {name: len(values) for name, values in old_targets.items()},
            "target_counts_after": {name: len(values) for name, values in targets.items()}}


def save_dataset(dataset: dict[str, Any], out_dir: str | Path = "data/ml") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / f"dataset_{dataset['grid']}.npz", X=dataset["X"],
                        **{target: np.asarray([(r["bank_id"], r["period"]) in values
                                               for r in dataset["rows"]])
                           for target, values in dataset["targets"].items()})
    manifest = {"grid": dataset["grid"], "panel_hash": dataset["panel_hash"],
                "rows": len(dataset["rows"]), "columns": dataset["columns"],
                "targets": {k: len(v) for k, v in dataset["targets"].items()}}
    (out / f"manifest_{dataset['grid']}.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return out


def folds(rows: list[dict[str, Any]]) -> list[tuple[np.ndarray, np.ndarray]]:
    result = []
    for test_year in (2017, 2018, 2019, 2020, 2021):
        train = np.asarray([i for i, row in enumerate(rows) if 2014 <= row["period"].year <= test_year - 2])
        test = np.asarray([i for i, row in enumerate(rows) if row["period"].year == test_year])
        result.append((train, test))
    return result


def train(conn, target: str = "T5", grid: str = "semiannual",
          out_dir: str | Path = "data/ml", robustness: bool = False,
          models: list[str] | None = None, wall_clock_hours: float = 2.0) -> dict[str, Any]:
    if target not in TARGETS:
        raise ValueError(f"unknown target: {target}")
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier

    random.seed(SEED)
    np.random.seed(SEED)
    selected_algorithms = tuple(models or ("LR", "RF", "XGB"))
    invalid = set(selected_algorithms) - {"LR", "RF", "XGB"}
    if invalid:
        raise ValueError(f"unknown models: {sorted(invalid)}")
    started = time.monotonic()
    logger = logging.getLogger("eba.ml_redo")
    if not logger.handlers:
        Path("logs").mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler("logs/ml_redo.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    dataset = build_dataset(conn, grid, robustness)
    save_dataset(dataset, out_dir)
    y = np.asarray([(row["bank_id"], row["period"]) in dataset["targets"][target]
                    for row in dataset["rows"]], dtype=int)
    split_report = []
    for fold_number, (train_indices, test_indices) in enumerate(folds(dataset["rows"]), 1):
        test_year = 2016 + fold_number
        split_report.append({
            "fold": fold_number, "train_rows": int(len(train_indices)),
            "train_positives": int(y[train_indices].sum()),
            "test_rows": int(len(test_indices)),
            "test_positives": int(y[test_indices].sum()),
            "train_share_percent": float(100 * y[train_indices].mean())
            if len(train_indices) else 0.0,
            "embargo_year": test_year - 1,
        })
    predictions: dict[str, dict[str, float]] = {}
    fold_metrics = []
    search_results = {}
    selected_params = {}
    smote_metrics = []
    for name in selected_algorithms:
        config_scores = []
        for config_number, params in enumerate(_search_configs(name)):
            if time.monotonic() - started > wall_clock_hours * 3600:
                raise TimeoutError("ML search exceeded wall-clock limit")
            logger.info("configuration model=%s number=%d/%d", name,
                        config_number + 1, SEARCH_CONFIGURATIONS)
            scores = []
            for train_idx, test_idx in folds(dataset["rows"]):
                if not len(test_idx) or not len(train_idx):
                    continue
                positives = int(y[train_idx].sum())
                weight = (len(train_idx) - positives) / positives if positives else 1.0
                candidate = model_factory(name, params, weight)
                candidate.fit(dataset["X"][train_idx], y[train_idx])
                scores.append(float(average_precision_score(
                    y[test_idx], candidate.predict_proba(dataset["X"][test_idx])[:, 1])))
            config_scores.append({"configuration": config_number, "parameters": params,
                                  "fold_pr_auc": scores, "mean_pr_auc": float(np.mean(scores))})
        search_results[name] = config_scores
        selected_params[name] = max(config_scores, key=lambda value: value["mean_pr_auc"])["parameters"]
    models = {name: model_factory(name, selected_params[name])
              for name in selected_algorithms}
    for fold_number, (train_idx, test_idx) in enumerate(folds(dataset["rows"]), 1):
        if not len(test_idx) or not len(train_idx):
            continue
        for name in models:
            if time.monotonic() - started > wall_clock_hours * 3600:
                raise TimeoutError("ML search exceeded wall-clock limit")
            positives = int(y[train_idx].sum())
            weight = (len(train_idx) - positives) / positives if positives else 1.0
            model = model_factory(name, selected_params[name], weight)
            model.fit(dataset["X"][train_idx], y[train_idx])
            probability = model.predict_proba(dataset["X"][test_idx])[:, 1]
            fold_metrics.append({"fold": fold_number, "model": name,
                                 "pr_auc": average_precision_score(y[test_idx], probability),
                                 "roc_auc": roc_auc_score(y[test_idx], probability) if len(set(y[test_idx])) > 1 else None,
                                 "brier": brier_score_loss(y[test_idx], probability)})
            predictions.setdefault(name, {}).update({
                f"{dataset['rows'][i]['bank_id']}:{dataset['rows'][i]['period'].isoformat()}": float(p)
                for i, p in zip(test_idx, probability)})
            if len(np.unique(y[train_idx])) > 1:
                from imblearn.over_sampling import SMOTE
                from sklearn.base import clone
                from sklearn.impute import SimpleImputer
                transformed = SimpleImputer(strategy="median").fit_transform(dataset["X"][train_idx])
                x_over, y_over = SMOTE(random_state=SEED).fit_resample(transformed, y[train_idx])
                comparison = clone(model)
                comparison.fit(x_over, y_over)
                test_values = SimpleImputer(strategy="median").fit(dataset["X"][train_idx]).transform(
                    dataset["X"][test_idx])
                probability = comparison.predict_proba(test_values)[:, 1]
                smote_metrics.append({"fold": fold_number, "model": name,
                                      "pr_auc": average_precision_score(y[test_idx], probability)})
    pooled_metrics = {}
    for name, values in predictions.items():
        keys = list(values)
        actual = np.asarray([y[next(i for i, row in enumerate(dataset["rows"])
                                     if f"{row['bank_id']}:{row['period'].isoformat()}" == key)]
                            for key in keys])
        probability = np.asarray([values[key] for key in keys])
        pooled_metrics[name] = {
            "pr_auc": float(average_precision_score(actual, probability)),
            "roc_auc": float(roc_auc_score(actual, probability)) if len(set(actual)) > 1 else None,
            "brier": float(brier_score_loss(actual, probability)),
        }
    comparator_scores = {"v1.1 score": {}, "B4": {}, "B2": {}}
    with conn.cursor() as cur:
        cur.execute("""SELECT a.bank_id,v.period_end,a.level,a.rule_results
                       FROM alert a JOIN dataset_version v USING(version_id)
                       WHERE a.profile_sha256=%s""",
                    ("28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40",))
        alert_rows = {(bank, period): (level, payload) for bank, period, level, payload in cur.fetchall()}
    for row in dataset["rows"]:
        key = (row["bank_id"], row["period"])
        level, payload = alert_rows.get(key, ("not_evaluated", {}))
        family_scores = (payload or {}).get("family_scores", {})
        comparator_scores["v1.1 score"][key] = sum(
            float(value.get("score", 0)) for value in family_scores.values())
        npl, cet1 = row["npl_ratio"], row["cet1_ratio"]
        comparator_scores["B4"][key] = float(
            (npl is not None and npl > .08) or (cet1 is not None and cet1 < .11))
        comparator_scores["B2"][key] = float(cet1 is not None and cet1 < .11)
    for name, scores in comparator_scores.items():
        actual = np.asarray([y[i] for i, row in enumerate(dataset["rows"])])
        values = np.asarray([scores[(row["bank_id"], row["period"])] for row in dataset["rows"]])
        pooled_metrics[name] = {"pr_auc": float(average_precision_score(actual, values)),
                                "roc_auc": float(roc_auc_score(actual, values)),
                                "brier": None}
    final_test = {}
    train_idx = np.asarray([i for i, row in enumerate(dataset["rows"]) if row["period"].year <= 2020])
    test_idx = np.asarray([i for i, row in enumerate(dataset["rows"]) if 2022 <= row["period"].year <= 2024])
    split_report.append({
        "fold": "final_test", "train_rows": int(len(train_idx)),
        "train_positives": int(y[train_idx].sum()), "test_rows": int(len(test_idx)),
        "test_positives": int(y[test_idx].sum()),
        "train_share_percent": float(100 * y[train_idx].mean()) if len(train_idx) else 0.0,
        "embargo_year": None,
    })
    selected_model = None
    for name, model in models.items():
        model.fit(dataset["X"][train_idx], y[train_idx])
        if len(test_idx) and len(set(y[test_idx])) > 1:
            probability = model.predict_proba(dataset["X"][test_idx])[:, 1]
            final_test[name] = {"pr_auc": float(average_precision_score(y[test_idx], probability)),
                                "roc_auc": float(roc_auc_score(y[test_idx], probability)),
                                "brier": float(brier_score_loss(y[test_idx], probability))}
    for name, scores in comparator_scores.items():
        values = np.asarray([scores[(dataset["rows"][i]["bank_id"],
                                     dataset["rows"][i]["period"])] for i in test_idx])
        final_test[name] = {"pr_auc": float(average_precision_score(y[test_idx], values)),
                            "roc_auc": float(roc_auc_score(y[test_idx], values)),
                            "brier": None}
    selected_name = max(selected_algorithms,
                        key=lambda name: pooled_metrics[name]["pr_auc"])
    selected_model = models[selected_name]
    positives = int(y[train_idx].sum())
    weight = (len(train_idx) - positives) / positives if positives else 1.0
    selected_model = model_factory(selected_name, selected_params[selected_name], weight)
    selected_model.fit(dataset["X"][train_idx], y[train_idx])
    import shap
    shap_idx = test_idx if len(test_idx) else train_idx
    if selected_name == "LR":
        imputer = selected_model.named_steps["imputer"]
        scaler = selected_model.named_steps["scale"]
        train_values = scaler.transform(imputer.transform(dataset["X"][train_idx]))
        explain_values = scaler.transform(imputer.transform(dataset["X"][shap_idx]))
        explanation = shap.LinearExplainer(selected_model.named_steps["model"], train_values)
        shap_columns = list(imputer.get_feature_names_out(dataset["columns"]))
    else:
        explanation = shap.TreeExplainer(selected_model)
        explain_values = dataset["X"][shap_idx]
        shap_columns = list(dataset["columns"])
    values = explanation.shap_values(explain_values)
    values = values[1] if isinstance(values, list) else values
    shap_importance = {column: float(np.nanmean(np.abs(values[:, i])))
                       for i, column in enumerate(shap_columns)}
    pooled_arrays = {}
    key_to_index = {f"{row['bank_id']}:{row['period'].isoformat()}": i
                   for i, row in enumerate(dataset["rows"])}
    for name, values in predictions.items():
       indices = np.asarray([key_to_index[key] for key in values])
       pooled_arrays[name] = (y[indices], np.asarray(list(values.values())),
                              np.asarray([dataset["rows"][i]["bank_id"] for i in indices]), indices)
    bootstrap_cis = {}
    for reference in ("v1.1 score", "B4"):
       ref_scores = np.asarray([comparator_scores[reference][(r["bank_id"], r["period"])]
                                for r in dataset["rows"]])
       for name in selected_algorithms:
           actual, scores, banks, indices = pooled_arrays[name]
           bootstrap_cis[f"{name}_vs_{reference}"] = _cluster_bootstrap(
               actual, scores, ref_scores[indices], banks)
    event_metrics = {
       name: _classification_metrics(y, np.asarray([
           scores[(row["bank_id"], row["period"])] for row in dataset["rows"]]))
       for name, scores in comparator_scores.items()
    }
    event_metrics.update({
       name: _classification_metrics(*pooled_arrays[name][:2])
       for name in selected_algorithms
    })
    catalogue = yaml.safe_load(Path("config/events.yaml").read_text()) or {}
    with conn.cursor() as cur:
       cur.execute("SELECT bank_id,trim(lei) FROM bank")
       bank_ids = {lei: bank_id for bank_id, lei in cur.fetchall()}
    selected_scores = predictions[selected_name]
    score_values = np.asarray(list(selected_scores.values()))
    red_share = np.mean(np.asarray([
       comparator_scores["v1.1 score"][(row["bank_id"], row["period"])] > 0
       for row in dataset["rows"]]))
    thresholds = {
       "matched_far": float(np.quantile(score_values, max(0.0, 1.0 - red_share))),
       "max_ur_0_9": float(np.quantile(score_values, .90)),
    }
    event_table = []
    for event in catalogue.get("events", []):
       if event.get("set") != "primary" or event.get("status") != "included":
           continue
       bank_id = bank_ids.get(str(event["bank_lei"]).strip())
       event_date = date.fromisoformat(str(event["event_date"]))
       values = [probability for key, probability in selected_scores.items()
                 if bank_id is not None and key.startswith(f"{bank_id}:")
                 and _months(event_date, -12) <= date.fromisoformat(key.split(":", 1)[1])
                 <= _months(event_date, -3)]
       probability = max(values) if values else None
       event_table.append({
           "event": event.get("name", event.get("bank_lei")),
           "probability": probability,
           "matched_far": probability is not None and probability >= thresholds["matched_far"],
           "max_ur_0_9": probability is not None and probability >= thresholds["max_ur_0_9"],
           "thresholds": thresholds,
       })
    oob_curve = []
    if "RF" in selected_algorithms:
       for estimator_count in (50, 100, 150):
           oob_model = model_factory("RF", {**selected_params["RF"],
                                            "n_estimators": estimator_count})
           oob_model.fit(dataset["X"][train_idx], y[train_idx])
           oob_curve.append({"n_estimators": estimator_count,
                             "oob_score": float(oob_model.oob_score_)})
    result = {"target": target, "grid": grid, "seed": SEED, "search_configurations": SEARCH_CONFIGURATIONS,
             "search": search_results, "selected_parameters": selected_params,
              "panel_hash": dataset["panel_hash"], "fold_metrics": fold_metrics,
              "split_report": split_report,
              "target_counts_before": dataset["target_counts_before"],
              "target_counts_after": dataset["target_counts_after"],
              "smote_metrics": smote_metrics,
              "pooled_metrics": pooled_metrics, "final_test": final_test,
              "selected_model": selected_name, "shap_importance": shap_importance,
              "event_metrics": event_metrics,
              "bootstrap_cis": bootstrap_cis,
              "event_table": event_table,
              "oob_curve": oob_curve,
              "predictions": predictions, "columns": dataset["columns"]}
    suffix = "_robust" if robustness else ""
    path = Path(out_dir) / f"results_{target}_{grid}{suffix}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result
