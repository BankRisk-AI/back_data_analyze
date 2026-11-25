from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.database import connect
from app.core.panel_reader import load_panel
from app.core.worker import Job, JobHandlerRegistry, ProgressReporter
from app.modules.eba_ml.application.dataset import build_dataset, save_dataset
from app.modules.eba_ml.domain.constants import MAX_BUDGET


def _cancelled(conn, job_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT cancel_requested FROM job WHERE job_id=%s", (job_id,))
        row = cur.fetchone()
        return bool(row and row[0])


def _experiment(conn, job: Job):
    with conn.cursor() as cur:
        cur.execute("""SELECT e.experiment_id,e.config,e.budget
                       FROM ml_experiment e
                       WHERE (e.artifact_refs->>'job_id')::integer=%s""", (job.job_id,))
        return cur.fetchone()


def _build(job: Job, progress: ProgressReporter):
    with connect(job.schema) as conn:
        if _cancelled(conn, job.job_id):
            return
        experiment = _experiment(conn, job)
        if not experiment:
            return
        _, config, budget = experiment
        if budget > MAX_BUDGET:
            raise ValueError(f"budget exceeds configured maximum {MAX_BUDGET}")
        dataset = build_dataset(conn, config.get("grid", "semiannual"),
                                config.get("feature_set") == "robustness_v1")
        path = Path("data/ml")
        path.mkdir(parents=True, exist_ok=True)
        save_dataset(dataset, path)
        progress("dataset built", 50)
        if _cancelled(conn, job.job_id):
            return
        with conn.cursor() as cur:
            cur.execute("UPDATE ml_experiment SET status='running',progress=75 WHERE experiment_id=%s",
                        (experiment[0],))


def _train(job: Job, progress: ProgressReporter):
    with connect(job.schema) as conn:
        if _cancelled(conn, job.job_id):
            return
        experiment = _experiment(conn, job)
        if not experiment:
            return
        _, config, budget = experiment
        from app.modules.eba_ml.domain.constants import MAX_BUDGET
        if budget > MAX_BUDGET:
            raise ValueError(f"budget exceeds configured maximum {MAX_BUDGET}")
        from app.modules.eba_ml.application.training.train import train
        progress("training started", 10)
        train(
            conn,
            label=config.get("label", "E2_or_E3"),
            grid=config.get("grid", "semiannual"),
            out_dir="data/ml",
            robustness=config.get("feature_set") == "robustness_v1",
            wall_clock_hours=float(budget),
            tail_quantile=config.get("tail_quantile"),
        )
        progress("training complete", 90)


def _evaluate(job: Job, progress: ProgressReporter):
    with connect(job.schema) as conn:
        if _cancelled(conn, job.job_id):
            return
        progress("evaluation completed", 90)


@dataclass
class Scorer:
    """Everything needed to score one champion: model, thresholds, feature grouping and SHAP explainer."""
    model_id: int
    fitted: object
    algorithm: str
    op_threshold: float
    r0_levels: dict
    columns: list[str]
    base_to_col_idxs: dict[str, list[int]]
    base_col_index: dict[str, int]
    explainer: object = None
    shap_names_out: list[str] | None = None


def _select_champion(cur, job: Job):
    """(model_id, model_card, artifact sha) of the requested champion (message 'model=<id>') or the first one."""
    cur.execute("SELECT message FROM job WHERE job_id=%s", (job.job_id,))
    message = cur.fetchone()[0] or ""
    model_filter = message.split("model=", 1)[1] if "model=" in message else None
    if model_filter and model_filter.isdigit():
        cur.execute("""SELECT model_id,model_card,artifact_sha256 FROM ml_model
                       WHERE model_id=%s AND status='champion'""", (int(model_filter),))
    else:
        cur.execute("""SELECT model_id,model_card,artifact_sha256 FROM ml_model
                       WHERE status='champion' ORDER BY model_id LIMIT 1""")
    return cur.fetchone()


def _base_feature_groups(columns: list[str]) -> tuple[dict[str, list[int]], dict[str, int]]:
    """Columns of each base feature (value, rank, change, missing) and the index of its own value column."""
    groups: dict[str, list[int]] = {}
    for j, col in enumerate(columns):
        groups.setdefault(col.replace("_rank", "").replace("_change12m", "").replace("_missing", ""), []).append(j)
    index = {col: j for j, col in enumerate(columns)}
    return groups, {base: index.get(base, idxs[0]) for base, idxs in groups.items()}


def _build_explainer(card: dict, fitted, algorithm: str, columns: list[str], store):
    """(explainer, transformed column names): LinearExplainer with the stored background for LR, Tree for RF/XGB."""
    import shap as shap_lib
    if algorithm == "LR":
        background_sha = card.get("shap_background_sha256")
        if background_sha:
            background = store.load_model(background_sha, "joblib")
            return (shap_lib.LinearExplainer(fitted.named_steps["model"], background),
                    list(fitted["imputer"].get_feature_names_out(np.asarray(columns))))
    elif algorithm in ("RF", "XGB"):
        try:
            return shap_lib.TreeExplainer(fitted), None
        except Exception:
            return None, None
    return None, None


def _load_scorer(conn, model_id: int, card: dict, sha: str):
    """Load the fitted model and the dataset rows it scores; returns (Scorer, dataset)."""
    from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore
    from app.modules.eba_rules.public import regulatory_levels
    store = ArtifactStore()
    fitted = store.load_model(sha, card["format"])
    dataset = build_dataset(conn, card.get("grid", "semiannual"), True)
    columns = dataset["columns"]
    groups, base_index = _base_feature_groups(columns)
    algorithm = card.get("algorithm", "")
    explainer, names_out = _build_explainer(card, fitted, algorithm, columns, store)
    scorer = Scorer(model_id, fitted, algorithm, card.get("operating_point", 0.5),
                    card.get("r0_levels") or regulatory_levels(), columns, groups, base_index, explainer, names_out)
    return scorer, dataset


def _top_features(base_shap: dict[str, float], values: np.ndarray, base_col_index: dict[str, int]) -> list[dict]:
    """The five base features with the largest |SHAP|: name, raw value (None if not finite), signed SHAP."""
    top = sorted(base_shap.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    return [{"feature": b,
             "value": float(values[base_col_index[b]]) if np.isfinite(values[base_col_index[b]]) else None,
             "shap": s} for b, s in top]


def _shap_payload(scorer: Scorer, values: np.ndarray) -> list[dict]:
    """Top SHAP contributions of one row, grouped by base feature name."""
    if scorer.explainer is None:
        return []
    col_to_idx = {col: j for j, col in enumerate(scorer.columns)}
    if scorer.algorithm == "LR" and scorer.shap_names_out is not None:
        x_trans = scorer.fitted[:-1].transform(values.reshape(1, -1))
        sv_raw = scorer.explainer.shap_values(x_trans)
        if isinstance(sv_raw, np.ndarray) and sv_raw.ndim == 2:
            sv_raw = sv_raw[0]
        aligned = np.zeros(len(scorer.columns))
        for i, name in enumerate(scorer.shap_names_out):
            if i < len(sv_raw) and name in col_to_idx:
                aligned[col_to_idx[name]] = float(sv_raw[i])
    elif scorer.algorithm == "LR":
        return []
    else:
        sv = scorer.explainer(values.reshape(1, -1)).values[0]
        aligned = np.asarray(sv[:, 1] if sv.ndim == 2 else sv)
    base_shap = {base: float(aligned[idxs].sum()) for base, idxs in scorer.base_to_col_idxs.items()}
    return _top_features(base_shap, values, scorer.base_col_index)


UPSERT_PREDICTION = """INSERT INTO ml_prediction
    (model_id,version_id,bank_id,period_end,threshold_setting,probability,alert,shap)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (model_id,bank_id,period_end,threshold_setting)
    DO UPDATE SET probability=EXCLUDED.probability,alert=EXCLUDED.alert,shap=EXCLUDED.shap"""


def _score_rows(cur, scorer: Scorer, dataset: dict, panel_rows: list, progress) -> tuple[list, int, int]:
    """Score every panel row: R0 breaches are flagged only, the others get probability, alert and SHAP.

    Returns (compliant rows for the top-share pass, number scored, number of R0 breaches).
    """
    from app.modules.eba_rules.public import r0_alert
    features = {f"{r['bank_id']}:{r['period'].isoformat()}": dataset["X"][i] for i, r in enumerate(dataset["rows"])}
    lookup = {f"{r['bank_id']}:{r['period'].isoformat()}": r for r in dataset["rows"]}
    compliant_rows, n_scored, n_breach = [], 0, 0
    for index, (bank_id, version_id, period_end) in enumerate(panel_rows):
        key = f"{bank_id}:{period_end.isoformat()}"
        values = features.get(key)
        if values is None:
            continue
        if r0_alert(lookup.get(key, {}), scorer.r0_levels):          # R0 breach: flag only, no probability score
            cur.execute(UPSERT_PREDICTION, (scorer.model_id, version_id, bank_id, period_end, "r0_breach", 0.0, False, None))
            n_breach += 1
        else:
            probability = float(scorer.fitted.predict_proba(values.reshape(1, -1))[:, 1][0])
            cur.execute(UPSERT_PREDICTION, (scorer.model_id, version_id, bank_id, period_end, "operating_point_f2",
                                            probability, probability >= scorer.op_threshold,
                                            json.dumps(_shap_payload(scorer, values))))
            compliant_rows.append((period_end, probability, bank_id, version_id))
            n_scored += 1
        if index % 100 == 0:
            progress("scoring panel", min(99, index * 100 // max(1, len(panel_rows))))
    return compliant_rows, n_scored, n_breach


def _store_top_share(cur, model_id: int, compliant_rows: list, share: float) -> int:
    """top_10pct_per_period: per period flag the top ceil(share * n_compliant) banks by probability."""
    import math
    from itertools import groupby
    n_alerts = 0
    compliant_rows.sort()
    for period_end, group in groupby(compliant_rows, key=lambda r: r[0]):
        period_rows = sorted(group, key=lambda r: r[1], reverse=True)
        n_flag = max(1, math.ceil(share * len(period_rows)))
        for i, (_, probability, bank_id, version_id) in enumerate(period_rows):
            cur.execute(UPSERT_PREDICTION, (model_id, version_id, bank_id, period_end, "top_10pct_per_period",
                                            probability, i < n_flag, None))
            n_alerts += i < n_flag
    return n_alerts


def _score(job: Job, progress: ProgressReporter):
    """Score the champion on the active panel (recipe): select -> load -> replace predictions -> score -> top share."""
    import yaml
    with connect(job.schema) as conn, conn.cursor() as cur:
        champion = _select_champion(cur, job)
        if not champion:
            return
        model_id, card, sha = champion
        card = card or {}
        if not card.get("format"):
            raise ValueError("champion has no fitted model format")
        share = float(yaml.safe_load(open("config/ml.yaml").read()).get("top_alert_share", 0.10))
        scorer, dataset = _load_scorer(conn, model_id, card, sha)
        panel_rows = [(r["bank_id"], r["dataset_version"], r["period"]) for r in load_panel(cur).rows]
        cur.execute("DELETE FROM ml_prediction WHERE model_id=%s", (model_id,))
        cur.execute("""INSERT INTO audit_log(action,entity,entity_id,detail) VALUES (%s,%s,%s,%s)""",
                    ("score_panel replace predictions", "ml_model", str(model_id), json.dumps({"deleted": cur.rowcount})))
        compliant_rows, n_scored, n_breach = _score_rows(cur, scorer, dataset, panel_rows, progress)
        n_top = _store_top_share(cur, model_id, compliant_rows, share)
        cur.execute("""INSERT INTO audit_log(action,entity,entity_id,detail) VALUES ('score_panel','ml_model',%s,%s)""",
                    (str(model_id), json.dumps({"scored": n_scored, "r0_breach": n_breach, "top_10pct_alerts": n_top})))
        progress("panel scored", 99)


def register_handlers(registry: JobHandlerRegistry):
    registry.register("build_ml_dataset", _build)
    registry.register("train_model", _train)
    registry.register("tune_model", _train)
    registry.register("evaluate_model", _evaluate)
    registry.register("score_panel", _score)
