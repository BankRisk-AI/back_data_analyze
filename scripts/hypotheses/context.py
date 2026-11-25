"""Load one training run once and share it across H1a-H5 (thesis §3.6).

A RunContext holds the results artefact, the rebuilt dataset and the index arrays.
Labels come from the rows stored in the artefact; the panel hash is verified.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.modules.eba_ml.application.config import load_ml_config
from app.modules.eba_ml.application.dataset import build_dataset
from app.modules.eba_rules.public import regulatory_levels


@dataclass
class Settings:
    """The `hypotheses:` section of config/ml.yaml, resolved for one run."""
    seed: int
    replicates: int
    h3_budget: int
    validation_seed_offset: int
    validation_years: tuple[int, int]
    test_years: tuple[int, int]
    fixed_alert_shares_pct: tuple[int, ...]
    min_wilcoxon_n: int
    h4_status: str
    r0_levels: dict[str, float]
    comparator_profile_sha: str


def load_settings(quick: bool = False) -> Settings:
    """Read config/ml.yaml; quick=True selects the reduced replicates and H3 budget."""
    cfg = load_ml_config()
    h = cfg["hypotheses"]
    return Settings(
        seed=h["seed"],
        replicates=h["replicates_quick" if quick else "replicates"],
        h3_budget=h["h3_budget_quick" if quick else "h3_budget"],
        validation_seed_offset=h["validation_seed_offset"],
        validation_years=tuple(h["validation_years"]),
        test_years=tuple(h["test_years"]),
        fixed_alert_shares_pct=tuple(h["fixed_alert_shares_pct"]),
        min_wilcoxon_n=h["min_wilcoxon_n"],
        h4_status=h["h4_status"],
        r0_levels=regulatory_levels(),
        comparator_profile_sha=cfg.get("comparator_profile_sha", ""),
    )


@dataclass
class RunContext:
    """All data needed to evaluate the hypotheses of one training run."""
    artifact: dict[str, Any]
    dataset: dict[str, Any]
    rows: list[dict]
    keys: np.ndarray
    target: str
    y: np.ndarray
    arrays: dict[str, np.ndarray]
    valid: dict[str, np.ndarray]
    selected: str
    operating_point_threshold: float
    r1_margin: float
    run_dir: Path
    conn: Any  # live DB connection (read-only: v1.1 alert query in H1b)
    settings: Settings

    @property
    def r0_levels(self) -> dict[str, float]:
        """R0 alert levels used when the labels were built (config as fallback)."""
        return (self.artifact.get("label_meta") or {}).get("r0_levels") or self.settings.r0_levels

    @property
    def space(self) -> str:
        """Search space used by the run ("table35" or "extended")."""
        return self.artifact.get("space", "table35")


def _stored_labels(artifact: dict, rows: list[dict]) -> np.ndarray:
    """Labels of the dataset rows from the artefact (-1 = outside the prediction sample)."""
    stored = artifact.get("rows", [])
    if not (stored and "label" in stored[0]):
        raise NotImplementedError("artefact has no stored row labels; run training first")
    lookup = {(r["bank_id"], r["period"]): int(r["label"]) for r in stored}
    return np.asarray([lookup.get((row["bank_id"], row["period"].isoformat()), -1)
                       for row in rows], dtype=int)


def _selected_model(artifact: dict) -> str:
    """Selected model of the run; falls back to the best mean search PR-AUC."""
    if artifact.get("selected_model"):
        return artifact["selected_model"]
    search = artifact.get("search", {})
    return max(("LR", "RF", "XGB"),
               key=lambda n: max(search.get(n, [{"mean_pr_auc": 0}]),
                                 key=lambda x: x["mean_pr_auc"])["mean_pr_auc"])


def load_run(run_dir: str | Path, conn, settings: Settings) -> RunContext:
    """Load the results artefact of run_dir, rebuild the dataset, derive the index arrays."""
    run = Path(run_dir)
    artifact = json.loads(next(run.glob("results_*.json")).read_text())
    dataset = build_dataset(conn, artifact.get("grid", "semiannual"),
                            artifact.get("robustness", True))
    stored_hash = artifact.get("panel_hash")
    if stored_hash and stored_hash != dataset["panel_hash"]:
        warnings.warn(
            f"panel_hash mismatch: stored={stored_hash[:12]}... "
            f"live={dataset['panel_hash'][:12]}...; results may not match live panel",
            stacklevel=2)

    rows = dataset["rows"]
    keys = np.asarray([f"{r['bank_id']}:{r['period'].isoformat()}" for r in rows])
    y = _stored_labels(artifact, rows)
    arrays = {name: np.asarray([scores.get(key, np.nan) for key in keys], dtype=float)
              for name, scores in artifact.get("predictions", {}).items()}
    return RunContext(
        artifact=artifact, dataset=dataset, rows=rows, keys=keys,
        target=artifact.get("label", artifact.get("target", "unknown")), y=y,
        arrays=arrays, valid={n: np.isfinite(v) & (y >= 0) for n, v in arrays.items()},
        selected=_selected_model(artifact),
        operating_point_threshold=float(artifact.get("operating_point_threshold", 0.5)),
        r1_margin=float(artifact.get("r1_margin", 0.0)),
        run_dir=run, conn=conn, settings=settings)
