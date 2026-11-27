"""Build the derived panel row table from active facts."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from psycopg2.extras import Json

from app.core.hooks import PanelRebuilt, run_after_panel_rebuild
from app.core.specialists import specialist_leis

FLAG_NAMES = {
    "missing_in_source", "invalid_denominator", "not_applicable_before_ifrs9",
    "template_gap", "not_reported_this_period", "fiscal_year_assumed",
    "denominator_missing", "fiscal_year_mismatch", "no_prior_period",
    "bank_entry_exit", "lei_change", "identity_crosswalk", "missing_sector",
    "outlier", "group_crosswalk",
    "extreme_growth", "implausible_value", "specialist_institution",
    "series_break", "numerator_missing",
}


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


def loan_series_break(root: Path) -> date:
    """Loans series break date from `<root>/ml.yaml` (key `loan_series_break`, required)."""
    cfg = yaml.safe_load((root / "ml.yaml").read_text(encoding="utf-8")) or {}
    if "loan_series_break" not in cfg:
        raise KeyError(f"loan_series_break missing in {root / 'ml.yaml'}")
    return date.fromisoformat(str(cfg["loan_series_break"]))


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


@dataclass
class PanelContext:
    """Per-version lookups used while building rows: period, year, quarter, edition label, bank LEIs."""
    version_ids: list[int]
    period: dict[int, date]
    year: dict[int, int]
    edition: dict[int, str]
    bank_leis: dict[int, str]
    loan_break: date


@dataclass
class FactIndex:
    """Facts needed for the panel, indexed by (version_id, bank_id) per item."""
    capital: dict[str, dict]
    loans: dict
    profit: dict
    cet1: dict
    leverage_tier1: dict
    leverage_exposure: dict
    stage: dict
    nace: dict
    sov_by_code: dict[str, dict]


@dataclass
class PanelBuild:
    """Result of the in-memory build: rows ready to write and the provenance stored with them."""
    rows: list[dict]
    provenance: dict


def _active_versions(cur) -> list[tuple]:
    cur.execute("""SELECT v.version_id, v.period_end, v.year, v.quarter,
        i.edition_label FROM dataset_version v
        JOIN import_batch i ON i.import_id=v.import_id
        WHERE v.is_active ORDER BY v.period_end""")
    return cur.fetchall()


def _context(cur, versions: list[tuple], loan_break: date) -> PanelContext:
    cur.execute("SELECT bank_id, lei FROM bank")
    return PanelContext(
        version_ids=[row[0] for row in versions],
        period={row[0]: row[1] for row in versions},
        year={row[0]: row[2] for row in versions},
        edition={row[0]: row[4] for row in versions},
        bank_leis={bank_id: lei.strip() for bank_id, lei in cur.fetchall()},
        loan_break=loan_break)


def _base_rows(cur, ctx: PanelContext, crosswalk_leis: dict, specialists: set) -> list[dict]:
    """One row per (version, bank) with any fact; continuity key and the crosswalk/specialist flags."""
    cur.execute("""SELECT version_id, bank_id FROM (
        SELECT version_id, bank_id FROM fact_oth WHERE version_id = ANY(%s)
        UNION SELECT version_id, bank_id FROM fact_cre WHERE version_id = ANY(%s)
        UNION SELECT version_id, bank_id FROM fact_mrk WHERE version_id = ANY(%s)
        UNION SELECT version_id, bank_id FROM fact_sov WHERE version_id = ANY(%s)
    ) x ORDER BY version_id, bank_id""", (ctx.version_ids,) * 4)
    rows = [{"version_id": v, "bank_id": b, "_flags": _flags(), "flags": {}} for v, b in cur.fetchall()]
    for row in rows:
        group_id = crosswalk_leis.get(ctx.bank_leis.get(row["bank_id"]))
        row["continuity_key"] = group_id or str(row["bank_id"])
        if group_id:
            for feature in FEATURES:
                _add_flag(row["_flags"], feature, "group_crosswalk")
        if ctx.bank_leis.get(row["bank_id"]) in specialists:
            for feature in FEATURES:
                _add_flag(row["_flags"], feature, "specialist_institution")
    return rows


def _load_facts(cur, version_ids: list[int]) -> tuple[FactIndex, dict[str, int]]:
    """Read the facts of the needed items; returns the index and the std_code -> indicator_id map."""
    cur.execute("SELECT indicator_id,std_code FROM indicator")
    ids = {code: indicator_id for indicator_id, code in cur.fetchall()}
    needed = {
        "oth": ("2520140", "2520141", "2520142", "2520905", "2520335", "2520102", "2520901", "2520903",
                "2521017", "2521019"),
        "cre": ("2520603", "2521301"), "sov": ("1820802", "1820810", "2520810")}
    wanted = {group: [ids.get(code) for code in codes] for group, codes in needed.items()}
    cur.execute("""SELECT version_id,bank_id,indicator_id,amount,n_quarters,fin_end_year,
        assets_stages,assets_fv,exposure,financial_instruments FROM fact_oth
        WHERE version_id=ANY(%s) AND indicator_id=ANY(%s)""", (version_ids, wanted["oth"]))
    oth = cur.fetchall()
    cur.execute("""SELECT version_id,bank_id,indicator_id,amount,portfolio,country,
        country_rank,exposure,status,perf_status,nace_codes FROM fact_cre
        WHERE version_id=ANY(%s) AND indicator_id=ANY(%s)""", (version_ids, wanted["cre"]))
    cre = cur.fetchall()
    cur.execute("""SELECT version_id,bank_id,indicator_id,sum(amount),country,
        NULL::text,NULL::text FROM fact_sov
        WHERE version_id=ANY(%s) AND indicator_id=ANY(%s)
        GROUP BY version_id,bank_id,indicator_id,country""", (version_ids, wanted["sov"]))
    sov = cur.fetchall()

    def keyed(source, code):
        result = defaultdict(list)
        for item in source:
            if item[2] == ids.get(code):
                result[(item[0], item[1])].append(item)
        return result

    stage = defaultdict(list)
    for code in ("2521017", "2521019"):
        for key, items in keyed(oth, code).items():
            stage[key].extend(items)
    index = FactIndex(
        capital={code: keyed(oth, code) for code in ("2520140", "2520141", "2520142", "2520905")},
        loans=keyed(cre, "2520603"), profit=keyed(oth, "2520335"), cet1=keyed(oth, "2520102"),
        leverage_tier1=keyed(oth, "2520901"), leverage_exposure=keyed(oth, "2520903"),
        stage=stage, nace=keyed(cre, "2521301"),
        sov_by_code={code: keyed(sov, code) for code in ("1820802", "1820810", "2520810")})
    return index, ids


def _capital_ratios(row: dict, key: tuple, facts: FactIndex) -> None:
    """CET1, Tier 1, total capital and leverage ratios: copied from the reported items."""
    for feature, code in (("cet1_ratio", "2520140"), ("tier1_ratio", "2520141"),
                          ("total_capital_ratio", "2520142"), ("leverage_ratio", "2520905")):
        value = _first(facts.capital[code].get(key, []), 3)
        if feature == "leverage_ratio" and value == 0:
            numerator = _first(facts.leverage_tier1.get(key, []), 3)
            exposure = _first(facts.leverage_exposure.get(key, []), 3)
            if not numerator or not exposure:
                value = None
                _add_flag(row["_flags"], feature, "implausible_value")
        row[feature] = value
        if value is None:
            _add_flag(row["_flags"], feature, "missing_in_source")


def _total_loans(row: dict, key: tuple, facts: FactIndex) -> list:
    """Loan rows without any breakdown (portfolio, country, rank, exposure, status all '0')."""
    return [x for x in facts.loans.get(key, []) if all((x[i] or "0") == "0" for i in (4, 5, 6, 7, 8))]


def _npl_ratio(row: dict, total_loans: list, period: date, year: int, dimension_codes, edition: str) -> None:
    """NPL = 'Non Performing' / 'No breakdown' loans; flags the series break before 2020-06-30."""
    total_codes = dimension_codes(edition, "Perf_status", "No breakdown")
    npl_codes = dimension_codes(edition, "Perf_status", "Non Performing", exact=True)
    denom = sum(x[3] or 0 for x in total_loans if x[9] in total_codes)
    numer = sum(x[3] or 0 for x in total_loans if x[9] in npl_codes and x[9] not in total_codes)
    row["npl_ratio"] = numer / denom if denom > 0 else None
    if year == 2016:
        _add_flag(row["_flags"], "npl_ratio", "template_gap" if row["npl_ratio"] is None else "series_break")
    elif row["npl_ratio"] is None:
        _add_flag(row["_flags"], "npl_ratio", "invalid_denominator")
    elif period < date(2020, 6, 30):
        _add_flag(row["_flags"], "npl_ratio", "series_break")


def _stage2_share(row: dict, stages: list, period: date, edition: str, dimension_codes) -> None:
    """Stage 2 share of Stage 1-3 loans; not applicable before IFRS 9 (2018-09)."""
    if period < date(2018, 9, 1):
        row["stage2_share"] = None
        _add_flag(row["_flags"], "stage2_share", "not_applicable_before_ifrs9")
        return
    stage_codes = {code: dimension_codes(edition, "ASSETS_Stages", label)
                   for code, label in (("1", "Stage 1:"), ("2", "Stage 2:"), ("3", "Stage 3:"))}
    denominator = sum(x[3] or 0 for x in stages if any(x[6] in values for values in stage_codes.values()))
    numerator = sum(x[3] or 0 for x in stages if x[6] in stage_codes["2"])
    row["stage2_share"] = numerator / denominator if denominator > 0 else None
    if row["stage2_share"] is None:
        _add_flag(row["_flags"], "stage2_share", "template_gap")


def _roe(row: dict, key: tuple, month: int, facts: FactIndex) -> None:
    """RoCET1 = annualised profit / CET1 amount."""
    p_rows = facts.profit.get(key, [])
    annual, assumed = annualise_profit(_first(p_rows, 3), _first(p_rows, 4), month, _first(p_rows, 5))
    cet1_amount = _first(facts.cet1.get(key, []), 3)
    row["roe_annualised"] = annual / cet1_amount if annual is not None and cet1_amount else None
    if assumed:
        _add_flag(row["_flags"], "roe_annualised", "fiscal_year_assumed")
    if annual is None:
        _add_flag(row["_flags"], "roe_annualised", "numerator_missing")
    if not cet1_amount:
        _add_flag(row["_flags"], "roe_annualised", "denominator_missing")


def _concentration(row: dict, key: tuple, period: date, year: int, total_codes: set, facts: FactIndex) -> None:
    """NACE and sovereign HHI (sovereign only for June/December)."""
    nace_rows = [x for x in facts.nace.get(key, []) if x[9] in total_codes and x[10] not in (None, "0")]
    row["nace_hhi"] = hhi([x[3] or 0 for x in nace_rows])
    if row["nace_hhi"] is None:
        _add_flag(row["_flags"], "nace_hhi", "template_gap")
    sov_code = "1820802" if year <= 2017 else ("1820810" if year == 2018 else "2520810")
    sov_rows = [x for x in facts.sov_by_code[sov_code].get(key, []) if x[4] not in (None, "0")]
    row["sovereign_hhi"] = hhi([x[3] or 0 for x in sov_rows]) if period.month in (6, 12) else None
    row["sovereign_template"] = "pre2019" if year <= 2018 else "2019plus"
    if period.month not in (6, 12):
        _add_flag(row["_flags"], "sovereign_hhi", "not_reported_this_period")
    elif row["sovereign_hhi"] is None:
        _add_flag(row["_flags"], "sovereign_hhi", "template_gap")


def _own_features(rows: list[dict], ctx: PanelContext, facts: FactIndex, dimensions: Path) -> None:
    """Features that depend only on the row's own facts (ratios, NPL, stage 2, RoCET1, HHI)."""
    cache: dict[tuple, set] = {}

    def dimension_codes(edition, sheet, text, exact=False):
        if (edition, sheet, text, exact) not in cache:
            cache[(edition, sheet, text, exact)] = _dimension_codes(dimensions, edition, sheet, text, exact)
        return cache[(edition, sheet, text, exact)]

    for row in rows:
        key = (row["version_id"], row["bank_id"])
        period, year, edition = ctx.period[key[0]], ctx.year[key[0]], ctx.edition[key[0]]
        row["frequency"] = "semi_annual" if period <= date(2018, 6, 30) else "quarterly"
        _capital_ratios(row, key, facts)
        total_loans = _total_loans(row, key, facts)
        _npl_ratio(row, total_loans, period, year, dimension_codes, edition)
        _stage2_share(row, facts.stage.get(key, []), period, edition, dimension_codes)
        _roe(row, key, period.month, facts)
        total_codes = dimension_codes(edition, "Perf_status", "No breakdown")
        _concentration(row, key, period, year, total_codes, facts)
        row["_loan"] = sum(x[3] or 0 for x in total_loans if x[9] in total_codes)


def _growth_features(rows: list[dict], ctx: PanelContext) -> None:
    """QoQ/YoY growth and deltas through the continuity key; NULL + series_break across 2020-06-30."""
    ordered = sorted(rows, key=lambda x: (x["continuity_key"], ctx.period[x["version_id"]]))
    by_period = {(row["continuity_key"], (ctx.period[row["version_id"]].year,
                                          ctx.period[row["version_id"]].month)): row for row in rows}
    break_period = date(2020, 6, 30)
    previous: dict[str, dict] = {}
    for row in ordered:
        bank, period = row["continuity_key"], ctx.period[row["version_id"]]
        prior = previous.get(bank)
        immediate = prior if (prior and is_quarter_pair(
            period, ctx.period[prior["version_id"]], prior["frequency"])) else None
        annual_prior = by_period.get((bank, _subtract_months(period, 12)))
        _quarterly_changes(row, immediate, period, break_period, ctx)
        _yearly_growth(row, annual_prior, period, ctx)
        previous[bank] = row


def _quarterly_changes(row: dict, immediate, period: date, break_period: date, ctx: PanelContext) -> None:
    crosses = immediate and crosses_series_break(period, ctx.period[immediate["version_id"]], break_period)
    if immediate and row["frequency"] == "quarterly":
        if crosses:
            row["loan_growth_qoq"] = None
            _add_flag(row["_flags"], "loan_growth_qoq", "series_break")
        else:
            row["loan_growth_qoq"] = growth_rate(row["_loan"], immediate["_loan"])
            if period < break_period:
                _add_flag(row["_flags"], "loan_growth_qoq", "series_break")
        row["npl_delta_qoq"] = (row["npl_ratio"] - immediate["npl_ratio"]
                                if row["npl_ratio"] is not None and immediate["npl_ratio"] is not None else None)
        row["cet1_delta_qoq"] = (row["cet1_ratio"] - immediate["cet1_ratio"]
                                 if row["cet1_ratio"] is not None and immediate["cet1_ratio"] is not None else None)
    else:
        row["loan_growth_qoq"] = row["npl_delta_qoq"] = row["cet1_delta_qoq"] = None


def _yearly_growth(row: dict, annual_prior, period: date, ctx: PanelContext) -> None:
    """Loan growth over 12 months; NULL + series_break across `ctx.loan_break`."""
    break_period = ctx.loan_break
    if annual_prior and crosses_series_break(period, ctx.period[annual_prior["version_id"]], break_period):
        row["loan_growth_yoy"] = None
        _add_flag(row["_flags"], "loan_growth_yoy", "series_break")
    elif annual_prior and row["_loan"] is not None and row["_loan"] > 0 and annual_prior["_loan"] > 0:
        row["loan_growth_yoy"] = growth_rate(row["_loan"], annual_prior["_loan"])
        if period < break_period:
            _add_flag(row["_flags"], "loan_growth_yoy", "series_break")
        if row["loan_growth_yoy"] > 1:
            _add_flag(row["_flags"], "loan_growth_yoy", "extreme_growth")
    else:
        row["loan_growth_yoy"] = None
        _add_flag(row["_flags"], "loan_growth_yoy", "no_prior_period")


def _flag_outliers(rows: list[dict], k: float, transform: str) -> None:
    """MAD outlier flags per dataset version and feature (flag only, values unchanged)."""
    by_version = defaultdict(list)
    for row in rows:
        by_version[row["version_id"]].append(row)
    for feature in FEATURES:
        for version_rows in by_version.values():
            _outliers(version_rows, feature, k, transform)


COLUMNS = ("version_id", "bank_id", "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
           "npl_ratio", "stage2_share", "roe_annualised", "nace_hhi", "sovereign_hhi", "npl_delta_qoq",
           "loan_growth_qoq", "loan_growth_yoy", "cet1_delta_qoq")


def panel_records(rows: list[dict]) -> list[tuple[tuple, dict]]:
    """(column values, flags json) per row, exactly what is written to panel_row."""
    records = []
    for row in rows:
        flags = {"frequency": row["frequency"], "sovereign_template": row["sovereign_template"]}
        flags.update({feature: values for feature, values in row["_flags"].items() if values})
        records.append((tuple(row.get(column) for column in COLUMNS), flags))
    return records


def compute_panel(cur, dimensions_root: str | Path = "config/dimensions",
                  dictionary_root: str | Path = "config", outlier_k: float = 3,
                  outlier_transform: str = "raw") -> PanelBuild | None:
    """Build the panel rows in memory from the active versions (read-only). None = no active version."""
    versions = _active_versions(cur)
    if not versions:
        return None
    root = Path(dictionary_root)
    ctx = _context(cur, versions, loan_series_break(root))
    rows = _base_rows(cur, ctx, _approved_crosswalks(root), specialist_leis(root))
    facts, _ = _load_facts(cur, ctx.version_ids)
    _own_features(rows, ctx, facts, Path(dimensions_root))
    _growth_features(rows, ctx)
    _flag_outliers(rows, outlier_k, outlier_transform)
    provenance = {"active_version_ids": ctx.version_ids, "configuration_sha256": _config_hash(root),
                  "builder": "core.panel"}
    return PanelBuild(rows, provenance)


def _write_panel(cur, build: PanelBuild) -> None:
    cur.execute("DELETE FROM panel_row")
    for values, flags in panel_records(build.rows):
        cur.execute("""INSERT INTO panel_row
            (version_id,bank_id,cet1_ratio,tier1_ratio,total_capital_ratio,leverage_ratio,
             npl_ratio,stage2_share,roe_annualised,nace_hhi,sovereign_hhi,npl_delta_qoq,
             loan_growth_qoq,loan_growth_yoy,cet1_delta_qoq,min_headroom,indicators,flags,build_provenance)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s)""",
                    (*values, Json({}), Json(flags), Json(build.provenance)))


def build_panel(conn, dimensions_root: str | Path = "config/dimensions",
                dictionary_root: str | Path = "config", outlier_k: float = 3,
                outlier_transform: str = "raw", run_hooks: bool = True) -> int:
    """Rebuild ``panel_row`` from the active versions in one transaction, then run the registered hooks.

    Recipe: compute_panel (read facts, build rows) -> write panel_row -> commit -> after-rebuild hooks.
    Registered hooks run after the commit; their failure is raised as PanelHookError.
    """
    with conn:
        with conn.cursor() as cur:
            build = compute_panel(cur, dimensions_root, dictionary_root, outlier_k, outlier_transform)
            if build is None:
                cur.execute("DELETE FROM panel_row")
            else:
                _write_panel(cur, build)
    rows = len(build.rows) if build else 0
    if run_hooks:
        run_after_panel_rebuild(conn, PanelRebuilt(rows, build.provenance["active_version_ids"] if build else []))
    return rows
