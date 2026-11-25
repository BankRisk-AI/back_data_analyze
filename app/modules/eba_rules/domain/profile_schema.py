"""Strict schema of an alert profile: unknown keys, wrong types and missing fields are errors."""
from __future__ import annotations

from typing import Any

FEATURES = {
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
}
RULE_TYPES = {"level", "trend", "persistence", "relative", "composite_score"}
STATUS = {"verified", "to_verify"}
PROFILE_KEYS = {"profile", "version", "frozen", "description", "defaults", "rules", "conversion"}
DEFAULT_KEYS = {"composite_logic", "weights", "null_input", "specialist_institution",
                "series_break", "frequency", "alert_levels", "sources"}
RULE_KEYS = {"id", "type", "feature", "condition", "threshold", "severity", "weight", "source",
             "status", "family", "bands", "percentile", "periods", "consecutive_periods",
             "cutoffs", "weights_from", "note"}


def _check_keys(found: set, allowed: set, where: str) -> None:
    unknown = sorted(found - allowed)
    if unknown:
        raise ValueError(f"{where}: unknown keys {unknown}")


def _validate_rule(rule: Any, ids: set[str]) -> None:
    """Validate one rule mapping; adds its id to ids."""
    if not isinstance(rule, dict):
        raise ValueError("each rule must be a mapping")
    rule_id = rule.get("id")
    if not isinstance(rule_id, str) or not rule_id or rule_id in ids:
        raise ValueError(f"invalid or duplicate rule id: {rule_id!r}")
    ids.add(rule_id)
    _check_keys(set(rule), RULE_KEYS, f"rule {rule_id}")
    kind = rule.get("type")
    if kind not in RULE_TYPES:
        raise ValueError(f"{rule_id}: unsupported rule type {kind!r}")
    if rule.get("status") not in STATUS:
        raise ValueError(f"{rule_id}: status must be verified or to_verify")
    if not rule.get("source"):
        raise ValueError(f"{rule_id}: source is required")
    if kind == "composite_score":
        _validate_composite(rule)
    else:
        _validate_component(rule, kind)


def _validate_component(rule: dict, kind: str) -> None:
    rule_id = rule["id"]
    if rule.get("feature") not in FEATURES:
        raise ValueError(f"{rule_id}: unsupported feature")
    has_threshold = (rule.get("threshold") is not None or rule.get("bands")
                     or (kind == "relative" and rule.get("percentile") is not None))
    if not has_threshold and rule["status"] == "verified":
        raise ValueError(f"{rule_id}: verified rule needs a threshold")
    weight = rule.get("weight")
    if weight is not None and (not isinstance(weight, (int, float)) or weight < 0):
        raise ValueError(f"{rule_id}: weight must be non-negative")
    if kind == "trend" and rule.get("periods") not in {2, 4}:
        raise ValueError(f"{rule_id}: trend periods must be 2 or 4")
    if kind == "persistence" and not isinstance(rule.get("consecutive_periods"), int):
        raise ValueError(f"{rule_id}: consecutive_periods is required")


def _validate_composite(rule: dict) -> None:
    cutoffs = rule.get("cutoffs")
    if (not isinstance(cutoffs, dict) or not {"green", "amber", "red"} <= cutoffs.keys()) \
            and rule["status"] == "verified":
        raise ValueError(f"{rule['id']}: composite cutoffs are required")


def validate_profile(profile: dict[str, Any]) -> None:
    """Raise ValueError unless the profile follows the schema (exactly one composite rule)."""
    if not isinstance(profile, dict) or not profile.get("profile"):
        raise ValueError("profile must define a non-empty profile name")
    _check_keys(set(profile), PROFILE_KEYS, "profile")
    if isinstance(profile.get("defaults"), dict):
        _check_keys(set(profile["defaults"]), DEFAULT_KEYS, "profile defaults")
    rules = profile.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("profile rules must be a non-empty list")
    ids: set[str] = set()
    for rule in rules:
        _validate_rule(rule, ids)
    if sum(rule["type"] == "composite_score" for rule in rules) != 1:
        raise ValueError("profile must contain exactly one composite_score rule")
