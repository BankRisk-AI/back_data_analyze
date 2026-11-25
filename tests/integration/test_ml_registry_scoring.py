"""Registry invariants, score_panel and the /api/ml contract on a synthetic panel in eba_test.

Seeds and removes its own rows; the artefact store is a tmp directory (EBA_STORAGE).
"""
from __future__ import annotations

import io
import json

import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from ml_synthetic import clear_panel, seed_panel

from app.core.worker import Job
from app.modules.eba_ml.application import service
from app.modules.eba_ml.application.models import model_factory
from app.modules.eba_ml.application.worker_handlers import _score
from app.modules.eba_ml.application.dataset import build_dataset
from app.modules.eba_ml.domain.constants import FEATURES
from app.modules.eba_ml.domain.exceptions import ProtectedModelError
from app.modules.eba_ml.infrastructure.artifacts import ArtifactStore


def _insert_model(cur, experiment_id: int, name: str, status: str, protected: bool,
                  sha: str, card: dict) -> int:
    cur.execute("""INSERT INTO ml_model(experiment_id,name,target,grid,algorithm,hyperparameters,
                       artifact_sha256,model_card,status,protected)
                   VALUES (%s,%s,'E2_or_E3','semiannual','LR','{}',%s,%s,%s,%s) RETURNING model_id""",
                (experiment_id, name, sha, json.dumps(card), status, protected))
    return cur.fetchone()[0]


@pytest.fixture()
def registry(db, monkeypatch):
    """Seeded panel + one fitted LR artefact + dataset/experiment rows; helpers to add models."""
    monkeypatch.setenv("EBA_STORAGE", db.storage)
    import_id = seed_panel(db.cur)
    # plant one R0 breach (CET1 below 7%) in the last period of bank 1
    db.cur.execute("""UPDATE panel_row SET cet1_ratio=0.05 WHERE bank_id=(SELECT min(bank_id) FROM bank
                      WHERE lei LIKE 'SYNTHETICBANK%') AND version_id=(SELECT version_id FROM dataset_version
                      ORDER BY period_end DESC LIMIT 1)""")
    dataset = build_dataset(db.conn, "semiannual", True)
    y = (np.nan_to_num(dataset["X"][:, 0]) < np.nanmedian(dataset["X"][:, 0])).astype(int)
    fitted = model_factory("LR", {}, 1.0)
    fitted.fit(dataset["X"], y)
    buffer = io.BytesIO(); joblib.dump(fitted, buffer)
    store = ArtifactStore()
    sha = store.put(buffer.getvalue(), {})
    background = io.BytesIO(); joblib.dump(fitted[:-1].transform(dataset["X"][:50]), background)
    card = {"format": "joblib", "algorithm": "LR", "grid": "semiannual", "operating_point": 0.5,
            "shap_background_sha256": store.put(background.getvalue(), {})}
    db.cur.execute("""INSERT INTO ml_dataset(target,grid,feature_set,panel_hash,content_hash,manifest,row_count,status)
                      VALUES ('E2_or_E3','semiannual','robustness_v1',%s,%s,'{}',1,'ready') RETURNING dataset_id""",
                   ("0" * 64, "1" * 64))
    db.cur.execute("""INSERT INTO ml_experiment(dataset_id,config,seed,folds,budget,status)
                      VALUES (%s,'{}',1,'[]',1,'completed') RETURNING experiment_id""", (db.cur.fetchone()[0],))
    db.experiment_id, db.import_id, db.sha, db.card = db.cur.fetchone()[0], import_id, sha, card
    db.add = lambda name, status, protected: _insert_model(
        db.cur, db.experiment_id, name, status, protected, sha, card)
    yield db
    db.cur.execute("TRUNCATE ml_prediction, ml_model, ml_experiment, ml_dataset CASCADE")
    clear_panel(db.cur)


def _status(db, model_id: int) -> str:
    db.cur.execute("SELECT status FROM ml_model WHERE model_id=%s", (model_id,))
    return db.cur.fetchone()[0]


def test_promoting_replaces_the_champion_protected_goes_back_to_validated(registry):
    protected = registry.add("p-champion", "champion", True)
    plain = registry.add("plain-champion-candidate", "validated", False)
    service.promote_model(plain)
    assert (_status(registry, protected), _status(registry, plain)) == ("validated", "champion")
    other = registry.add("later", "validated", False)
    service.promote_model(other)           # a non-protected former champion is archived
    registry.cur.execute("SELECT count(*) FROM ml_model WHERE status='champion'")
    assert registry.cur.fetchone()[0] == 1 and _status(registry, plain) == "archived"


def test_one_champion_per_label_and_grid_is_enforced_by_the_database(registry):
    import psycopg2
    registry.add("c1", "champion", False)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        registry.add("c2", "champion", False)


def test_protected_and_champion_models_cannot_be_archived_or_deleted(registry):
    protected = registry.add("prot", "validated", True)
    champion = registry.add("champ", "champion", False)
    for model_id, name in ((protected, "prot"), (champion, "champ")):
        with pytest.raises(ProtectedModelError):
            service.archive_model(model_id)
        with pytest.raises(ProtectedModelError):
            service.hard_delete_model(model_id, name)


def test_a_tampered_artefact_is_refused_on_load(registry):
    path = ArtifactStore()._directory(registry.sha) / "model.bin"
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(ValueError, match="verification failed"):
        ArtifactStore().load_model(registry.sha, "joblib")


def _run_score(db, model_id: int) -> None:
    db.cur.execute("INSERT INTO job(import_id,kind,message) VALUES (%s,'score_panel',%s) RETURNING job_id",
                   (db.import_id, f"model={model_id}"))
    _score(Job(job_id=db.cur.fetchone()[0], import_id=db.import_id, kind="score_panel", schema=db.schema),
           lambda message, percent: None)


def _predictions(db, model_id: int) -> list[tuple]:
    db.cur.execute("""SELECT bank_id,period_end,threshold_setting,probability,alert,shap
                      FROM ml_prediction WHERE model_id=%s ORDER BY threshold_setting,period_end,bank_id""",
                   (model_id,))
    return db.cur.fetchall()


def test_score_panel_writes_all_modes_and_r0_breach_rows_with_reproducible_named_shap(registry):
    model_id = registry.add("scored", "champion", False)
    _run_score(registry, model_id)
    first = _predictions(registry, model_id)
    modes = {row[2] for row in first}
    assert modes == {"operating_point_f2", "top_10pct_per_period", "r0_breach"}
    breach = [r for r in first if r[2] == "r0_breach"]
    assert len(breach) == 1 and breach[0][3] == 0.0 and breach[0][4] is False
    scored = [r for r in first if r[2] == "operating_point_f2"]
    assert all(r[5] for r in scored)
    for r in scored:
        assert {e["feature"] for e in r[5]} <= set(FEATURES) and len(r[5]) <= 5
    _run_score(registry, model_id)         # replaces predictions with identical values
    assert _predictions(registry, model_id) == first


def test_api_ml_contract_422_409_pagination_and_problem_json(registry):
    from app.main import create_app
    client = TestClient(create_app(schema=registry.schema))
    champion = registry.add("champ-api", "champion", True)
    for i in range(3):
        registry.add(f"extra-{i}", "validated", False)
    bad = client.post("/api/ml/experiments", json={"dataset_id": 1, "algorithms": ["NOPE"], "grid": "semiannual"})
    assert bad.status_code == 422 and bad.headers["content-type"].startswith("application/problem+json")
    gone = client.request("DELETE", f"/api/ml/models/{champion}", json={"model_name": "champ-api"})
    assert gone.status_code == 409 and gone.headers["content-type"].startswith("application/problem+json")
    assert client.get("/api/ml/models/999999").status_code == 404
    page = client.get("/api/ml/models", params={"page": 1, "page_size": 2}).json()
    assert len(page["items"]) == 2 and page["page"] == 1 and page["page_size"] == 2
    assert client.get("/api/ml/models", params={"page": 2, "page_size": 2}).json()["items"]
    assert client.get("/api/ml/models", params={"page_size": 100000}).status_code == 422


def test_an_unprotected_archived_model_can_be_deleted_with_its_exact_name(registry):
    model_id = registry.add("disposable", "archived", False)
    with pytest.raises(Exception, match="confirmation"):
        service.hard_delete_model(model_id, "wrong-name")
    service.hard_delete_model(model_id, "disposable")
    registry.cur.execute("SELECT count(*) FROM ml_model WHERE model_id=%s", (model_id,))
    assert registry.cur.fetchone()[0] == 0
