"""Versioned owner decisions for known source-data conflicts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class DataDecision:
    id: str
    edition: str
    file_type: str
    lei: str
    period: str
    item: str
    dimensions: dict[str, str]
    action: str
    amount: str | None
    reason: str
    source: str
    decided_by: str
    decided_on: str


def load_data_decisions() -> list[DataDecision]:
    path = Path(__file__).resolve().parents[2] / "config" / "data_decisions.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [DataDecision(
        id=str(row["id"]), edition=str(row["edition"]), file_type=str(row["file_type"]),
        lei=str(row["lei"]), period=str(row["period"]), item=str(row["item"]),
        dimensions={str(k): str(v) for k, v in (row.get("dimensions") or {}).items()},
        action=str(row["action"]), amount=None if row.get("amount") is None else str(row["amount"]),
        reason=str(row["reason"]), source=str(row["source"]), decided_by=str(row["decided_by"]),
        decided_on=str(row["decided_on"]),
    ) for row in raw.get("decisions", [])]


def decision_matches_row(decision: DataDecision, row: dict[str, object]) -> bool:
    if any(str(row.get(key) or "").strip() != value for key, value in {
        "lei_code": decision.lei, "period": decision.period, "item": decision.item,
        **decision.dimensions,
    }.items()):
        return False
    return decision.amount is None or str(row.get("amount") or "").strip() == decision.amount
