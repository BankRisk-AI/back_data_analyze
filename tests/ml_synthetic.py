"""Synthetic panel shared by the ML tests: 10 banks x 2014-2024 half-years, banks 1-5 lose CET1."""
from __future__ import annotations

import json
from datetime import date

import numpy as np

_FEATURES = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
)
R0 = {"cet1": 0.07, "tier1": 0.085, "total_capital": 0.105}


def _row(bank_id, period, seed=0):
    rng = np.random.default_rng(seed + bank_id * 100 + period.year * 10 + period.month)
    r = {"bank_id": bank_id, "period": period}
    for name in _FEATURES:
        r[name] = float(rng.uniform(0.09, 0.20))
    r["cet1_ratio"] = float(rng.uniform(0.09, 0.18))
    r["tier1_ratio"] = float(rng.uniform(0.10, 0.20))
    r["total_capital_ratio"] = float(rng.uniform(0.12, 0.22))
    # Banks 1-5: gradual CET1 decline to generate E2 positives
    if bank_id <= 5 and period.year >= 2016:
        r["cet1_ratio"] = max(0.08, r["cet1_ratio"] - (period.year - 2015) * 0.008)
    return r


def _make_panel(n_banks=10):
    rows = []
    for b in range(1, n_banks + 1):
        for year in range(2014, 2025):
            for month in (6, 12):
                rows.append(_row(b, date(year, month, 30), seed=b))
    return rows


def _dataset(rows):
    import hashlib
    X = np.asarray([[r.get(f) or 0.0 for f in _FEATURES] for r in rows], dtype=float)
    ph = hashlib.sha256(
        json.dumps([(r["bank_id"], r["period"].isoformat()) for r in rows],
                   default=str).encode()).hexdigest()
    return {"rows": rows, "X": X, "columns": list(_FEATURES),
            "panel_hash": ph, "grid": "semiannual", "robustness": True}


def _two_configs(name, space="table35"):
    """Minimal 2-config version of _search_configs for fast tests."""
    if name == "LR":
        return [{"penalty": "l2", "solver": "liblinear", "C": 0.1},
                {"penalty": "l1", "solver": "liblinear", "C": 1.0}]
    if name == "RF":
        return [{"max_depth": 3, "min_samples_leaf": 2, "max_features": "sqrt"},
                {"max_depth": 5, "min_samples_leaf": 1, "max_features": "log2"}]
    return [{"n_estimators": 50, "max_depth": 3, "learning_rate": 0.1,
             "subsample": 0.8, "colsample_bytree": 0.8, "reg_lambda": 1.0},
            {"n_estimators": 50, "max_depth": 4, "learning_rate": 0.05,
             "subsample": 0.9, "colsample_bytree": 0.9, "reg_lambda": 0.1}]


_PANEL_COLUMNS = ("cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
                  "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi", "sovereign_hhi",
                  "loan_growth_qoq", "loan_growth_yoy")


def seed_panel(cur) -> int:
    """Insert 10 synthetic banks, one active dataset_version per period, one panel_row per bank/period.

    Returns the import_id of the synthetic import batch. Remove with `clear_panel`.
    """
    cur.execute("INSERT INTO import_batch(status, edition_label) VALUES ('loaded','SYN') RETURNING import_id")
    import_id = cur.fetchone()[0]
    banks = {}
    for b in range(1, 11):
        cur.execute("INSERT INTO bank(lei, name) VALUES (%s, %s) RETURNING bank_id",
                    (f"SYNTHETICBANK{b:07d}", f"syn{b}"))
        banks[b] = cur.fetchone()[0]
    versions = {}
    for row in _make_panel():
        period = row["period"]
        if period not in versions:
            cur.execute("""INSERT INTO dataset_version(year, quarter, period_end, import_id, version_no, is_active)
                           VALUES (%s,%s,%s,%s,1,true) RETURNING version_id""",
                        (period.year, (period.month - 1) // 3 + 1, period, import_id))
            versions[period] = cur.fetchone()[0]
        cur.execute(f"INSERT INTO panel_row(version_id, bank_id, flags, {', '.join(_PANEL_COLUMNS)}) "
                    f"VALUES (%s,%s,%s,{', '.join(['%s'] * len(_PANEL_COLUMNS))})",
                    (versions[period], banks[row["bank_id"]], json.dumps({}),
                     *[row[f] for f in _PANEL_COLUMNS]))
    return import_id


def clear_panel(cur) -> None:
    """Delete what seed_panel inserted."""
    cur.execute("TRUNCATE import_batch CASCADE")
    cur.execute("DELETE FROM bank WHERE lei LIKE 'SYNTHETICBANK%'")
