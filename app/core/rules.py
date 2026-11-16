"""Profile-driven evaluation of panel rows and atomic alert persistence."""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from psycopg2.extras import Json

FEATURES = {
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi",
    "sovereign_hhi", "loan_growth_qoq", "loan_growth_yoy",
}
RULE_TYPES = {"level", "trend", "persistence", "relative", "composite_score"}
STATUS = {"verified", "to_verify"}
BREAK_PERIOD = date(2020, 6, 30)


def load_profile(path: str | Path) -> tuple[dict[str, Any], str]:
    raw = Path(path).read_bytes()
    profile = yaml.safe_load(raw) or {}
    validate_profile(profile)
    return profile, hashlib.sha256(raw).hexdigest()


def validate_profile(profile: dict[str, Any]) -> None:
    if not isinstance(profile, dict) or not profile.get("profile"):
        raise ValueError("profile must define a non-empty profile name")
    rules = profile.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("profile rules must be a non-empty list")
    ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("each rule must be a mapping")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in ids:
            raise ValueError(f"invalid or duplicate rule id: {rule_id!r}")
        ids.add(rule_id)
        kind = rule.get("type")
        if kind not in RULE_TYPES:
            raise ValueError(f"{rule_id}: unsupported rule type {kind!r}")
        if rule.get("status") not in STATUS:
            raise ValueError(f"{rule_id}: status must be verified or to_verify")
        if not rule.get("source"):
            raise ValueError(f"{rule_id}: source is required")
        if kind != "composite_score":
            if rule.get("feature") not in FEATURES:
                raise ValueError(f"{rule_id}: unsupported feature")
            if (rule.get("threshold") is None and not rule.get("bands")
                    and not (kind == "relative" and rule.get("percentile") is not None)):
                if rule.get("status") == "verified":
                    raise ValueError(f"{rule_id}: verified rule needs a threshold")
            if rule.get("weight") is not None and (
                not isinstance(rule["weight"], (int, float)) or rule["weight"] < 0
            ):
                raise ValueError(f"{rule_id}: weight must be non-negative")
        if kind == "composite_score":
            cutoffs = rule.get("cutoffs")
            if not isinstance(cutoffs, dict) or not {"green", "amber", "red"} <= cutoffs.keys():
                if rule.get("status") == "verified":
                    raise ValueError(f"{rule_id}: composite cutoffs are required")
        if kind == "trend" and rule.get("periods") not in {2, 4}:
            raise ValueError(f"{rule_id}: trend periods must be 2 or 4")
        if kind == "persistence" and not isinstance(rule.get("consecutive_periods"), int):
            raise ValueError(f"{rule_id}: consecutive_periods is required")
    if sum(rule["type"] == "composite_score" for rule in rules) != 1:
        raise ValueError("profile must contain exactly one composite_score rule")


def _flags(row: dict[str, Any], feature: str) -> list[str]:
    return list((row.get("flags") or {}).get(feature) or [])


def _target_periods(periods: list[date], current: date, count: int) -> date | None:
    if current < date(2018, 9, 1):
        index = periods.index(current) - (2 if count == 4 else 1)
        return periods[index] if index >= 0 else None
    return date(current.year - 1, current.month, current.day) if count == 4 else None


def _condition(value: float, rule: dict[str, Any]) -> bool:
    condition = rule.get("condition")
    threshold = rule.get("threshold")
    if condition == "below":
        return value < threshold
    if condition == "above":
        return value > threshold
    if condition == "decrease_over":
        return value < -threshold
    if condition == "increase_over":
        return value > threshold
    raise ValueError(f"{rule['id']}: unsupported condition {condition!r}")


def _band(value: float, bands: dict[str, Any]) -> str:
    for name in ("red", "amber", "green"):
        bounds = bands.get(name) or {}
        if "below" in bounds and value < bounds["below"]:
            return name
        if "above" in bounds and value > bounds["above"]:
            return name
        if "min" in bounds and "max" in bounds and bounds["min"] <= value <= bounds["max"]:
            return name
    return "green"


def _family(rule: dict[str, Any]) -> str:
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


def _severity(rule: dict[str, Any], value: float | None, triggered: bool) -> int:
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
        return 2 if _band(value, rule["bands"]) == "red" else 1
    return 1


def evaluate_rows(profile: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluate rows already fetched from panel_row; useful for deterministic tests."""
    validate_profile(profile)
    rules = profile["rules"]
    composite = next(rule for rule in rules if rule["type"] == "composite_score")
    components = [rule for rule in rules if rule["type"] != "composite_score"]
    by_key = {(row["bank_id"], row["period"]): row for row in rows}
    periods = sorted({row["period"] for row in rows})
    specialists = {
        row["bank_id"] for row in rows
        if "specialist_institution" in (row.get("flags") or {}).get("cet1_ratio", [])
    }
    results: list[dict[str, Any]] = []
    families = ("capital", "asset_quality", "profitability", "dynamics")
    for row in rows:
        result_rules: list[dict[str, Any]] = []
        evaluated = 0
        for rule in components:
            feature = rule["feature"]
            value = row.get(feature)
            input_flags = _flags(row, feature)
            not_evaluated = value is None
            triggered = False
            threshold: Any = rule.get("threshold")
            if rule["type"] == "level":
                if not_evaluated:
                    pass
                elif rule.get("bands"):
                    threshold = rule["bands"]
                    triggered = _band(value, rule["bands"]) != "green"
                    evaluated += 1
                else:
                    triggered = _condition(value, rule)
                    evaluated += 1
            elif rule["type"] == "trend":
                prior_period = _target_periods(periods, row["period"], rule["periods"])
                prior = by_key.get((row["bank_id"], prior_period)) if prior_period else None
                prior_value = prior.get(feature) if prior else None
                not_evaluated = value is None or prior_value is None
                if prior and feature == "npl_ratio" and prior_period < BREAK_PERIOD <= row["period"]:
                    not_evaluated = True
                    input_flags = sorted(set(input_flags + _flags(prior, feature) + ["series_break"]))
                if not_evaluated:
                    threshold = rule.get("threshold")
                else:
                    threshold = rule["threshold"]
                    delta = value - prior_value
                    triggered = _condition(delta, rule)
                    evaluated += 1
            elif rule["type"] == "persistence":
                index = periods.index(row["period"])
                count = rule["consecutive_periods"]
                candidate_periods = periods[max(0, index - count + 1):index + 1]
                values = [
                    by_key.get((row["bank_id"], period), {}).get(feature)
                    for period in candidate_periods
                ]
                not_evaluated = len(values) != count or any(v is None for v in values)
                if feature == "npl_ratio" and any(
                    period < BREAK_PERIOD <= row["period"] for period in candidate_periods
                ):
                    not_evaluated = True
                    input_flags = sorted(set(input_flags + ["series_break"]))
                if not not_evaluated:
                    triggered = all(_condition(v, rule) for v in values)
                    evaluated += 1
            elif rule["type"] == "relative":
                eligible = [
                    other.get(feature) for other in rows
                    if other["period"] == row["period"]
                    and other["bank_id"] not in specialists
                    and other.get(feature) is not None
                ]
                if row["bank_id"] in specialists or not eligible:
                    not_evaluated = True
                else:
                    percentile = rule.get("percentile", 0.9)
                    eligible.sort()
                    cutoff = eligible[min(len(eligible) - 1, int((len(eligible) - 1) * percentile))]
                    threshold = cutoff
                    not_evaluated = value is None
                    if not not_evaluated:
                        triggered = value >= cutoff if percentile >= 0.5 else value <= cutoff
                        evaluated += 1
            if triggered:
                severity = _severity(rule, value, triggered)
            else:
                severity = 0
            result_rules.append({
                "rule_id": rule["id"], "input_value": value, "triggered": triggered,
                "not_evaluated": not_evaluated, "input_flags": input_flags,
                "threshold": threshold, "severity": severity, "family": _family(rule),
            })
        family_scores: dict[str, dict[str, Any]] = {}
        for family in families:
            family_rules = [
                result for result in result_rules
                if result["family"] == family and not result["not_evaluated"]
            ]
            if not family_rules:
                family_scores[family] = {"score": 0, "rule_id": None, "not_evaluated": True}
            else:
                best = max(family_rules, key=lambda result: result["severity"])
                family_scores[family] = {
                    "score": best["severity"], "rule_id": best["rule_id"],
                    "not_evaluated": False,
                }
        scored = {family: data for family, data in family_scores.items() if not data["not_evaluated"]}
        score_value = float(sum(data["score"] for data in scored.values())) if scored else None
        regulatory = next(
            (data["rule_id"] for family, data in family_scores.items()
             if data["score"] == 3 and data["rule_id"]),
            None,
        )
        severe_families = sorted(
            family for family, data in family_scores.items() if data["score"] >= 2
        )
        if row["bank_id"] in specialists:
            level, reason, score_value = "not_evaluated", "specialist_excluded", None
        elif not scored:
            level, reason = "not_evaluated", "all_families_not_evaluated"
        elif regulatory:
            level, reason = "red", f"regulatory_breach:{regulatory}"
        elif len(severe_families) >= 2:
            level, reason = "red", f"two_families:{','.join(severe_families)}"
        elif score_value >= 2:
            level, reason = "amber", "family_score:" + ",".join(
                family for family, data in family_scores.items() if data["score"]
            )
        else:
            level, reason = "green", "no_material_family_trigger"
        composite_result = {
            "rule_id": composite["id"], "input_value": score_value,
            "triggered": level in {"amber", "red"},
            "not_evaluated": level == "not_evaluated", "input_flags": [],
            "threshold": None, "severity": 0, "family": None,
        }
        results.append({
            "bank_id": row["bank_id"], "version_id": row["version_id"],
            "score": score_value, "level": level,
            "rule_results": {
                "rules": result_rules + [composite_result],
                "family_scores": family_scores,
                "level_reason": reason,
            },
        })
    return results


def evaluate_profile(conn, profile_path: str | Path, profile_name: str | None = None) -> int:
    profile, profile_sha256 = load_profile(profile_path)
    name = profile_name or profile["profile"]
    with conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT p.version_id, p.bank_id, v.period_end AS period,
                p.cet1_ratio, p.tier1_ratio, p.total_capital_ratio, p.leverage_ratio,
                p.npl_ratio, p.stage2_share, p.roe_annualised, p.nace_hhi,
                p.sovereign_hhi, p.loan_growth_qoq, p.loan_growth_yoy, p.flags
                FROM panel_row p JOIN dataset_version v USING (version_id)
                WHERE v.is_active ORDER BY v.period_end, p.bank_id""")
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, values)) for values in cur.fetchall()]
            evaluated = evaluate_rows(profile, rows)
            cur.execute("DELETE FROM alert WHERE profile_sha256=%s", (profile_sha256,))
            for result in evaluated:
                cur.execute("""INSERT INTO alert
                    (bank_id, version_id, profile_name, profile_sha256, score, level, rule_results)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""", (
                    result["bank_id"], result["version_id"], name, profile_sha256,
                    result["score"], result["level"], Json(result["rule_results"]),
                ))
    return len(evaluated)


def register_handler(registry, schema: str | None = None) -> None:
    from app.core.worker import JobHandlerRegistry

    def handle(job, progress) -> None:
        import os
        from app.core.database import connect

        profile_name = os.getenv("EBA_RULE_PROFILE", "eu_eba")
        path = Path("config/rules") / f"{profile_name}.yaml"
        progress(f"evaluating rules profile={profile_name}", 5)
        conn = connect(schema or job.schema)
        try:
            count = evaluate_profile(conn, path, profile_name)
        finally:
            conn.close()
        progress(f"evaluated {count} alerts", 99)

    if not isinstance(registry, JobHandlerRegistry):
        raise TypeError("registry must be a JobHandlerRegistry")
    registry.register("evaluate_rules", handle)
