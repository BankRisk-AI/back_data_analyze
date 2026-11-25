"""The single reader of `panel_row` and the active dataset versions.

`load_panel` returns one standard row per bank and period. ML (`eba_ml`), the rules (`eba_rules`)
and the public analysis API all start from it; each applies only its own documented adjustments.
`panel_hash` is the only definition of the hash that identifies a panel (training provenance).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

INDICATORS = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio", "npl_ratio",
    "stage2_share", "roe_annualised", "nace_hhi", "sovereign_hhi", "loan_growth_qoq",
    "loan_growth_yoy", "npl_delta_qoq", "cet1_delta_qoq", "min_headroom",
)
SPECIALIST_FLAG = "specialist_institution"

PANEL_QUERY = f"""SELECT p.bank_id, v.period_end, p.version_id, p.flags, {", ".join("p." + c for c in INDICATORS)}
    FROM panel_row p JOIN dataset_version v USING (version_id)
    WHERE v.is_active ORDER BY v.period_end, p.bank_id"""


@dataclass(frozen=True)
class PanelData:
    """The active panel: standard rows plus the hash of the whole panel."""
    rows: list[dict[str, Any]]
    panel_hash: str

    @property
    def version_ids(self) -> list[int]:
        """Active dataset versions present in the panel, in period order."""
        return list(dict.fromkeys(row["dataset_version"] for row in self.rows))


def panel_hash(rows: Sequence[dict[str, Any]], features: Sequence[str]) -> str:
    """SHA-256 of (bank_id, period, feature values) of the given rows; the one hash definition."""
    return hashlib.sha256(json.dumps(
        [(r["bank_id"], r["period"].isoformat(), [r[f] for f in features]) for r in rows],
        default=str, sort_keys=True).encode()).hexdigest()


def _standard_row(values: tuple) -> dict[str, Any]:
    bank_id, period, version_id, flags, *indicators = values
    flags = flags or {}
    row: dict[str, Any] = {"bank_id": bank_id, "period": period, "frequency": flags.get("frequency"),
                           "dataset_version": version_id, "flags": flags}
    row.update(zip(INDICATORS, indicators))
    row["is_specialist"] = SPECIALIST_FLAG in (flags.get("cet1_ratio") or [])
    return row


def load_panel(cur) -> PanelData:
    """Read the active panel with a cursor.

    Standard row: bank_id, period (date), frequency ('semi_annual'|'quarterly'), dataset_version
    (version_id), the 14 indicators of INDICATORS, flags (per feature lists: specialist_institution,
    outlier, series_break, ...; plus frequency/sovereign_template) and is_specialist.
    Ordered by period, then bank. Nothing is dropped, converted or filled.
    """
    cur.execute(PANEL_QUERY)
    rows = [_standard_row(values) for values in cur.fetchall()]
    return PanelData(rows, panel_hash(rows, INDICATORS))
