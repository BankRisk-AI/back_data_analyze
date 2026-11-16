from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

import psycopg2.errors
import yaml
from psycopg2 import sql

from app.core.database import connect
from app.core.exceptions import AppError, BadRequestError, InvalidParameter, NotFoundError
from app.modules.eba_public_analysis.domain import DATASETS, MAX_PAGE_SIZE

QUERY_TIMEOUT_SECONDS = 10


class QueryTooSlow(AppError):
    kind = "query-too-slow"
    status = 504
    title = "Query too slow"
FEATURES = {
    "cet1_ratio": ("CET1 ratio", "end-period CET1 ratio", "ratio", "201412", "higher_is_riskier"),
    "tier1_ratio": ("Tier 1 ratio", "end-period Tier 1 ratio", "ratio", "201412", "higher_is_riskier"),
    "total_capital_ratio": ("Total capital ratio", "end-period total capital ratio", "ratio", "201412", "higher_is_riskier"),
    "leverage_ratio": ("Leverage ratio", "reported transitional leverage ratio", "ratio", "201412", "lower_is_riskier"),
    "npl_ratio": ("NPL ratio", "non-performing loans divided by total loans", "ratio", "201412", "higher_is_riskier"),
    "stage2_share": ("Stage 2 share", "Stage 2 loans divided by Stage 1-3 loans", "ratio", "201809", "higher_is_riskier"),
    "roe_annualised": ("RoCET1", "annualised YTD profit divided by end-period CET1", "ratio", "201412", "both_extremes"),
    "loan_growth_qoq": ("Loan growth QoQ", "total loans divided by the prior calendar quarter minus one", "ratio", "201812", "both_extremes"),
    "loan_growth_yoy": ("Loan growth YoY", "total loans divided by the same month in the prior year minus one", "ratio", "201512", "both_extremes"),
    "nace_hhi": ("NACE HHI", "sum of squared NACE sector loan shares", "index", "201909", "higher_is_riskier"),
    "sovereign_hhi": ("Sovereign HHI", "sum of squared sovereign country shares", "index", "201412", "higher_is_riskier"),
}
FLAG_DESCRIPTIONS = {
    "missing_in_source": "Source value is absent.",
    "invalid_denominator": "A required denominator is non-positive or absent.",
    "template_gap": "The reporting template does not provide the feature.",
    "not_reported_this_period": "The source does not report this feature in this period.",
    "no_prior_period": "The required calendar comparison period is absent.",
    "implausible_value": "The raw value fails a source consistency check.",
    "specialist_institution": "The bank is in the version-controlled specialist list.",
    "outlier": "The value is outside the per-period robust MAD threshold.",
}


@contextmanager
def _read_session(schema: str):
    conn = connect(schema)
    try:
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = %s", (f"{QUERY_TIMEOUT_SECONDS}s",))
        yield conn, cur
    except psycopg2.errors.QueryCanceled as exc:
        raise QueryTooSlow(f"the query took more than {QUERY_TIMEOUT_SECONDS} seconds") from exc
    finally:
        conn.rollback()
        conn.close()


def _specialist_leis() -> set[str]:
    path = Path("config/specialist_institutions.yaml")
    return {str(item["lei"]).strip() for item in yaml.safe_load(path.read_text()) or []} if path.exists() else set()


def report_types(schema: str) -> list[dict]:
    with _read_session(schema) as (_, cur):
        cur.execute("""SELECT report_type, array_agg(DISTINCT file_group ORDER BY file_group)
                       FROM indicator GROUP BY report_type ORDER BY report_type""")
        return [{"name": r[0], "label": r[0], "datasets": list(r[1])} for r in cur.fetchall()]


def report_years(report_type: str, schema: str) -> list[dict]:
    with _read_session(schema) as (_, cur):
        cur.execute("""SELECT DISTINCT v.year FROM dataset_version v
                       JOIN indicator i ON i.report_type=%s
                       WHERE v.is_active AND EXISTS (
                         SELECT 1 FROM fact_oth f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_cre f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_mrk f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_sov f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id)
                       ORDER BY v.year""", (report_type,))
        return [{"year": r[0]} for r in cur.fetchall()]


def report_quarters(report_type: str, year: int, schema: str) -> list[dict]:
    with _read_session(schema) as (_, cur):
        cur.execute("""SELECT DISTINCT v.period_end, v.quarter FROM dataset_version v
                       JOIN indicator i ON i.report_type=%s
                       WHERE v.is_active AND v.year=%s AND EXISTS (
                         SELECT 1 FROM fact_oth f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_cre f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_mrk f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id
                         UNION ALL SELECT 1 FROM fact_sov f WHERE f.version_id=v.version_id AND f.indicator_id=i.indicator_id)
                       ORDER BY v.period_end""", (report_type, year))
        return [{"period": r[0].strftime("%Y%m"), "quarter": f"Q{r[1]}", "reporting_date": r[0].isoformat()} for r in cur.fetchall()]


def banks(schema: str, page: int, page_size: int, country: str | None = None, search: str | None = None) -> dict:
    _page(page, page_size)
    specialist = _specialist_leis()
    clauses, params = [], []
    if country:
        clauses.append("b.country_code=%s"); params.append(country.upper())
    if search:
        clauses.append("(b.name ILIKE %s OR b.lei ILIKE %s)"); params.extend([f"%{search}%", f"%{search}%"])
    where = " AND ".join(clauses) or "TRUE"
    with _read_session(schema) as (_, cur):
        cur.execute(f"""SELECT count(*) FROM bank b WHERE {where}""", params)
        total = cur.fetchone()[0]
        cur.execute(f"""SELECT b.bank_id,trim(b.lei),b.name,b.country_code,min(v.period_end),
                               max(v.period_end),count(DISTINCT v.version_id)
                        FROM bank b LEFT JOIN panel_row p ON p.bank_id=b.bank_id
                        LEFT JOIN dataset_version v ON v.version_id=p.version_id AND v.is_active
                        WHERE {where} GROUP BY b.bank_id ORDER BY b.name,b.bank_id
                        LIMIT %s OFFSET %s""", (*params, page_size, (page - 1) * page_size))
        rows = [{"bank_id": r[0], "lei": r[1], "name": r[2], "country": r[3],
                 "first_period": r[4].strftime("%Y%m") if r[4] else None,
                 "last_period": r[5].strftime("%Y%m") if r[5] else None,
                 "periods": r[6], "specialist_institution": r[1] in specialist} for r in cur.fetchall()]
        return {"rows": rows, "total": total, "page": page, "page_size": page_size}


def bank_panel(bank_id: int, schema: str) -> dict:
    with _read_session(schema) as (_, cur):
        cur.execute("""SELECT 1 FROM bank WHERE bank_id=%s""", (bank_id,))
        if not cur.fetchone():
            raise NotFoundError(f"bank {bank_id} does not exist")
        cur.execute("""SELECT to_char(v.period_end,'YYYYMM'),v.period_end,p.cet1_ratio,p.tier1_ratio,
                              p.total_capital_ratio,p.leverage_ratio,p.npl_ratio,p.stage2_share,
                              p.roe_annualised,p.loan_growth_qoq,p.loan_growth_yoy,p.nace_hhi,
                              p.sovereign_hhi,p.npl_delta_qoq,p.cet1_delta_qoq,p.min_headroom,p.flags
                       FROM panel_row p JOIN dataset_version v USING(version_id)
                       WHERE p.bank_id=%s AND v.is_active ORDER BY v.period_end""", (bank_id,))
        columns = ["period", "reporting_date", *FEATURES, "npl_delta_qoq",
                   "cet1_delta_qoq", "min_headroom"]
        periods = []
        for r in cur.fetchall():
            flags = r[-1] or {}
            item = dict(zip(columns, r[:-1]))
            item["flags"] = flags
            item["frequency"] = flags.get("frequency")
            periods.append(item)
        return {"bank_id": bank_id, "periods": periods}


def cross_section(period: str, feature: str, schema: str, exclude_specialist: bool = False) -> dict:
    if feature not in FEATURES or len(period) != 6 or not period.isdigit():
        raise InvalidParameter("feature or period is invalid")
    specialist = _specialist_leis()
    with _read_session(schema) as (_, cur):
        cur.execute("""SELECT v.version_id FROM dataset_version v
                       WHERE v.is_active AND to_char(v.period_end,'YYYYMM')=%s""", (period,))
        version = cur.fetchone()
        if not version:
            raise NotFoundError(f"active period {period} does not exist")
        cur.execute("""SELECT p.bank_id,trim(b.lei),b.name,p.flags
                       FROM panel_row p JOIN bank b USING(bank_id)
                       WHERE p.version_id=%s ORDER BY b.name""", (version[0],))
        values = []
        for bank_id, lei, name, flags in cur.fetchall():
            if exclude_specialist and lei in specialist:
                continue
            values.append({"bank_id": bank_id, "lei": lei, "name": name,
                           "value": flags.get(feature) if False else None,
                           "flags": (flags or {}).get(feature, [])})
        # The feature identifier is fixed in SQL to avoid dynamic identifiers.
        cur.execute(sql.SQL("SELECT p.bank_id,{} FROM panel_row p WHERE p.version_id=%s").format(sql.Identifier(feature)), (version[0],))
        by_bank = dict(cur.fetchall())
        for item in values:
            item["value"] = by_bank.get(item["bank_id"])
        return {"period": period, "feature": feature, "values": values}


def feature_definitions() -> dict:
    return {"features": [{"name": n, "label": v[0], "formula": v[1], "unit": v[2],
                          "first_period": v[3], "risk_direction": v[4]} for n, v in FEATURES.items()],
            "flags": FLAG_DESCRIPTIONS}


def _profile_file(name: str) -> dict:
    path = Path("config/rules") / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def _available_profiles(cur) -> list[dict]:
    cur.execute("""SELECT profile_name, profile_sha256, max(created_at)
                   FROM alert GROUP BY profile_name, profile_sha256
                   ORDER BY profile_name, max(created_at) DESC""")
    return [{"profile_name": name, "sha": sha, "short_sha": sha[:12],
             "version": _profile_file(name).get("version")}
            for name, sha, _ in cur.fetchall()]


def _profile_error(profile: str | None, available: list[dict]) -> NotFoundError:
    choices = ", ".join(f"{p['profile_name']} v{p['version'] or '?'} ({p['short_sha']})" for p in available)
    return NotFoundError(f"alert profile {profile or 'eu_eba'} does not exist; available profiles: {choices or 'none'}")


def _resolve_profile(cur, profile: str | None) -> tuple[str, str]:
    available = _available_profiles(cur)
    if not available:
        raise _profile_error(profile, available)
    if profile is None:
        candidates = [p for p in available if p["profile_name"] == "eu_eba"]
        if not candidates:
            raise _profile_error(profile, available)
        return candidates[0]["profile_name"], candidates[0]["sha"]
    named = [p for p in available if p["profile_name"] == profile]
    if named:
        return named[0]["profile_name"], named[0]["sha"]
    if len(profile) == 64:
        matches = [p for p in available if p["sha"] == profile]
    elif len(profile) >= 8:
        matches = [p for p in available if p["sha"].startswith(profile)]
        if len(matches) > 1:
            raise BadRequestError(f"ambiguous alert profile prefix '{profile}'")
    else:
        matches = []
    if matches:
        return matches[0]["profile_name"], matches[0]["sha"]
    raise _profile_error(profile, available)


def alert_profiles(schema: str) -> list[dict]:
    with _read_session(schema) as (_, cur):
        cur.execute("""SELECT profile_name, profile_sha256, max(created_at),
                              max(CASE WHEN jsonb_typeof(rule_results)='array'
                                       THEN jsonb_array_length(rule_results)
                                       ELSE jsonb_array_length(rule_results->'rules') END)
                       FROM alert GROUP BY profile_name, profile_sha256
                       ORDER BY profile_name, max(created_at) DESC""")
        rows = []
        for name, sha, created, rule_count in cur.fetchall():
            config = _profile_file(name)
            rows.append({"profile_name": name, "version": str(config.get("version")) if config.get("version") is not None else None,
                         "sha": sha, "frozen": config.get("frozen"), "created_at": created.isoformat(),
                         "rule_count": rule_count or 0,
                         "families": ["capital", "asset_quality", "profitability", "dynamics"]})
        return rows


def alert_summary(profile: str | None, schema: str) -> dict:
    with _read_session(schema) as (_, cur):
        name, sha = _resolve_profile(cur, profile)
        specialists = _specialist_leis()
        cur.execute("""SELECT to_char(v.period_end,'YYYYMM'), a.level, trim(b.lei)
                       FROM alert a JOIN dataset_version v USING(version_id)
                       JOIN bank b USING(bank_id)
                       WHERE a.profile_name=%s AND a.profile_sha256=%s
                       ORDER BY v.period_end""", (name, sha))
        grouped = {}
        for period, level, lei in cur.fetchall():
            if lei in specialists:
                continue
            item = grouped.setdefault(period, {"green": 0, "amber": 0, "red": 0, "not_evaluated": 0})
            item[level] += 1
        periods = []
        for period, counts in grouped.items():
            total = sum(counts.values())
            periods.append({"period": period, "counts": counts,
                            "shares": {key: round(value * 100 / total, 4) if total else 0 for key, value in counts.items()}})
        return {"profile_name": name, "profile_sha256": sha, "periods": periods}


def _payload_fields(payload) -> tuple[str | None, dict | None]:
    if isinstance(payload, list):
        return None, None
    payload = payload or {}
    return payload.get("level_reason"), payload.get("family_scores")


def _alert_projection(value: tuple, specialist: set[str]) -> dict:
    alert_id, bank_id, lei, bank_name, period, level, score, payload = value
    reason, family_scores = _payload_fields(payload)
    return {"alert_id": alert_id, "bank_id": bank_id, "lei": lei, "bank_name": bank_name,
            "period": period, "level": level, "reason": reason,
            "family_scores": family_scores}


def alerts(period: str, profile: str | None, level: str | None, exclude_specialist: bool,
           page: int, page_size: int, schema: str) -> dict:
    _page(page, page_size)
    if len(period) != 6 or not period.isdigit():
        raise InvalidParameter("period must be YYYYMM")
    if level not in {None, "green", "amber", "red", "not_evaluated"}:
        raise InvalidParameter("level is invalid")
    with _read_session(schema) as (_, cur):
        name, sha = _resolve_profile(cur, profile)
        specialist = _specialist_leis()
        clauses = ["a.profile_name=%s", "a.profile_sha256=%s", "to_char(v.period_end,'YYYYMM')=%s"]
        params: list = [name, sha, period]
        if level:
            clauses.append("a.level=%s"); params.append(level)
        cur.execute(f"""SELECT a.alert_id,a.bank_id,trim(b.lei),b.name,to_char(v.period_end,'YYYYMM'),
                               a.level,a.score,a.rule_results
                        FROM alert a JOIN dataset_version v USING(version_id) JOIN bank b USING(bank_id)
                        WHERE {' AND '.join(clauses)}
                        ORDER BY CASE a.level WHEN 'red' THEN 0 WHEN 'amber' THEN 1 WHEN 'green' THEN 2 ELSE 3 END,
                                 a.score DESC NULLS LAST,b.name,a.bank_id""", params)
        filtered = [row for row in cur.fetchall() if not (exclude_specialist and row[2] in specialist)]
        total = len(filtered)
        rows = [_alert_projection(row, specialist)
                for row in filtered[(page - 1) * page_size:page * page_size]]
        return {"rows": rows, "total": total, "page": page, "page_size": page_size}


def bank_alerts(bank_id: int, profile: str | None, schema: str) -> dict:
    with _read_session(schema) as (_, cur):
        cur.execute("SELECT 1 FROM bank WHERE bank_id=%s", (bank_id,))
        if not cur.fetchone():
            raise NotFoundError(f"bank {bank_id} does not exist")
        name, sha = _resolve_profile(cur, profile)
        cur.execute("""SELECT to_char(v.period_end,'YYYYMM'),a.level,a.rule_results
                       FROM alert a JOIN dataset_version v USING(version_id)
                       WHERE a.bank_id=%s AND a.profile_name=%s AND a.profile_sha256=%s
                       ORDER BY v.period_end""", (bank_id, name, sha))
        return {"bank_id": bank_id, "rows": [
            {"period": period, "level": level, "reason": _payload_fields(payload)[0],
             "family_scores": _payload_fields(payload)[1]}
            for period, level, payload in cur.fetchall()
        ]}


def alert_detail(alert_id: int, profile: str | None, schema: str) -> dict:
    with _read_session(schema) as (_, cur):
        cur.execute("""SELECT a.alert_id,a.bank_id,a.version_id,to_char(v.period_end,'YYYYMM'),
                              a.level,a.score,a.rule_results,a.profile_name,a.profile_sha256
                       FROM alert a JOIN dataset_version v USING(version_id) WHERE a.alert_id=%s""", (alert_id,))
        row = cur.fetchone()
        if not row:
            raise NotFoundError(f"alert {alert_id} does not exist")
        if profile is not None:
            name, sha = _resolve_profile(cur, profile)
            if row[7] != name or row[8] != sha:
                raise NotFoundError(f"alert {alert_id} does not belong to profile {profile}")
        payload = row[6] or {}
        if isinstance(payload, list):
            payload_dict = {}
            rules = payload
        else:
            payload_dict = payload
            rules = payload.get("rules", [])
        config = _profile_file(row[7])
        return {"alert_id": row[0], "bank_id": row[1], "version_id": row[2], "period": row[3],
                "level": row[4], "score": row[5], "reason": payload_dict.get("level_reason"),
                "family_scores": payload_dict.get("family_scores"), "rules": rules,
                "profile_name": row[7], "profile_version": str(config.get("version")) if config.get("version") is not None else None,
                "profile_sha256": row[8]}


def indicator_series(indicator_id: int, bank_id: int, schema: str) -> dict:
    with _read_session(schema) as (_, cur):
        cur.execute("SELECT std_code FROM indicator WHERE indicator_id=%s", (indicator_id,))
        if not cur.fetchone():
            raise NotFoundError(f"indicator {indicator_id} does not exist")
        cur.execute("SELECT 1 FROM bank WHERE bank_id=%s", (bank_id,))
        if not cur.fetchone():
            raise NotFoundError(f"bank {bank_id} does not exist")
        rows = []
        for table, dimensions in (("fact_oth", "jsonb_build_object('assets_fv',f.assets_fv,'assets_stages',f.assets_stages,'exposure',f.exposure,'financial_instruments',f.financial_instruments)"),
                                  ("fact_cre", "jsonb_build_object('portfolio',f.portfolio,'country',f.country,'country_rank',f.country_rank,'exposure',f.exposure,'status',f.status,'perf_status',f.perf_status,'nace_codes',f.nace_codes)"),
                                  ("fact_mrk", "jsonb_build_object('portfolio',f.portfolio,'mkt_modprod',f.mkt_modprod,'mkt_risk',f.mkt_risk)"),
                                  ("fact_sov", "jsonb_build_object('country',f.country,'accounting_portfolio',f.accounting_portfolio,'maturity',f.maturity)")):
            cur.execute(sql.SQL("""SELECT to_char(v.period_end,'YYYYMM'),f.amount,%s,coalesce(m.source_item,''),
                                         {} FROM {} f JOIN dataset_version v USING(version_id)
                                         LEFT JOIN indicator_code_map m ON m.indicator_id=f.indicator_id
                                           AND m.edition_label=(SELECT edition_label FROM import_batch WHERE import_id=v.import_id)
                                         WHERE f.indicator_id=%s AND f.bank_id=%s AND v.is_active
                                         ORDER BY v.period_end""").format(sql.SQL(dimensions), sql.Identifier(table)),
                        (table, indicator_id, bank_id))
            rows.extend({"period": r[0], "value": r[1], "dataset": r[2], "source_code": r[3], "dimensions": r[4]} for r in cur.fetchall())
        rows.sort(key=lambda r: r["period"])
        return {"indicator_id": indicator_id, "bank_id": bank_id, "rows": rows}


def _view(dataset: str) -> str:
    key = dataset.removeprefix("tr_")
    try:
        return DATASETS[key]
    except KeyError as exc:
        raise InvalidParameter(f"unsupported public dataset '{dataset}'") from exc


def _page(page: int, page_size: int) -> None:
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise InvalidParameter(f"page_size must be between 1 and {MAX_PAGE_SIZE}")


def _ensure_active(cur, version_id: int) -> None:
    cur.execute("SELECT 1 FROM dataset_version WHERE version_id=%s AND is_active", (version_id,))
    if not cur.fetchone():
        raise NotFoundError(f"active version {version_id} does not exist")


def periods(schema: str) -> list[dict]:
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT version_id, year, quarter, period_end, import_id,
                                  (SELECT count(*) FROM fact_oth WHERE version_id=v.version_id),
                                  (SELECT count(*) FROM fact_cre WHERE version_id=v.version_id),
                                  (SELECT count(*) FROM fact_mrk WHERE version_id=v.version_id)
                                  ,(SELECT count(*) FROM fact_sov WHERE version_id=v.version_id)
                           FROM dataset_version v WHERE is_active
                           ORDER BY year, quarter, version_no""")
            return [{"version_id": r[0], "year": r[1], "quarter": r[2], "period_end": r[3].isoformat(),
                     "import_id": r[4], "rows_oth": r[5], "rows_cre": r[6], "rows_mrk": r[7], "rows_sov": r[8]} for r in cur.fetchall()]
    finally:
        conn.close()


def preview(version_id: int, dataset: str, schema: str, page: int, page_size: int) -> dict:
    _page(page, page_size)
    view = _view(dataset)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            _ensure_active(cur, version_id)
            cur.execute(f"SELECT count(*) FROM {view} WHERE version_id=%s", (version_id,))
            total = cur.fetchone()[0]
            cur.execute(f"SELECT * FROM {view} WHERE version_id=%s ORDER BY lei_code, item LIMIT %s OFFSET %s",
                        (version_id, page_size, (page - 1) * page_size))
            names = [d[0] for d in cur.description]
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "columns": names,
                    "rows": [dict(zip(names, row)) for row in cur.fetchall()], "total": total,
                    "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}
    finally:
        conn.close()


def profile(version_id: int, dataset: str, schema: str) -> dict:
    view = _view(dataset)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            _ensure_active(cur, version_id)
            cur.execute(f"SELECT count(*), min(amount), max(amount), avg(amount) FROM {view} WHERE version_id=%s", (version_id,))
            rows, minimum, maximum, mean = cur.fetchone()
            cur.execute(f"""SELECT column_name FROM information_schema.columns
                            WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position""",
                        (view,))
            columns = []
            for (name,) in cur.fetchall():
                cur.execute(
                    sql.SQL("SELECT count(*)-count({}), count(DISTINCT {}) FROM {} WHERE version_id=%s")
                    .format(sql.Identifier(name), sql.Identifier(name), sql.Identifier(view)),
                    (version_id,),
                )
                nulls, distinct = cur.fetchone()
                columns.append({"name": name, "nulls": nulls, "distinct": distinct})
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "rows": rows,
                    "columns": columns, "amount": {"min": minimum, "max": maximum, "mean": mean}}
    finally:
        conn.close()


def histogram(version_id: int, dataset: str, item: str, period: str, schema: str, bins: int = 20) -> dict:
    if bins < 1 or bins > 200:
        raise InvalidParameter("bins must be between 1 and 200")
    view = _view(dataset)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            _ensure_active(cur, version_id)
            cur.execute(f"""SELECT count(*), min(amount), max(amount), avg(amount)
                            FROM {view} WHERE version_id=%s AND item=%s AND period=%s""",
                        (version_id, item, period))
            count, minimum, maximum, mean = cur.fetchone()
            if not count or minimum is None or minimum == maximum:
                return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "item": item,
                        "period": period, "rows": count, "bins": [], "stats": {"min": minimum, "max": maximum, "mean": mean}}
            width = (maximum - minimum) / bins
            cur.execute(f"""SELECT least(floor((amount-%s)/%s)::int+1,%s), count(*)
                            FROM {view} WHERE version_id=%s AND item=%s AND period=%s
                            GROUP BY 1 ORDER BY 1""", (minimum, width, bins, version_id, item, period))
            counts = dict(cur.fetchall())
            edges = [{"x0": minimum + i * width, "x1": minimum + (i + 1) * width, "count": counts.get(i + 1, 0)}
                     for i in range(bins)]
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "item": item,
                    "period": period, "rows": count, "bins": edges,
                    "stats": {"min": minimum, "max": maximum, "mean": mean}}
    finally:
        conn.close()


def aggregate(version_id: int, dataset: str, item: str, period: str, function: str, schema: str) -> dict:
    if function not in {"sum", "avg", "min", "max", "count"}:
        raise InvalidParameter("function must be sum, avg, min, max or count")
    view = _view(dataset)
    expression = "count(*)" if function == "count" else f"{function}(amount)"
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            _ensure_active(cur, version_id)
            cur.execute(f"SELECT {expression} FROM {view} WHERE version_id=%s AND item=%s AND period=%s",
                        (version_id, item, period))
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"), "item": item,
                    "period": period, "function": function, "value": cur.fetchone()[0]}
    finally:
        conn.close()


def scatter(version_id: int, dataset: str, item_x: str, item_y: str, period: str, schema: str) -> dict:
    view = _view(dataset)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            _ensure_active(cur, version_id)
            cur.execute(
                f"""SELECT x.lei_code, x.amount, y.amount
                    FROM {view} x JOIN {view} y
                      ON y.version_id=x.version_id AND y.lei_code=x.lei_code AND y.period=x.period
                    WHERE x.version_id=%s AND x.period=%s AND x.item=%s AND y.item=%s
                    ORDER BY x.lei_code""",
                (version_id, period, item_x, item_y),
            )
            points = [{"lei_code": r[0], "x": r[1], "y": r[2]} for r in cur.fetchall()]
            return {"version_id": version_id, "dataset": dataset.removeprefix("tr_"),
                    "item_x": item_x, "item_y": item_y, "period": period, "points": points}
    finally:
        conn.close()
