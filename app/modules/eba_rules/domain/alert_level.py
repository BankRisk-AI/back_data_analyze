"""From rule results to family scores to the alert level (family_max composite, profile eu_eba v1.1).

Each family scores its highest triggered severity; a regulatory breach (severity 3) or two
families with severity >= 2 give red; a summed score >= 2 gives amber; otherwise green.
"""
from __future__ import annotations

from typing import Any

from app.modules.eba_rules.domain.rule_evaluation import (
    PanelIndex, evaluate_rule, rule_family, rule_severity)

FAMILIES = ("capital", "asset_quality", "profitability", "dynamics")
REQUIRED_INPUTS = ("cet1_ratio", "tier1_ratio", "total_capital_ratio")   # a row without them is never rated


def rule_result(rule: dict[str, Any], row: dict[str, Any], index: PanelIndex) -> dict[str, Any]:
    """Serialisable result of one rule on one row (stored in alert.rule_results)."""
    outcome = evaluate_rule(rule, row, index)
    value = row.get(rule["feature"])
    severity = rule_severity(rule, value, outcome.triggered) if outcome.triggered else 0
    result = {"rule_id": rule["id"], "input_value": value, "triggered": outcome.triggered,
              "not_evaluated": outcome.not_evaluated, "input_flags": outcome.input_flags,
              "threshold": outcome.threshold, "severity": severity, "family": rule_family(rule)}
    if rule["type"] == "trend":   # the tested quantity is the change; the level stays in feature_value
        result.update(input_value=outcome.tested_value, feature_value=value)
    return result


def family_scores(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per family: highest severity among evaluated rules and the rule that gave it."""
    scores: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        evaluated = [r for r in results if r["family"] == family and not r["not_evaluated"]]
        if not evaluated:
            scores[family] = {"score": 0, "rule_id": None, "not_evaluated": True}
        else:
            best = max(evaluated, key=lambda r: r["severity"])
            scores[family] = {"score": best["severity"], "rule_id": best["rule_id"],
                              "not_evaluated": False}
    return scores


def alert_level(scores: dict[str, dict[str, Any]], is_specialist: bool,
                missing_inputs: list[str] | None = None) -> tuple[str, str, float | None]:
    """(level, reason, score) from the family scores; missing required inputs never give green."""
    scored = {f: d for f, d in scores.items() if not d["not_evaluated"]}
    score = float(sum(d["score"] for d in scored.values())) if scored else None
    regulatory = next((d["rule_id"] for d in scores.values() if d["score"] == 3 and d["rule_id"]), None)
    severe = sorted(f for f, d in scores.items() if d["score"] >= 2)
    if is_specialist:
        return "not_evaluated", "specialist_excluded", None
    if missing_inputs:
        return "not_evaluated", "required_input_missing:" + ",".join(missing_inputs), None
    if not scored:
        return "not_evaluated", "all_families_not_evaluated", score
    if regulatory:
        return "red", f"regulatory_breach:{regulatory}", score
    if len(severe) >= 2:
        return "red", f"two_families:{','.join(severe)}", score
    if score >= 2:
        return "amber", "family_score:" + ",".join(f for f, d in scores.items() if d["score"]), score
    return "green", "no_material_family_trigger", score


def evaluate_rows(profile: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Alert result for every panel row: bank_id, dataset_version, score, level, rule_results."""
    rules = profile["rules"]
    composite = next(rule for rule in rules if rule["type"] == "composite_score")
    components = [rule for rule in rules if rule["type"] != "composite_score"]
    index = PanelIndex.build(rows)
    results = []
    for row in rows:
        rule_results = [rule_result(rule, row, index) for rule in components]
        scores = family_scores(rule_results)
        missing = [name for name in REQUIRED_INPUTS if row.get(name) is None]
        level, reason, score = alert_level(scores, row["bank_id"] in index.specialists, missing)
        composite_result = {"rule_id": composite["id"], "input_value": score,
                            "triggered": level in {"amber", "red"},
                            "not_evaluated": level == "not_evaluated", "input_flags": [],
                            "threshold": None, "severity": 0, "family": None}
        results.append({"bank_id": row["bank_id"], "dataset_version": row["dataset_version"],
                        "score": score, "level": level,
                        "rule_results": {"rules": rule_results + [composite_result],
                                         "family_scores": scores, "level_reason": reason}})
    return results
