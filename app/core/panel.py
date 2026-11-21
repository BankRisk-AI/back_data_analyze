"""Build the derived panel row table from active facts."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import yaml
from psycopg2.extras import Json

FLAG_NAMES = {
    "missing_in_source", "invalid_denominator", "not_applicable_before_ifrs9",
    "template_gap", "not_reported_this_period", "fiscal_year_assumed",
    "denominator_missing", "fiscal_year_mismatch", "no_prior_period",
    "bank_entry_exit", "lei_change", "identity_crosswalk", "missing_sector",
    "outlier", "group_crosswalk",
    "extreme_growth", "implausible_value", "specialist_institution",
    "series_break",
}


def _specialist_leis(root: Path) -> set[str]:
    path = root / "specialist_institutions.yaml"
    if not path.exists():
        return set()
    return {str(item["lei"]).strip() for item in yaml.safe_load(path.read_text(encoding="utf-8")) or []}


def _approved_crosswalks(root: Path) -> dict[str, str]:
    path = root / "bank_crosswalk.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    result = {}
    for item in (data or {}).get("crosswalks", []):
        if item.get("status") == "approved":
            for member in item.get("members", []):
                result[str(member["lei"]).strip()] = item["group_id"]
    return result


FEATURES = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "npl_ratio", "stage2_share", "roe_annualised", "loan_growth_qoq",
    "loan_growth_yoy", "nace_hhi", "sovereign_hhi",
)


def _month_key(period):
    return period.year, period.month


def _subtract_months(period, months):
    index = period.year * 12 + period.month - 1 - months
    return index // 12, index % 12 + 1


def growth_rate(current, prior):
    """Return growth only when both loan observations are positive."""
    if current is None or prior is None or current <= 0 or prior <= 0:
        return None
    return current / prior - 1


def is_quarter_pair(current_period, prior_period, prior_frequency):
    return (
        current_period >= __import__("datetime").date(2018, 12, 1)
        and prior_frequency == "quarterly"
        and _month_key(prior_period) == _subtract_months(current_period, 3)
    )


def crosses_series_break(current_period, prior_period, break_period):
    """Return whether a change compares observations on opposite definitions."""
    return prior_period < break_period <= current_period


def annualise_profit(amount: float | None, n_quarters: int | None, period_month: int,
                     fin_end_year: str | None) -> tuple[float | None, bool]:
    if amount is None:
        return None, False
    assumed = n_quarters is None or not fin_end_year
    quarters = n_quarters or ({6: 2, 12: 4}.get(period_month, {3: 1, 9: 3}.get(period_month, 1)))
    return amount * 4 / quarters, assumed


def hhi(values: list[float]) -> float | None:
    positive = [value for value in values if value >= 0]
    total = sum(positive)
    if total <= 0:
        return None
    return sum((value / total) ** 2 for value in positive)


def _config_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.yaml")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _dimension_codes(root: Path, edition: str, sheet: str, text: str,
                     exact: bool = False) -> set[str]:
    path = root / f"{edition}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    entries = (data or {}).get("dimensions", {}).get(sheet, {})
    return {
        str(code) for code, value in entries.items()
        if (str(value.get("label", "")).strip().casefold() == text.casefold()
            if exact else text.casefold() in str(value.get("label", "")).casefold())
    }


def _flags() -> dict[str, list[str]]:
    return {feature: [] for feature in FEATURES}


def _add_flag(flags: dict[str, list[str]], feature: str, flag: str) -> None:
    if flag not in FLAG_NAMES:
        raise ValueError(f"unknown panel flag: {flag}")
    if flag not in flags[feature]:
        flags[feature].append(flag)


def _outliers(rows: list[dict], feature: str, k: float = 3,
              transform: str = "raw") -> None:
    if transform not in {"raw", "log"}:
        raise ValueError("outlier transform must be 'raw' or 'log'")
    values = [row[feature] for row in rows if row[feature] is not None]
    if transform == "log":
        values = [math.log(value) for value in values if value > 0]
    if len(values) < 20:
        return
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    if mad == 0:
        return
    for row in rows:
        value = row[feature]
        comparison = math.log(value) if transform == "log" and value > 0 else value
        if transform == "log" and (value is None or value <= 0):
            continue
        if comparison is not None and abs(comparison - median) > k * mad:
            row["_flags"][feature].append("outlier")


def _first(rows, key, predicate=lambda row: True):
    values = [row[key] for row in rows if predicate(row) and row[key] is not None]
    return values[0] if values else None


def build_panel(conn, dimensions_root: str | Path = "config/dimensions",
                dictionary_root: str | Path = "config", outlier_k: float = 3,
                outlier_transform: str = "raw") -> int:
    """Rebuild ``panel_row`` from active versions in one transaction."""
    dimensions = Path(dimensions_root)
    specialist_leis = _specialist_leis(Path(dictionary_root))
    crosswalk_leis = _approved_crosswalks(Path(dictionary_root))
    provenance = {
        "active_version_ids": [],
        "configuration_sha256": _config_hash(Path(dictionary_root)),
        "builder": "core.panel",
    }
    with conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT v.version_id, v.period_end, v.year, v.quarter,
                i.edition_label FROM dataset_version v
                JOIN import_batch i ON i.import_id=v.import_id
                WHERE v.is_active ORDER BY v.period_end""")
            versions = cur.fetchall()
            provenance["active_version_ids"] = [row[0] for row in versions]
            if not versions:
                cur.execute("DELETE FROM panel_row")
                return 0
            version_ids = tuple(row[0] for row in versions)
            cur.execute("""SELECT version_id, bank_id FROM (
                SELECT version_id, bank_id FROM fact_oth WHERE version_id = ANY(%s)
                UNION SELECT version_id, bank_id FROM fact_cre WHERE version_id = ANY(%s)
                UNION SELECT version_id, bank_id FROM fact_mrk WHERE version_id = ANY(%s)
                UNION SELECT version_id, bank_id FROM fact_sov WHERE version_id = ANY(%s)
            ) x ORDER BY version_id, bank_id""",
                        (list(version_ids),) * 4)
            keys = cur.fetchall()
            rows = [{"version_id": version_id, "bank_id": bank_id} for version_id, bank_id in keys]
            by_key = {(row["version_id"], row["bank_id"]): row for row in rows}
            for row in rows:
                row["_flags"] = _flags()
                row["flags"] = {}
            period_by_version = {row[0]: row[1] for row in versions}
            year_by_version = {row[0]: row[2] for row in versions}
            quarter_by_version = {row[0]: row[3] for row in versions}
            edition_by_version = {row[0]: row[4] for row in versions}
            cur.execute("SELECT bank_id, lei FROM bank")
            bank_leis = {bank_id: lei.strip() for bank_id, lei in cur.fetchall()}
            bank_groups = {bank_id: crosswalk_leis.get(lei) for bank_id, lei in bank_leis.items()}
            for row in rows:
                group_id = bank_groups.get(row["bank_id"])
                row["continuity_key"] = group_id or str(row["bank_id"])
                if group_id:
                    for feature in FEATURES:
                        _add_flag(row["_flags"], feature, "group_crosswalk")
            specialist_banks = {
                bank_id for bank_id, lei in bank_leis.items() if lei in specialist_leis
            }
            for row in rows:
                if row["bank_id"] in specialist_banks:
                    for feature in FEATURES:
                        _add_flag(row["_flags"], feature, "specialist_institution")

            cur.execute("SELECT indicator_id,std_code FROM indicator")
            codes = {indicator_id: code for indicator_id, code in cur.fetchall()}
            ids = {code: indicator_id for indicator_id, code in codes.items()}
            needed_oth = [ids.get(code) for code in (
                "2520140", "2520141", "2520142", "2520905", "2520335",
                "2520102", "2520901", "2520903", "2521017", "2521019")]
            needed_cre = [ids.get(code) for code in ("2520603", "2521301")]
            needed_sov = [ids.get(code) for code in (
                "1820802", "1820810", "2520810")]

            def relevant(query, params=()):
                cur.execute(query, params)
                return cur.fetchall()

            oth = relevant("""SELECT version_id,bank_id,indicator_id,amount,n_quarters,fin_end_year,
                assets_stages,assets_fv,exposure,financial_instruments FROM fact_oth
                WHERE version_id=ANY(%s) AND indicator_id=ANY(%s)""",
                           (list(version_ids), needed_oth))
            cre = relevant("""SELECT version_id,bank_id,indicator_id,amount,portfolio,country,
                country_rank,exposure,status,perf_status,nace_codes FROM fact_cre
                WHERE version_id=ANY(%s) AND indicator_id=ANY(%s)""",
                           (list(version_ids), needed_cre))
            sov = relevant("""SELECT version_id,bank_id,indicator_id,sum(amount),country,
                NULL::text,NULL::text FROM fact_sov
                WHERE version_id=ANY(%s) AND indicator_id=ANY(%s)
                GROUP BY version_id,bank_id,indicator_id,country""",
                           (list(version_ids), needed_sov))

            def facts(source, code):
                indicator_id = ids.get(code)
                return [row for row in source if row[2] == indicator_id]

            def keyed(source, code):
                result = defaultdict(list)
                for item in facts(source, code):
                    result[(item[0], item[1])].append(item)
                return result

            capital = {code: keyed(oth, code) for code in ("2520140", "2520141", "2520142", "2520905")}
            loans = keyed(cre, "2520603")
            profit = keyed(oth, "2520335")
            cet1 = keyed(oth, "2520102")
            leverage_tier1 = keyed(oth, "2520901")
            leverage_exposure = keyed(oth, "2520903")
            stage = defaultdict(list)
            for code in ("2521017", "2521019"):
                for key, items in keyed(oth, code).items():
                    stage[key].extend(items)
            nace = keyed(cre, "2521301")
            sov_by_code = {code: keyed(sov, code) for code in ("1820802", "1820810", "2520810")}
            dimension_cache = {}

            def dimension_codes(edition, sheet, text, exact=False):
                cache_key = (edition, sheet, text, exact)
                if cache_key not in dimension_cache:
                    dimension_cache[cache_key] = _dimension_codes(dimensions, edition, sheet, text, exact)
                return dimension_cache[cache_key]
            for row in rows:
                key = (row["version_id"], row["bank_id"])
                period = period_by_version[row["version_id"]]
                month = period.month
                row["frequency"] = "semi_annual" if period <= __import__("datetime").date(2018, 6, 30) else "quarterly"
                for feature, code in (("cet1_ratio", "2520140"), ("tier1_ratio", "2520141"),
                                      ("total_capital_ratio", "2520142"), ("leverage_ratio", "2520905")):
                    value = _first(capital[code].get(key, []), 3)
                    if feature == "leverage_ratio" and value == 0:
                        numerator = _first(leverage_tier1.get(key, []), 3)
                        exposure = _first(leverage_exposure.get(key, []), 3)
                        if not numerator or not exposure:
                            value = None
                            _add_flag(row["_flags"], feature, "implausible_value")
                    row[feature] = value
                    if value is None:
                        _add_flag(row["_flags"], feature, "missing_in_source")
                total_loans = [x for x in loans.get(key, [])
                               if all((x[i] or "0") == "0" for i in (4, 5, 6, 7, 8))]
                if year_by_version[key[0]] == 2016:
                    edition = edition_by_version[key[0]]
                    total_codes = dimension_codes(edition, "Perf_status", "No breakdown")
                    npl_codes = dimension_codes(edition, "Perf_status", "Non Performing", exact=True)
                    denom = sum(x[3] or 0 for x in total_loans if x[9] in total_codes)
                    numer = sum(x[3] or 0 for x in total_loans if x[9] in npl_codes and x[9] not in total_codes)
                    row["npl_ratio"] = numer / denom if denom > 0 else None
                    if row["npl_ratio"] is None:
                        _add_flag(row["_flags"], "npl_ratio", "template_gap")
                    else:
                        _add_flag(row["_flags"], "npl_ratio", "series_break")
                else:
                    edition = edition_by_version[key[0]]
                    total_codes = dimension_codes(edition, "Perf_status", "No breakdown")
                    npl_codes = dimension_codes(edition, "Perf_status", "Non Performing", exact=True)
                    denom = sum(x[3] or 0 for x in total_loans if x[9] in total_codes)
                    numer = sum(x[3] or 0 for x in total_loans if x[9] in npl_codes and x[9] not in total_codes)
                    row["npl_ratio"] = numer / denom if denom > 0 else None
                    if row["npl_ratio"] is None:
                        _add_flag(row["_flags"], "npl_ratio", "invalid_denominator")
                    elif period < __import__("datetime").date(2020, 6, 30):
                        _add_flag(row["_flags"], "npl_ratio", "series_break")
                stages = stage.get(key, [])
                if period < __import__("datetime").date(2018, 9, 1):
                    row["stage2_share"] = None
                    _add_flag(row["_flags"], "stage2_share", "not_applicable_before_ifrs9")
                else:
                    edition = edition_by_version[key[0]]
                    stage_codes = {
                        code: dimension_codes(edition, "ASSETS_Stages", label)
                        for code, label in (("1", "Stage 1:"), ("2", "Stage 2:"), ("3", "Stage 3:"))
                    }
                    denominator = sum(x[3] or 0 for x in stages if any(x[6] in values for values in stage_codes.values()))
                    numerator = sum(x[3] or 0 for x in stages if x[6] in stage_codes["2"])
                    row["stage2_share"] = numerator / denominator if denominator > 0 else None
                    if row["stage2_share"] is None:
                        _add_flag(row["_flags"], "stage2_share", "template_gap")
                p_rows = profit.get(key, [])
                p = _first(p_rows, 3)
                cp = _first(cet1.get(key, []), 3)
                nq = _first(p_rows, 4)
                fy = _first(p_rows, 5)
                annual, assumed = annualise_profit(p, nq, month, fy)
                row["roe_annualised"] = annual / cp if annual is not None and cp else None
                if assumed:
                    _add_flag(row["_flags"], "roe_annualised", "fiscal_year_assumed")
                if row["roe_annualised"] is None:
                    _add_flag(row["_flags"], "roe_annualised", "denominator_missing")
                total_codes = dimension_codes(edition_by_version[key[0]], "Perf_status", "No breakdown")
                nrows = [x for x in nace.get(key, []) if x[9] in total_codes and x[10] not in (None, "0")]
                row["nace_hhi"] = hhi([x[3] or 0 for x in nrows])
                if row["nace_hhi"] is None:
                    _add_flag(row["_flags"], "nace_hhi", "template_gap")
                # Sovereign country HHI uses the verified old/new item identity.
                sov_code = "1820802" if year_by_version[key[0]] <= 2017 else ("1820810" if year_by_version[key[0]] == 2018 else "2520810")
                srows = [x for x in sov_by_code[sov_code].get(key, []) if x[4] not in (None, "0")]
                row["sovereign_hhi"] = hhi([x[3] or 0 for x in srows]) if period.month in (6, 12) else None
                row["sovereign_template"] = "pre2019" if year_by_version[key[0]] <= 2018 else "2019plus"
                if period.month not in (6, 12):
                    _add_flag(row["_flags"], "sovereign_hhi", "not_reported_this_period")
                elif row["sovereign_hhi"] is None:
                    _add_flag(row["_flags"], "sovereign_hhi", "template_gap")
                row["_loan"] = sum(
                    x[3] or 0 for x in total_loans if x[9] in total_codes
                )
            # Continuity-derived features.
            ordered = sorted(rows, key=lambda x: (x["continuity_key"], period_by_version[x["version_id"]]))
            previous = {}
            by_period = {
                (row["continuity_key"], (period_by_version[row["version_id"]].year,
                                         period_by_version[row["version_id"]].month)): row
                for row in rows
            }

            def prior_period(period, years=0, months=0):
                return _subtract_months(period, years * 12 + months)

            for row in ordered:
                bank = row["continuity_key"]
                prior = previous.get(bank)
                period = period_by_version[row["version_id"]]
                immediate = prior if (
                    prior and is_quarter_pair(
                        period, period_by_version[prior["version_id"]],
                        prior["frequency"],
                    )
                ) else None
                annual_prior = by_period.get((bank, prior_period(period, years=1)))
                break_period = __import__("datetime").date(2020, 6, 30)
                crosses_qoq_break = immediate and crosses_series_break(
                    period, period_by_version[immediate["version_id"]], break_period)
                crosses_yoy_break = annual_prior and crosses_series_break(
                    period, period_by_version[annual_prior["version_id"]], break_period)
                if immediate and row["frequency"] == "quarterly":
                    if crosses_qoq_break:
                        row["loan_growth_qoq"] = None
                        _add_flag(row["_flags"], "loan_growth_qoq", "series_break")
                    else:
                        row["loan_growth_qoq"] = growth_rate(row["_loan"], immediate["_loan"])
                        if period < break_period:
                            _add_flag(row["_flags"], "loan_growth_qoq", "series_break")
                    row["npl_delta_qoq"] = (
                        row["npl_ratio"] - immediate["npl_ratio"]
                        if row["npl_ratio"] is not None and immediate["npl_ratio"] is not None else None)
                    row["cet1_delta_qoq"] = (
                        row["cet1_ratio"] - immediate["cet1_ratio"]
                        if row["cet1_ratio"] is not None and immediate["cet1_ratio"] is not None else None)
                else:
                    row["loan_growth_qoq"] = None
                    row["npl_delta_qoq"] = None
                    row["cet1_delta_qoq"] = None
                if crosses_yoy_break:
                    row["loan_growth_yoy"] = None
                    _add_flag(row["_flags"], "loan_growth_yoy", "series_break")
                elif (annual_prior and row["_loan"] is not None and row["_loan"] > 0
                        and annual_prior["_loan"] > 0):
                    row["loan_growth_yoy"] = growth_rate(row["_loan"], annual_prior["_loan"])
                    if period < break_period:
                        _add_flag(row["_flags"], "loan_growth_yoy", "series_break")
                    if row["loan_growth_yoy"] > 1:
                        _add_flag(row["_flags"], "loan_growth_yoy", "extreme_growth")
                else:
                    row["loan_growth_yoy"] = None
                    _add_flag(row["_flags"], "loan_growth_yoy", "no_prior_period")
                previous[bank] = row
            for feature in FEATURES:
                by_period_rows = defaultdict(list)
                for row in rows:
                    by_period_rows[row["version_id"]].append(row)
                for period_rows in by_period_rows.values():
                    _outliers(period_rows, feature, outlier_k, outlier_transform)
            cur.execute("DELETE FROM panel_row")
            for row in rows:
                flags = {"frequency": row.pop("frequency"), "sovereign_template": row.pop("sovereign_template")}
                row.pop("continuity_key", None)
                flags.update({feature: values for feature, values in row.pop("_flags").items() if values})
                values = [row.get(column) for column in (
                    "version_id", "bank_id", "cet1_ratio", "tier1_ratio", "total_capital_ratio",
                    "leverage_ratio", "npl_ratio", "stage2_share", "roe_annualised",
                    "nace_hhi", "sovereign_hhi", "npl_delta_qoq", "loan_growth_qoq",
                    "loan_growth_yoy", "cet1_delta_qoq")]
                cur.execute("""INSERT INTO panel_row
                    (version_id,bank_id,cet1_ratio,tier1_ratio,total_capital_ratio,leverage_ratio,
                     npl_ratio,stage2_share,roe_annualised,nace_hhi,sovereign_hhi,npl_delta_qoq,
                     loan_growth_qoq,loan_growth_yoy,cet1_delta_qoq,min_headroom,indicators,flags,build_provenance)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s)""",
                            (*values, Json({}), Json(flags), Json(provenance)))
            cur.execute("SELECT model_id FROM ml_model WHERE status='champion'")
            champions = [model_id for (model_id,) in cur.fetchall()]
            if champions:
                cur.execute("INSERT INTO import_batch(status) VALUES ('uploaded') RETURNING import_id")
                import_id = cur.fetchone()[0]
                for model_id in champions:
                    cur.execute("""INSERT INTO job(import_id,kind,status,message)
                                   VALUES (%s,'score_panel','pending',%s)""",
                                (import_id, f"score_panel model={model_id}"))
            return len(rows)
