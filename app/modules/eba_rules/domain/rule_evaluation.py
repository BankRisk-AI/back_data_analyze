"""Evaluate one profile rule on one panel row (thesis §3.4, Table 3.8; profile eu_eba v1.1).

A rule yields an outcome: triggered?, not evaluated?, the threshold actually used and the input
flags. Rule types: level (threshold or bands), trend (change over 2/4 periods), persistence
(condition in two consecutive half-years) and relative (percentile of the cross-section).
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any

BREAK_PERIOD = date(2020, 6, 30)   # NPL series break (definition change), thesis §3.2


@dataclass
class PanelIndex:
    """Lookups over all panel rows of an evaluation: by (bank, period), periods, specialists."""
    rows: list[dict[str, Any]]
    by_key: dict[tuple, dict[str, Any]]
    periods: list[date]
    specialists: set

    @classmethod
    def build(cls, rows: list[dict[str, Any]]) -> "PanelIndex":
        specialists = {row["bank_id"] for row in rows
                       if "specialist_institution" in (row.get("flags") or {}).get("cet1_ratio", [])}
        return cls(rows, {(r["bank_id"], r["period"]): r for r in rows},
                   sorted({r["period"] for r in rows}), specialists)


@dataclass
class Outcome:
    """Result of one rule on one row."""
    triggered: bool
    not_evaluated: bool
    threshold: Any
    input_flags: list[str]
    tested_value: float | None = None   # trend rules: the change that was compared with the threshold


def row_flags(row: dict[str, Any], feature: str) -> list[str]:
    """Quality flags of a feature value in a panel row."""
    return list((row.get("flags") or {}).get(feature) or [])


def _condition(value: float, rule: dict[str, Any]) -> bool:
    condition, threshold = rule.get("condition"), rule.get("threshold")
    if condition == "below":
        return value < threshold
    if condition == "above":
        return value > threshold
    if condition == "decrease_over":
        return value < -threshold
    if condition == "increase_over":
        return value > threshold
    raise ValueError(f"{rule['id']}: unsupported condition {condition!r}")


def band_of(value: float, bands: dict[str, Any]) -> str:
    """Band name (red, amber, green) of a value; green when no band matches."""
    for name in ("red", "amber", "green"):
        bounds = bands.get(name) or {}
        if "below" in bounds and value < bounds["below"]:
            return name
        if "above" in bounds and value > bounds["above"]:
            return name
        if "min" in bounds and "max" in bounds and bounds["min"] <= value <= bounds["max"]:
            return name
    return "green"


def _comparison_period(periods: list[date], current: date, count: int) -> date | None:
    """Period to compare with: index shift before 2018-09 (semi-annual), calendar year after."""
    if current < date(2018, 9, 1):
        index = periods.index(current) - (2 if count == 4 else 1)
        return periods[index] if index >= 0 else None
    return date(current.year - 1, current.month, current.day) if count == 4 else None


def _previous_half_year(period: date) -> date:
    """Last day of the month six months before period."""
    month, year = period.month - 6, period.year
    if month <= 0:
        month, year = month + 12, year - 1
    return date(year, month, calendar.monthrange(year, month)[1])


def _level(rule: dict, row: dict, value, flags: list[str]) -> Outcome:
    if value is None:
        return Outcome(False, True, rule.get("threshold"), flags)
    if rule.get("bands"):
        return Outcome(band_of(value, rule["bands"]) != "green", False, rule["bands"], flags)
    return Outcome(_condition(value, rule), False, rule.get("threshold"), flags)


def _trend(rule: dict, row: dict, value, flags: list[str], index: PanelIndex) -> Outcome:
    feature = rule["feature"]
    prior_period = _comparison_period(index.periods, row["period"], rule["periods"])
    prior = index.by_key.get((row["bank_id"], prior_period)) if prior_period else None
    prior_value = prior.get(feature) if prior else None
    not_evaluated = value is None or prior_value is None
    if prior and feature == "npl_ratio" and prior_period < BREAK_PERIOD <= row["period"]:
        not_evaluated = True
        flags = sorted(set(flags + row_flags(prior, feature) + ["series_break"]))
    if not_evaluated:
        return Outcome(False, True, rule.get("threshold"), flags)
    change = value - prior_value
    return Outcome(_condition(change, rule), False, rule["threshold"], flags, change)


def _persistence(rule: dict, row: dict, value, flags: list[str], index: PanelIndex) -> Outcome:
    feature = rule["feature"]
    prior_period = _previous_half_year(row["period"])
    prior = index.by_key.get((row["bank_id"], prior_period))
    values = [prior.get(feature) if prior else None, value]
    not_evaluated = prior is None or any(v is None for v in values)
    if feature == "npl_ratio" and prior and prior_period < BREAK_PERIOD <= row["period"]:
        not_evaluated = True
        flags = sorted(set(flags + ["series_break"]))
    triggered = (not not_evaluated) and all(_condition(v, rule) for v in values)
    return Outcome(triggered, not_evaluated, rule.get("threshold"), flags)


def _relative(rule: dict, row: dict, value, flags: list[str], index: PanelIndex) -> Outcome:
    feature = rule["feature"]
    eligible = [other.get(feature) for other in index.rows
                if other["period"] == row["period"] and other["bank_id"] not in index.specialists
                and other.get(feature) is not None]
    if row["bank_id"] in index.specialists or not eligible:
        return Outcome(False, True, rule.get("threshold"), flags)
    percentile = rule.get("percentile", 0.9)
    eligible.sort()
    cutoff = eligible[min(len(eligible) - 1, int((len(eligible) - 1) * percentile))]
    if value is None:
        return Outcome(False, True, cutoff, flags)
    triggered = value >= cutoff if percentile >= 0.5 else value <= cutoff
    return Outcome(triggered, False, cutoff, flags)


def evaluate_rule(rule: dict[str, Any], row: dict[str, Any], index: PanelIndex) -> Outcome:
    """Outcome of one non-composite rule on one panel row."""
    value = row.get(rule["feature"])
    flags = row_flags(row, rule["feature"])
    if rule["type"] == "level":
        return _level(rule, row, value, flags)
    if rule["type"] == "trend":
        return _trend(rule, row, value, flags, index)
    if rule["type"] == "persistence":
        return _persistence(rule, row, value, flags, index)
    return _relative(rule, row, value, flags, index)


def rule_family(rule: dict[str, Any]) -> str:
    """Family of a rule: explicit, else derived from the type and feature."""
    if rule.get("family"):
        return rule["family"]
    if rule.get("type") == "trend":
        return "dynamics"
    feature = rule.get("feature", "")
    if feature in {"cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio"}:
        return "capital"
    if feature == "npl_ratio":
        return "asset_quality"
    if feature == "roe_annualised":
        return "profitability"
    return "dynamics"


def rule_severity(rule: dict[str, Any], value: float | None, triggered: bool) -> int:
    """Severity of a triggered rule: 3 regulatory, 2 trend/persistence/red band, 1 otherwise."""
    if not triggered:
        return 0
    rule_id = rule["id"]
    if rule_id.endswith("_regulatory_min") or rule_id == "cet1_buffer_warning":
        return 3
    if rule["type"] == "relative":
        return 1
    if rule["type"] in {"trend", "persistence"}:
        return 2
    if rule_id == "leverage_supervisory_low":
        return 1
    if rule.get("bands") and value is not None:
        return 2 if band_of(value, rule["bands"]) == "red" else 1
    return 1
