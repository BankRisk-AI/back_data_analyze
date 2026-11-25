"""The inner load logic: reference file parsing and fact table population.
Called by run_load() inside the transaction it owns."""
from __future__ import annotations

import calendar
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

from openpyxl import load_workbook
from psycopg2 import sql
from psycopg2.extras import Json

from app.core.data_decisions import DataDecision, load_data_decisions
from app.core.preflight import collision_check
from app.modules.eba_ingest.domain.exceptions import LoadError
from app.shared.staging import staging_identifier
from app.shared.sql.predicates import NUMBER_REGEX, aggregate_rows_predicate, blank_text, numeric_amount


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _workbook_rows(path: str, sheet: str | None = None):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        yield from ([("" if v is None else str(int(v) if isinstance(v, float) and v.is_integer() else v)) for v in row]
                    for row in ws.iter_rows(values_only=True))
    finally:
        wb.close()


def _header_rows(rows):
    rows = iter(rows)
    for row in rows:
        headers = [_norm(v) for v in row]
        if "item" in headers or "lei_code" in headers:
            return headers, rows
    return [], iter(())


def _reference_files(cur, import_id: int) -> dict[str, str]:
    cur.execute("SELECT file_type, stored_path FROM source_file WHERE import_id = %s", (import_id,))
    return {kind: path for kind, path in cur.fetchall() if kind in {"SDD", "TR_Metadata"}}


def _decision_condition(decision: DataDecision, columns: list[str], cur):
    values = {"lei_code": decision.lei, "period": decision.period, "item": decision.item, **decision.dimensions}
    parts, params = [], []
    for column, value in values.items():
        if column not in columns:
            raise LoadError(f"data decision {decision.id} references missing column {column}")
        parts.append(sql.SQL("btrim({}) = %s").format(sql.Identifier(column)))
        params.append(value)
    if decision.action == "keep_amount":
        if "amount" not in columns or decision.amount is None:
            raise LoadError(f"data decision {decision.id} requires an amount")
        parts.append(sql.SQL("btrim(amount) = %s").format(sql.Identifier("amount")))
        params.append(decision.amount)
    return sql.SQL(" AND ").join(parts), params


def _sdd(path: str, edition: str | None, file_groups: set[str]):
    headers, rows = _header_rows(_workbook_rows(path))
    if not headers:
        raise LoadError("SDD has no Item header")
    item_idx = headers.index("item")
    label_idx = headers.index("label") if "label" in headers else None
    category_idx = headers.index("category") if "category" in headers else None
    dataset_idx = headers.index("dataset") if "dataset" in headers else None
    edition_col = next((i for i, h in enumerate(headers) if h == f"item_tr_{(edition or '').lower()}"), None)
    mapping: dict[str, dict] = {}
    labels: dict[tuple[str, str], str] = {}
    for row in rows:
        row = list(row) + [""] * max(0, len(headers) - len(row))
        std = row[item_idx].strip()
        if not std:
            continue
        label = row[label_idx].strip() if label_idx is not None else std
        group = _norm(row[dataset_idx]).replace("tr_", "") if dataset_idx is not None else ""
        category = row[category_idx].strip() if category_idx is not None else "Unclassified"
        mapping[std] = {"std_code": std, "label": label, "group": group, "category": category}
        labels[(group, label)] = std
        if edition_col is not None and row[edition_col].strip():
            mapping.setdefault(row[edition_col].strip(), mapping[std])
    return mapping, labels


def _metadata(path: str):
    if not path:
        return []
    from app.modules.eba_ingest.infrastructure.readers.readers import xlsx_bank_list_sheet

    sheet = xlsx_bank_list_sheet(path)
    if sheet is None:
        return []
    rows = list(_workbook_rows(path, sheet))
    header_at = next((i for i, r in enumerate(rows) if "lei_code" in [_norm(x) for x in r]), None)
    if header_at is None:
        return []
    headers = [_norm(x) for x in rows[header_at]]
    out = []
    for row in rows[header_at + 1:]:
        values = list(row) + [""] * max(0, len(headers) - len(row))
        record = dict(zip(headers, values))
        lei = record.get("lei_code", "").strip()
        if not lei:
            continue
        previous = {record[k].strip() for k in headers if k.startswith("lei_code_") and record.get(k, "").strip()}
        previous.discard(lei)
        out.append((lei, record.get("name") or record.get("bank_name") or None,
                    (record.get("country") or record.get("country_code") or "")[:2] or None,
                    str(record.get("finrep", "")).lower().startswith("yes"), sorted(previous)))
    return out


TARGET_TABLES = {"tr_oth": "fact_oth", "tr_cre": "fact_cre", "tr_mrk": "fact_mrk", "tr_sov": "fact_sov"}
SOURCE_ONLY_COLUMNS = {"lei_code", "nsa", "period", "item", "label"}
SOURCE_COLUMN_MAP = {"row": "source_row", "column": "source_column", "sheet": "source_sheet"}
DUPLICATE_IGNORED = {"label", "footnote", "row", "column", "sheet", "source_row", "source_column", "source_sheet"}
QUARTER_EXPR = "((substring(btrim(s.period), 5, 2)::integer - 1) / 3 + 1)"


@dataclass
class LoadPlan:
    """What the load needs about one import: edition, data files, reference files and column layouts."""
    edition: str
    data: list[tuple[int, str, str]]                      # (file_id, file_type, file_name)
    paths: dict[str, str]                                 # SDD / TR_Metadata stored paths
    source_hashes: dict[str, str]
    staging_columns: dict[int, list[str]]
    target_columns: dict[str, list[str]]


def _lock_import(cur, import_id: int):
    """Lock the import row; refuse imports that are not ready; log the load request. Returns (status, edition, user)."""
    cur.execute("SELECT status, edition_label, created_by FROM import_batch WHERE import_id = %s FOR UPDATE", (import_id,))
    head = cur.fetchone()
    if not head:
        raise LoadError(f"import {import_id} does not exist")
    if head[0] not in ("validated", "failed", "approved", "loading"):
        raise LoadError(f"import {import_id} is not ready for load: {head[0]}")
    cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_request',%s)",
                (import_id, Json({"edition": head[1]})))
    return head


def _plan(cur, import_id: int, edition: str) -> LoadPlan:
    """Data files, reference files and the staged/target column layouts (schema-mismatch is refused here)."""
    cur.execute("SELECT file_id, file_type, file_name FROM source_file WHERE import_id = %s ORDER BY file_id", (import_id,))
    data = [(fid, typ, name) for fid, typ, name in cur.fetchall() if typ in TARGET_TABLES]
    if not data:
        raise LoadError("no recognised EBA data files")
    paths = _reference_files(cur, import_id)
    cur.execute("SELECT file_type, sha256 FROM source_file WHERE import_id=%s", (import_id,))
    source_hashes = dict(cur.fetchall())
    staging_columns: dict[int, list[str]] = {}
    target_columns: dict[str, list[str]] = {}
    for fid, typ, _ in data:
        cur.execute(sql.SQL("SELECT * FROM {} LIMIT 0").format(staging_identifier(fid)))
        staging_columns[fid] = [d[0] for d in cur.description]
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position""",
                    (TARGET_TABLES[typ],))
        target_columns[typ] = [r[0] for r in cur.fetchall()]
        unknown = [c for c in staging_columns[fid]
                   if c not in SOURCE_ONLY_COLUMNS and c not in SOURCE_COLUMN_MAP and c not in target_columns[typ]]
        if unknown:
            raise LoadError(f"schema-mismatch: {', '.join(unknown)}")
    return LoadPlan(edition, data, paths, source_hashes, staging_columns, target_columns)


def _match_decisions(cur, plan: LoadPlan):
    """Owner data decisions: each must match exactly 2 rows (exclude) or 1; returns (exclusions per file, applied)."""
    exclusions: dict[int, list] = defaultdict(list)
    applied: list[tuple[str, int]] = []
    for decision in load_data_decisions():
        for fid, typ, _ in plan.data:
            if typ != decision.file_type:
                continue
            if not {"lei_code", "period", "item", *decision.dimensions}.issubset(plan.staging_columns[fid]):
                continue
            condition, params = _decision_condition(decision, plan.staging_columns[fid], cur)
            cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE ").format(staging_identifier(fid)) + condition, params)
            count = cur.fetchone()[0]
            if count == 0:
                continue
            if count != (2 if decision.action == "exclude" else 1):
                raise LoadError(f"data decision {decision.id} matched {count} rows; expected "
                                f"{2 if decision.action == 'exclude' else 1}")
            if decision.action != "exclude":
                raise LoadError(f"data decision action {decision.action} is not implemented")
            exclusions[fid].append((condition, params))
            applied.append((decision.id, count))
    return exclusions, applied


def _check_preflight(cur, import_id: int) -> None:
    collisions = collision_check(cur, import_id)
    if collisions:
        counts = Counter(row["class"] for row in collisions)
        detail = ", ".join(f"class {key}={value}" for key, value in sorted(counts.items()))
        tables = ", ".join(sorted({row["fact_table"] for row in collisions}))
        raise LoadError(f"preflight-collisions: {detail}; duplicate-facts: {tables}; no facts inserted")


def _merge_metadata_banks(cur, path: str) -> None:
    """Banks from TR_Metadata: a bank whose LEI history names an existing bank is merged into it."""
    for lei, name, country, finrep, previous in _metadata(path):
        cur.execute("SELECT bank_id FROM bank WHERE lei = ANY(%s) ORDER BY bank_id LIMIT 1 FOR UPDATE", (previous,))
        predecessor = cur.fetchone()
        if predecessor:
            cur.execute("""UPDATE bank SET previous_leis = (
                               SELECT ARRAY(SELECT DISTINCT value FROM unnest(
                                   COALESCE(previous_leis, ARRAY[]::text[]) || %s || ARRAY[%s]) AS value ORDER BY value))
                           WHERE bank_id=%s""", (previous, lei, predecessor[0]))
            continue
        cur.execute("""INSERT INTO bank(lei,name,country_code,finrep_reported,previous_leis)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (lei) DO UPDATE SET name=EXCLUDED.name,country_code=EXCLUDED.country_code,
                       finrep_reported=EXCLUDED.finrep_reported,previous_leis=EXCLUDED.previous_leis""",
                    (lei, name, country, finrep, previous))


def _create_temp_tables(cur) -> None:
    cur.execute("""CREATE TEMP TABLE tmp_load_versions (
        year integer NOT NULL, quarter integer NOT NULL, version_id integer NOT NULL,
        PRIMARY KEY (year, quarter)) ON COMMIT DROP""")
    cur.execute("CREATE TEMP TABLE tmp_load_banks (lei text PRIMARY KEY, bank_id integer NOT NULL) ON COMMIT DROP")
    cur.execute("""CREATE TEMP TABLE tmp_load_items (
        file_group text NOT NULL, item text NOT NULL, label text NOT NULL,
        indicator_id integer NOT NULL, PRIMARY KEY (file_group, item, label)) ON COMMIT DROP""")


def _file_exclusions(cur, plan: LoadPlan, fid: int, typ: str, decision_exclusions: dict):
    """(SQL fragment ' AND NOT (...)', params) excluding the rows named by this file's data decisions."""
    exclusions = decision_exclusions.get(fid, [])
    if not exclusions:
        for decision in load_data_decisions():
            if decision.file_type != typ:
                continue
            if not {"lei_code", "period", "item", *decision.dimensions}.issubset(plan.staging_columns[fid]):
                continue
            condition, params = _decision_condition(decision, plan.staging_columns[fid], cur)
            cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE ").format(staging_identifier(fid)) + condition, params)
            if cur.fetchone()[0] == 2 and decision.action == "exclude":
                exclusions.append((condition, params))
    if not exclusions:
        return sql.SQL(""), []
    fragment = sql.SQL(" AND NOT (") + sql.SQL(" OR ").join(
        sql.SQL("(") + condition + sql.SQL(")") for condition, _ in exclusions) + sql.SQL(")")
    return fragment, [value for _, params in exclusions for value in params]


def _register_banks(cur, table, non_aggregate: str) -> None:
    """Insert unknown LEIs as banks, then map every staged LEI (current or previous) to its bank_id."""
    cur.execute(sql.SQL("""
        WITH source_leis AS (
            SELECT DISTINCT btrim(s.lei_code) AS lei FROM {} s
            WHERE NOT {} AND btrim(s.lei_code) <> ''
        )
        INSERT INTO bank(lei)
        SELECT l.lei FROM source_leis l
        WHERE NOT EXISTS (
              SELECT 1 FROM bank b
              WHERE btrim(b.lei) = l.lei
                 OR EXISTS (SELECT 1 FROM unnest(b.previous_leis) p WHERE btrim(p) = l.lei))
        ON CONFLICT (lei) DO NOTHING
    """).format(table, sql.SQL(non_aggregate)))
    cur.execute(sql.SQL("""
        WITH source_leis AS (
            SELECT DISTINCT btrim(s.lei_code) AS lei FROM {} s WHERE NOT {}
        )
        INSERT INTO tmp_load_banks(lei, bank_id)
        SELECT l.lei, b.bank_id FROM source_leis l
        JOIN bank b ON btrim(b.lei) = l.lei
            OR EXISTS (SELECT 1 FROM unnest(b.previous_leis) p WHERE btrim(p) = l.lei)
        ON CONFLICT (lei) DO NOTHING
    """).format(table, sql.SQL(non_aggregate)))


def _create_versions(cur, table, name: str, versions: dict, import_id: int, non_aggregate: str, emit) -> None:
    """One dataset_version per (year, quarter) of the file; the previous active version of that quarter is deactivated."""
    cur.execute(sql.SQL("SELECT DISTINCT btrim(period) FROM {} WHERE NOT {}").format(table, sql.SQL(non_aggregate)))
    for period in [row[0] or "" for row in cur.fetchall()]:
        if not re.fullmatch(r"\d{6}", period):
            raise LoadError(f"invalid period in {name}")
        year, month = int(period[:4]), int(period[4:])
        key = (year, (month - 1) // 3 + 1)
        if key in versions:
            continue
        emit(f"creating version {year} Q{key[1]}", 25)
        cur.execute("SELECT version_id FROM dataset_version WHERE year=%s AND quarter=%s AND is_active FOR UPDATE", key)
        old = cur.fetchone()
        if old:
            cur.execute("UPDATE dataset_version SET is_active=false WHERE version_id=%s", old)
        cur.execute("SELECT COALESCE(max(version_no),0)+1 FROM dataset_version WHERE year=%s AND quarter=%s", key)
        version_no = cur.fetchone()[0]
        cur.execute("""INSERT INTO dataset_version(year,quarter,period_end,import_id,version_no,is_active,quality)
                       VALUES (%s,%s,%s,%s,%s,true,%s) RETURNING version_id""",
                    (year, key[1], date(year, month, calendar.monthrange(year, month)[1]), import_id, version_no,
                     Json({"validation": {}, "files": []})))
        versions[key] = cur.fetchone()[0]
    if versions:
        cur.execute("INSERT INTO tmp_load_versions(year,quarter,version_id) VALUES " +
                    ",".join(["(%s,%s,%s)"] * len(versions)) + " ON CONFLICT DO NOTHING",
                    [value for key, value in versions.items() for value in (key[0], key[1], value)])


def _unmapped_indicator(cur, item: str, label: str, group: str, edition: str, indicator_cache: dict) -> int:
    """indicator_id for an item without an SDD mapping (created on first use, cached)."""
    indicator = indicator_cache.get(item)
    if indicator is None:
        cur.execute("""INSERT INTO indicator(std_code,label,report_type,file_group,aggregation_rule,
                       first_seen_edition,last_seen_edition) VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (std_code) DO UPDATE SET label=EXCLUDED.label RETURNING indicator_id""",
                    (item, label or item, "Unclassified", group, "stock", edition, edition))
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT indicator_id FROM indicator WHERE std_code=%s", (item,))
            row = cur.fetchone()
        indicator = indicator_cache[item] = row[0]
    return indicator


def _resolve_items(cur, plan: LoadPlan, fid: int, typ: str, table, non_aggregate: str,
                   indicator_cache: dict, resolution: Counter) -> None:
    """Map each (item, label) of the file to an indicator through indicator_code_map into tmp_load_items."""
    group = typ.replace("tr_", "")
    label_expr = sql.SQL("btrim(label)") if "label" in plan.staging_columns[fid] else sql.SQL("NULL")
    cur.execute(sql.SQL("SELECT btrim(item), coalesce({}, ''), count(*) FROM {} WHERE NOT {} GROUP BY 1,2")
                .format(label_expr, table, sql.SQL(non_aggregate)))
    for item, label, count in cur.fetchall():
        item, label = item or "", label or ""
        cur.execute("""SELECT indicator_id, method FROM indicator_code_map
                       WHERE edition_label=%s AND dataset=%s AND source_item=%s""", (plan.edition, group, item))
        mapped = cur.fetchone()
        if mapped and mapped[0] is None:
            raise LoadError(f"ambiguous item mapping: {plan.edition}/{group}/{item}")
        if mapped:
            indicator, method = mapped
        else:
            method = "unmapped"
            indicator = _unmapped_indicator(cur, item, label, group, plan.edition, indicator_cache)
            cur.execute("""INSERT INTO indicator_code_map
                           (edition_label,dataset,source_item,source_label,indicator_id,method,sdd_file_sha256)
                           VALUES (%s,%s,%s,%s,%s,'unmapped',%s)
                           ON CONFLICT (edition_label,dataset,source_item) DO NOTHING""",
                        (plan.edition, group, item, label, indicator, plan.source_hashes.get("SDD")))
        resolution[method] += count
        cur.execute("INSERT INTO tmp_load_items(file_group,item,label,indicator_id) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (group, item, label, indicator))


def _refuse_conflicting_amounts(cur, plan: LoadPlan, fid: int, typ: str, table, non_aggregate: str,
                                exclusion_sql, exclusion_params: list) -> list[str]:
    """Same identity with different amounts (except tr_cre) refuses the load; returns the duplicate key columns."""
    columns = plan.staging_columns[fid]
    duplicate_key = [c for c in columns if c not in DUPLICATE_IGNORED]
    conflict_key = [c for c in duplicate_key if c != "amount"]
    conflict_columns = sql.SQL(", ").join(sql.Identifier(c) for c in conflict_key)
    if "amount" in columns and conflict_key and typ != "tr_cre":
        cur.execute(sql.SQL("""
            SELECT count(*) FROM (
                SELECT {} FROM {} WHERE NOT {} {} GROUP BY {}
                HAVING count(DISTINCT CASE WHEN btrim(amount) ~ %s
                                           THEN btrim(amount)::numeric::text ELSE btrim(amount) END) > 1
            ) conflicts
        """).format(conflict_columns, table, sql.SQL(non_aggregate), exclusion_sql, conflict_columns),
                    [*exclusion_params, NUMBER_REGEX])
        if cur.fetchone()[0]:
            raise LoadError(f"duplicate-facts: {TARGET_TABLES[typ]}")
    return duplicate_key


def _fact_select_parts(cur, plan: LoadPlan, fid: int, typ: str) -> tuple[list[str], list[str]]:
    """Target column names and their SQL expressions (amount/n_quarters normalised, blanks to NULL)."""
    allowed = [(SOURCE_COLUMN_MAP.get(c, c), c) for c in plan.staging_columns[fid]
               if SOURCE_COLUMN_MAP.get(c, c) in plan.target_columns[typ]]
    fields = ["version_id", "bank_id", "indicator_id"] + [target for target, _ in allowed]
    expressions = ["tv.version_id", "tb.bank_id", "ti.indicator_id"]
    for column, source in allowed:
        quoted = sql.Identifier(source).as_string(cur)
        if column == "amount":
            expressions.append(numeric_amount(quoted))
        elif column == "n_quarters":
            expressions.append(f"CASE WHEN {quoted} ~ '^[+-]?\\d+$' THEN {quoted}::smallint END")
        else:
            expressions.append(blank_text(quoted))
    return fields, expressions


def _version_totals(cur, typ: str, versions: dict, separate: bool = False) -> tuple[int, float]:
    """(row count, amount sum) of the fact table for the loaded versions; `separate` = two queries (after the insert)."""
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in versions)
    table, params = sql.Identifier(TARGET_TABLES[typ]), tuple(versions.values())
    if not separate:
        cur.execute(sql.SQL("SELECT count(*), coalesce(sum(amount), 0) FROM {} WHERE version_id IN ({})").format(
            table, placeholders), params)
        return cur.fetchone()
    cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE version_id IN ({})").format(table, placeholders), params)
    count = cur.fetchone()[0]
    cur.execute(sql.SQL("SELECT coalesce(sum(amount), 0) FROM {} WHERE version_id IN ({})").format(table, placeholders), params)
    return count, cur.fetchone()[0]


def _insert_facts(cur, plan: LoadPlan, fid: int, typ: str, name: str, table, versions: dict, non_aggregate: str,
                  exclusion_sql, exclusion_params: list, quality: dict, emit) -> None:
    """Set-based insert of the file's non-aggregate rows (one copy per identity) into the fact table."""
    group = typ.replace("tr_", "")
    fields, expressions = _fact_select_parts(cur, plan, fid, typ)
    duplicate_key = _refuse_conflicting_amounts(cur, plan, fid, typ, table, non_aggregate, exclusion_sql, exclusion_params)
    duplicate_order = sql.SQL(", ").join(
        sql.SQL(f"CASE WHEN btrim(s.amount) ~ '{NUMBER_REGEX}' THEN btrim(s.amount)::numeric::text ELSE btrim(s.amount) END")
        if c == "amount" else sql.SQL("btrim(s.{})").format(sql.Identifier(c)) for c in duplicate_key)
    source = sql.SQL("(SELECT DISTINCT ON ({}) s.* FROM {} s ORDER BY {}, s.ctid) s").format(
        duplicate_order, table, duplicate_order)
    prior_loaded, prior_amount = _version_totals(cur, typ, versions)
    cur.execute("SET LOCAL enable_nestloop = off")
    cur.execute(sql.SQL("""
        INSERT INTO {} ({})
        SELECT {}
        FROM {}
        JOIN tmp_load_versions tv
          ON tv.year = substring(btrim(s.period), 1, 4)::integer AND tv.quarter = {}
        JOIN tmp_load_banks tb ON tb.lei = btrim(s.lei_code)
        JOIN tmp_load_items ti
          ON ti.file_group = {} AND ti.item = coalesce(btrim(s.item), '') AND ti.label = coalesce({}, '')
        WHERE NOT {}
        ON CONFLICT DO NOTHING
    """).format(sql.Identifier(TARGET_TABLES[typ]), sql.SQL(", ").join(map(sql.Identifier, fields)),
                sql.SQL(", ").join(sql.SQL(expression) for expression in expressions), source,
                sql.SQL(QUARTER_EXPR), sql.Literal(group),
                sql.SQL("btrim(s.label)") if "label" in plan.staging_columns[fid] else sql.SQL("NULL"),
                sql.SQL(non_aggregate), exclusion_sql), exclusion_params)
    emit(f"loaded {name}", 70)
    total_rows, total_amount = _version_totals(cur, typ, versions, separate=True)
    cur.execute(sql.SQL("SELECT count(*) FROM {}").format(table))
    staged = cur.fetchone()[0]
    loaded = total_rows - prior_loaded
    quality[typ]["files"].append(name)
    quality[typ]["rows_staged"] += staged
    quality[typ]["aggregate_rows_excluded"] += staged - loaded
    quality[typ]["rows_loaded"] += loaded
    quality[typ]["amount_sum"] += float(total_amount - prior_amount)


def _post_checks(cur, import_id: int, versions: dict, quality: dict) -> None:
    """Store the quality report on each version and compare loaded rows/amounts with what was staged."""
    for version_id in versions.values():
        cur.execute("UPDATE dataset_version SET quality=%s WHERE version_id=%s",
                    (Json({"validation": {}, "files": list(quality.values())}), version_id))
    for typ, report in quality.items():
        view = {"tr_oth": "v_tr_oth", "tr_cre": "v_tr_cre", "tr_mrk": "v_tr_mrk", "tr_sov": "v_tr_sov"}[typ]
        cur.execute(f"SELECT count(*), coalesce(sum(amount),0), count(*) FILTER (WHERE amount IS NULL) FROM {view} v JOIN dataset_version d USING (version_id) WHERE d.import_id=%s", (import_id,))
        actual_rows, actual_sum, _ = cur.fetchone()
        tolerance = max(1e-6, abs(report["amount_sum"]) * 1e-12)
        if actual_rows != report["rows_loaded"] or abs(float(actual_sum) - report["amount_sum"]) > tolerance:
            raise LoadError(f"load-mismatch in {report['file']}")


def _load(cur, import_id: int, emit):
    """Load one validated import into the fact tables (recipe); returns (version ids, timings).

    lock import -> plan files -> data decisions -> preflight -> banks -> versions + items + facts per file -> checks.
    """
    timings: dict[str, float] = {}
    started = time.perf_counter()
    head = _lock_import(cur, import_id)
    plan = _plan(cur, import_id, str(head[1] or "").strip())
    decision_exclusions, applied_decisions = _match_decisions(cur, plan)
    _check_preflight(cur, import_id)
    timings["reference_files"] = round(time.perf_counter() - started, 2)
    emit("resolving banks and indicators", 10)
    started = time.perf_counter()
    _merge_metadata_banks(cur, plan.paths.get("TR_Metadata", ""))
    _create_temp_tables(cur)
    non_aggregate = aggregate_rows_predicate()
    for fid, typ, _ in plan.data:
        exclusion_sql, exclusion_params = _file_exclusions(cur, plan, fid, typ, decision_exclusions)
        _register_banks(cur, staging_identifier(fid), non_aggregate)
    timings["bank_resolution"] = round(time.perf_counter() - started, 2)
    # KNOWN DEFECT (AUD-2 finding, behaviour preserved): the exclusions of the LAST data file are the ones
    # applied to every file in the insert loop below (they were a loop variable of the bank loop).
    started = time.perf_counter()
    cur.execute("SELECT indicator_id, std_code FROM indicator")
    indicator_cache = {code: indicator_id for indicator_id, code in cur.fetchall()}
    versions: dict = {}
    resolution: Counter = Counter()
    quality = defaultdict(lambda: {"files": [], "rows_staged": 0, "aggregate_rows_excluded": 0,
                                   "rows_loaded": 0, "amount_sum": 0.0})
    for fid, typ, name in plan.data:
        table = staging_identifier(fid)
        _create_versions(cur, table, name, versions, import_id, non_aggregate, emit)
        _resolve_items(cur, plan, fid, typ, table, non_aggregate, indicator_cache, resolution)
        _insert_facts(cur, plan, fid, typ, name, table, versions, non_aggregate,
                      exclusion_sql, exclusion_params, quality, emit)
    timings["fact_inserts"] = round(time.perf_counter() - started, 2)
    started = time.perf_counter()
    _post_checks(cur, import_id, versions, quality)
    timings["post_checks"] = round(time.perf_counter() - started, 2)
    cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'item_resolution',%s)",
                (import_id, Json({"counts": dict(resolution)})))
    for decision_id, rows_affected in applied_decisions:
        cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'data_decision',%s)",
                    (import_id, Json({"id": decision_id, "rows_affected": rows_affected})))
    cur.execute("UPDATE import_batch SET status='loaded' WHERE import_id=%s", (import_id,))
    return list(versions.values()), timings
