"""Synthetic end-to-end test: train() + hypotheses() without a database (T-2).

Builds a minimal in-memory panel, injects it via `dataset=`, patches
_search_configs at the import site in search.py (budget=2), runs quick mode.
No DB required; must pass in CI before any real run.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from ml_synthetic import _FEATURES, R0, _dataset, _make_panel, _row, _two_configs  # noqa: F401


def test_training_is_deterministic_and_complete(tmp_path, monkeypatch):
    """Same seed, same synthetic panel -> identical predictions; the result carries what the app needs."""
    import app.modules.eba_ml.application.training.search as search_mod
    monkeypatch.setattr(search_mod, "_search_configs", _two_configs)
    from app.modules.eba_ml.application.training.train import train

    runs = [train(conn=None, label="E2_or_E3", out_dir=str(tmp_path / name), models=["LR"],
                  wall_clock_hours=1.0, space="table35", dataset=_dataset(_make_panel()))
            for name in ("a", "b")]
    a, b = runs
    assert a["predictions"] == b["predictions"] and a["test_predictions"] == b["test_predictions"]
    assert a["operating_point_threshold"] == b["operating_point_threshold"]
    assert a["label"] == "E2_or_E3" and a["r1_margin"] is not None and a["rows"]
    assert (tmp_path / "a" / "search.json").exists()


def test_training_fails_clearly_when_no_row_can_be_labelled(tmp_path):
    """A panel without any evaluable future (single last period) -> ValueError, not an empty fit."""
    from app.modules.eba_ml.application.training.train import train
    rows = [_row(b, date(2024, 12, 31)) for b in range(1, 6)]
    with pytest.raises(ValueError, match="No rows in prediction sample"):
        train(conn=None, label="E2_or_E3", out_dir=str(tmp_path), dataset=_dataset(rows))


def test_leakage_guard_rejects_a_feature_that_is_the_label():
    """A single feature with PR-AUC > 0.95 against the label aborts training."""
    import logging
    from app.modules.eba_ml.application.training.train import _check_leakage
    y = np.array([0, 1] * 30)
    dataset = {"X": np.column_stack([y + 0.0, np.random.default_rng(0).random(60)]),
               "columns": ["leaky", "noise"]}
    with pytest.raises(ValueError, match="possible label leakage: leaky"):
        _check_leakage(dataset, y, logging.getLogger("t"))
    dataset["X"][:, 0] = np.random.default_rng(1).random(60)
    _check_leakage(dataset, y, logging.getLogger("t"))


def test_train_unknown_label_raises(tmp_path):
    """train() raises ValueError for unrecognised label (service 422 boundary)."""
    from app.modules.eba_ml.application.training.train import train
    rows = _make_panel()
    ds = _dataset(rows)
    with pytest.raises(ValueError, match="unknown label"):
        train(conn=None, label="BOGUS", out_dir=str(tmp_path), dataset=ds)


def test_service_validate_unknown_label():
    """service._validate raises InvalidParameter for unknown label."""
    from app.core.exceptions import InvalidParameter
    from app.modules.eba_ml.application.service import _validate
    with pytest.raises(InvalidParameter, match="unknown label"):
        _validate({"grid": "semiannual", "feature_set": "robustness_v1",
                   "algorithms": ["LR"], "label": "BOGUS"})


def test_service_validate_unknown_tail_quantile():
    """service._validate raises InvalidParameter for disallowed tail_quantile."""
    from app.core.exceptions import InvalidParameter
    from app.modules.eba_ml.application.service import _validate
    with pytest.raises(InvalidParameter, match="unknown tail_quantile"):
        _validate({"grid": "semiannual", "feature_set": "robustness_v1",
                   "algorithms": ["LR"], "label": "E2_or_E3", "tail_quantile": 0.50})


def test_service_validate_allowed_tail_quantile():
    """service._validate accepts known tail_quantile values without error."""
    from app.modules.eba_ml.application.service import _validate
    for q in (0.90, 0.95, 0.975, 0.99):
        _validate({"grid": "semiannual", "feature_set": "robustness_v1",
                   "algorithms": ["LR"], "label": "E2_or_E3", "tail_quantile": q})


def test_hypotheses_synthetic_quick(tmp_path, monkeypatch):
    """run_hypotheses() --quick completes on a synthetic JSON with mocked DB."""
    import app.modules.eba_ml.application.training.search as search_mod
    monkeypatch.setattr(search_mod, "_search_configs", _two_configs)

    rows = _make_panel()
    ds = _dataset(rows)

    # Patch the import-sites used by the hypotheses script (read-only DB access)
    import scripts.hypotheses.context as ctx_mod
    monkeypatch.setattr(ctx_mod, "build_dataset", lambda conn, grid="semiannual", robustness=False: ds)

    import scripts.hypotheses.main as hyp_mod

    class _FakeConn:
        def cursor(self): return _FakeCur()
        def close(self): pass

    class _FakeCur:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, *a, **kw): pass
        def fetchone(self): return None
        def fetchall(self): return []

    monkeypatch.setattr(hyp_mod, "connect", lambda schema: _FakeConn())
    monkeypatch.setattr(hyp_mod, "get_schema", lambda: "public")

    # Build a minimal results JSON using train()
    from app.modules.eba_ml.application.training.train import train
    result = train(conn=None, label="E2_or_E3", out_dir=str(tmp_path),
                   wall_clock_hours=1.0, space="table35", dataset=ds)

    from scripts.hypotheses.main import run_hypotheses
    report = run_hypotheses(tmp_path, quick=True)

    assert "H1a" in report
    assert "H1b" in report
    assert "H2" in report
    assert "H3" in report
    assert "H5" in report
