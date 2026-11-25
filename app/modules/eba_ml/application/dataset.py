"""Panel feature matrix construction, fold splits, and dataset persistence.

No target labels — labels are computed externally (T-2 adds E2/E3).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from app.core.panel_reader import load_panel, panel_hash
from app.modules.eba_ml.domain.constants import FEATURES


def _months(date_value: date, count: int) -> date:
    absolute = date_value.year * 12 + date_value.month - 1 + count
    year, month = divmod(absolute, 12)
    return date(year, month + 1, date_value.day)


def build_dataset(conn, grid: str = "semiannual", robustness: bool = False) -> dict[str, Any]:
    """Build the feature matrix and row index from the active panel (§3.5).

    Returns rows, X (feature matrix), columns, panel_hash, grid, robustness.
    Target labels are not included; pass y externally (T-2).
    """
    if grid not in {"semiannual", "quarterly"}:
        raise ValueError("grid must be semiannual or quarterly")
    with conn.cursor() as cur:
        panel = load_panel(cur)
    rows = []
    for source in panel.rows:                                  # ML adjustments on top of load_panel:
        if any("specialist_institution" in value for value in source["flags"].values()):
            continue                                           # 1. specialist institutions are excluded
        if grid == "semiannual" and source["period"].month not in (6, 12):
            continue                                           # 2. semiannual grid keeps June/December
        rows.append({"bank_id": source["bank_id"], "period": source["period"],
                     **{feature: source[feature] for feature in FEATURES}})
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
    return {"rows": rows, "X": np.asarray(matrix, dtype=float), "columns": columns,
            "panel_hash": panel_hash(rows, FEATURES), "grid": grid, "robustness": robustness}


def save_dataset(dataset: dict[str, Any], out_dir: str | Path = "data/ml") -> Path:
    """Save feature matrix and manifest to out_dir (§3.5).

    Does not save labels; labels are managed externally (T-2).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / f"dataset_{dataset['grid']}.npz", X=dataset["X"])
    manifest = {"grid": dataset["grid"], "panel_hash": dataset["panel_hash"],
                "rows": len(dataset["rows"]), "columns": dataset["columns"]}
    (out / f"manifest_{dataset['grid']}.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return out


def folds(rows: list[dict[str, Any]]) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return (train_idx, test_idx) pairs with one-year embargo (Table 3.5).

    Test years 2017-2021; training data ends at test_year - 2.
    """
    result = []
    for test_year in (2017, 2018, 2019, 2020, 2021):
        train = np.asarray(
            [i for i, row in enumerate(rows) if 2014 <= row["period"].year <= test_year - 2],
            dtype=int)
        test = np.asarray(
            [i for i, row in enumerate(rows) if row["period"].year == test_year],
            dtype=int)
        if len(train) == 0 or len(test) == 0:
            import logging
            logging.getLogger(__name__).warning(
                "fold year=%d has empty split (train=%d test=%d) — fold skipped",
                test_year, len(train), len(test))
        result.append((train, test))
    return result
