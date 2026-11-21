"""Registry import and model lifecycle persistence."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore


def import_thesis_experiment(conn, result_path: str | Path = "data/ml/results_T5_semiannual_robust.json") -> int:
    """Import the protected 5c run idempotently; return the experiment id."""
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    config = {"target": result["target"], "grid": result["grid"], "robustness": True,
              "seed": result["seed"], "budget": result["search_configurations"]}
    content = json.dumps(config, sort_keys=True).encode()
    content_hash = hashlib.sha256(content).hexdigest()
    store = ArtifactStore()
    with conn.cursor() as cur:
        cur.execute("SELECT dataset_id FROM ml_dataset WHERE content_hash=%s", (content_hash,))
        dataset = cur.fetchone()
        if dataset:
            dataset_id = dataset[0]
        else:
            cur.execute("""INSERT INTO ml_dataset
                (target,grid,feature_set,panel_hash,content_hash,manifest,row_count,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'ready') RETURNING dataset_id""",
                        (result["target"], result["grid"], "robustness_v1",
                         result["panel_hash"], content_hash,
                         json.dumps({"columns": result["columns"], "protected": True}),
                         sum(1 for _ in result["predictions"]["XGB"])))
            dataset_id = cur.fetchone()[0]
        cur.execute("SELECT experiment_id FROM ml_experiment WHERE dataset_id=%s", (dataset_id,))
        experiment = cur.fetchone()
        if experiment:
            cur.execute("UPDATE ml_dataset SET protected=true WHERE dataset_id=%s", (dataset_id,))
            cur.execute("UPDATE ml_experiment SET protected=true WHERE experiment_id=%s", (experiment[0],))
            return experiment[0]
        cur.execute("""INSERT INTO ml_experiment
            (dataset_id,config,seed,folds,budget,status,progress,metrics,artifact_refs)
            VALUES (%s,%s,%s,%s,%s,'completed',100,%s,%s) RETURNING experiment_id""",
                    (dataset_id, json.dumps(config), result["seed"],
                     json.dumps([2017, 2018, 2019, 2020, 2021]),
                     result["search_configurations"],
                     json.dumps({"pooled": result["pooled_metrics"],
                                 "final": result["final_test"]}),
                     json.dumps({"result": str(result_path)})))
        experiment_id = cur.fetchone()[0]
        cur.execute("UPDATE ml_dataset SET protected=true WHERE dataset_id=%s", (dataset_id,))
        cur.execute("UPDATE ml_experiment SET protected=true WHERE experiment_id=%s", (experiment_id,))
        for algorithm in ("LR", "RF", "XGB"):
            payload = json.dumps({"algorithm": algorithm, "result": result},
                                 sort_keys=True).encode()
            sha = store.put(payload, {"data_hash": result["panel_hash"], "config": config,
                                      "metrics": result["pooled_metrics"], "git_commit": "imported",
                                      "python": platform.python_version()})
            name = f"stage5c-robustness-{algorithm.lower()}"
            cur.execute("""INSERT INTO ml_model
                (experiment_id,name,target,grid,algorithm,hyperparameters,artifact_sha256,
                 model_card,status,protected)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'validated',true)
                ON CONFLICT (name) DO NOTHING""",
                        (experiment_id, name, result["target"], result["grid"], algorithm,
                         json.dumps({}), sha, json.dumps({"protected": True})))
        cur.execute("""INSERT INTO audit_log (action,entity,entity_id,detail)
                       VALUES ('create','ml_experiment',%s,%s)""",
                    (str(experiment_id), json.dumps({"protected": True})))
    return experiment_id
