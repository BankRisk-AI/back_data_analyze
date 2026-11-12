"""Atomic promotion of validated staging data into the Chapter 4 tables."""
from __future__ import annotations

import calendar
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from psycopg2 import sql
from psycopg2.errors import UniqueViolation
from psycopg2.extras import Json

from app.core.config import get_schema
from app.core.database import connect
from app.core.exceptions import AppError
from app.modules.eba_ingest.infrastructure.database import repositories as repo
from app.shared.staging import staging_identifier
from app.shared.sql.predicates import aggregate_rows_predicate, blank_text, numeric_amount

LOAD_KIND = "load"
class LoadError(AppError):
    kind = "load-error"
    status = 409
    title = "Import could not be loaded"


def _check_load_status(cur, import_id: int) -> None:
    cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (import_id,))
    row = cur.fetchone()
    if not row:
        raise LoadError(f"import {import_id} does not exist")
    status = row[0]
    if status in ("validated", "approved"):
        return
    if status != "failed":
        raise LoadError(f"import {import_id} cannot be loaded: status is {status}; expected validated or approved")

    cur.execute(
        "SELECT kind, status FROM job WHERE import_id=%s ORDER BY job_id DESC LIMIT 2",
        (import_id,),
    )
    jobs = cur.fetchall()
    retry_job = jobs and jobs[0] == ("load", "failed")
    retry_job = retry_job or (
        jobs
        and jobs[0] == ("load", "processing")
        and len(jobs) > 1
        and jobs[1] == ("load", "failed")
    )
    if not retry_job:
        raise LoadError(f"import {import_id} cannot be retried: latest job is not a failed load")

    cur.execute(
        "SELECT detail FROM decision_log WHERE import_id=%s AND step='validation_report' ORDER BY log_id DESC LIMIT 1",
        (import_id,),
    )
    report = cur.fetchone()
    if not report or not (report[0] or {}).get("summary", {}).get("can_proceed", False):
        raise LoadError(f"import {import_id} cannot be retried: latest validation report does not allow proceeding")

    cur.execute(
        """SELECT count(*) FROM source_file
           WHERE import_id=%s AND file_type IN ('tr_oth','tr_cre','tr_mrk')
             AND to_regclass(%s || '.f' || file_id) IS NULL""",
        (import_id, "staging"),
    )
    missing = cur.fetchone()[0]
    if missing:
        raise LoadError(f"import {import_id} cannot be retried: {missing} data staging table(s) are missing")


def enqueue_load(import_id: int, schema: str | None = None) -> dict:
    conn = connect(schema or get_schema())
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (import_id,))
            row = cur.fetchone()
            if row and row[0] == "loaded":
                raise LoadError(f"import {import_id} is already loaded")
            _check_load_status(cur, import_id)
            cur.execute("SELECT job_id,status FROM job WHERE import_id=%s AND kind=%s AND status IN ('pending','processing') ORDER BY job_id DESC LIMIT 1", (import_id, LOAD_KIND))
            active = cur.fetchone()
            if active:
                return {"job_id": active[0], "status": active[1], "created": False}
            cur.execute("INSERT INTO job(import_id,kind,status,message) VALUES (%s,%s,'pending','queued') RETURNING job_id", (import_id, LOAD_KIND))
            return {"job_id": cur.fetchone()[0], "status": "pending", "created": True}
    finally:
        conn.close()


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
    rows = list(_workbook_rows(path, "Bank list"))
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
        out.append((lei, record.get("name") or None, record.get("country", "")[:2] or None,
                    str(record.get("finrep", "")).lower().startswith("yes"), sorted(previous)))
    return out


def _load(cur, import_id: int, emit):
    cur.execute("SELECT status, edition_label, created_by FROM import_batch WHERE import_id = %s FOR UPDATE", (import_id,))
    head = cur.fetchone()
    if not head:
        raise LoadError(f"import {import_id} does not exist")
    if head[0] not in ("validated", "failed", "approved", "loading"):
        raise LoadError(f"import {import_id} is not ready for load: {head[0]}")
    cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_request',%s)",
                (import_id, Json({"edition": head[1]})))
    cur.execute("SELECT file_id, file_type, file_name FROM source_file WHERE import_id = %s ORDER BY file_id", (import_id,))
    files = cur.fetchall()
    data = [(fid, typ, name) for fid, typ, name in files if typ in {"tr_oth", "tr_cre", "tr_mrk"}]
    if not data:
        raise LoadError("no tr_oth, tr_cre or tr_mrk data files")
    paths = _reference_files(cur, import_id)
    sdd_map, label_map = _sdd(paths["SDD"], head[1], {x[1] for x in data}) if "SDD" in paths else ({}, {})
    target_tables = {"tr_oth": "fact_oth", "tr_cre": "fact_cre", "tr_mrk": "fact_mrk"}
    source_only = {"lei_code", "nsa", "period", "item", "label"}
    target_columns: dict[str, list[str]] = {}
    staging_columns: dict[int, list[str]] = {}
    for fid, typ, name in data:
        table = staging_identifier(fid)
        cur.execute(sql.SQL("SELECT * FROM {} LIMIT 0").format(table))
        columns = [d[0] for d in cur.description]
        staging_columns[fid] = columns
        cur.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = %s
               ORDER BY ordinal_position""",
            (target_tables[typ],),
        )
        target_columns[typ] = [r[0] for r in cur.fetchall()]
        unknown = [c for c in columns if c not in source_only and c not in target_columns[typ]]
        if unknown:
            raise LoadError(f"schema-mismatch: {', '.join(unknown)}")

    emit("resolving banks and indicators", 10)
    for lei, name, country, finrep, previous in _metadata(paths.get("TR_Metadata", "")):
        cur.execute("""INSERT INTO bank(lei,name,country_code,finrep_reported,previous_leis)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (lei) DO UPDATE SET name=EXCLUDED.name,country_code=EXCLUDED.country_code,
                       finrep_reported=EXCLUDED.finrep_reported,previous_leis=EXCLUDED.previous_leis""",
                    (lei, name, country, finrep, previous))
    cur.execute("""
        CREATE TEMP TABLE tmp_load_versions (
            year integer NOT NULL, quarter integer NOT NULL, version_id integer NOT NULL,
            PRIMARY KEY (year, quarter)
        ) ON COMMIT DROP
    """)
    cur.execute("""
        CREATE TEMP TABLE tmp_load_banks (
            lei text PRIMARY KEY, bank_id integer NOT NULL
        ) ON COMMIT DROP
    """)
    cur.execute("""
        CREATE TEMP TABLE tmp_load_items (
            file_group text NOT NULL, item text NOT NULL, label text NOT NULL,
            indicator_id integer NOT NULL, PRIMARY KEY (file_group, item, label)
        ) ON COMMIT DROP
    """)
    non_aggregate = aggregate_rows_predicate()
    for fid, typ, _ in data:
        table = staging_identifier(fid)
        cur.execute(sql.SQL("""
            WITH source_leis AS (
                SELECT DISTINCT btrim(s.lei_code) AS lei
                FROM {} s
                WHERE NOT {} AND btrim(s.lei_code) <> ''
            )
            INSERT INTO bank(lei)
            SELECT l.lei
            FROM source_leis l
            WHERE NOT EXISTS (
                  SELECT 1 FROM bank b
                  WHERE btrim(b.lei) = l.lei
                     OR EXISTS (SELECT 1 FROM unnest(b.previous_leis) p
                                WHERE btrim(p) = l.lei)
              )
            ON CONFLICT (lei) DO NOTHING
        """).format(table, sql.SQL(non_aggregate)))
        cur.execute(sql.SQL("""
            WITH source_leis AS (
                SELECT DISTINCT btrim(s.lei_code) AS lei
                FROM {} s
                WHERE NOT {}
            )
            INSERT INTO tmp_load_banks(lei, bank_id)
            SELECT l.lei, b.bank_id
            FROM source_leis l
            JOIN bank b ON btrim(b.lei) = l.lei
                OR EXISTS (SELECT 1 FROM unnest(b.previous_leis) p
                           WHERE btrim(p) = l.lei)
            ON CONFLICT (lei) DO NOTHING
        """).format(table, sql.SQL(non_aggregate)))

    indicator_cache = {}
    cur.execute("SELECT indicator_id, std_code FROM indicator")
    indicator_cache.update({code: indicator_id for indicator_id, code in cur.fetchall()})
    versions = {}
    resolution = Counter()
    quality = defaultdict(dict)
    for fid, typ, name in data:
        table = staging_identifier(fid)
        cur.execute(sql.SQL("SELECT DISTINCT btrim(period) FROM {} WHERE NOT {}").format(table, sql.SQL(non_aggregate)))
        periods = [row[0] or "" for row in cur.fetchall()]
        for period in periods:
            if not re.fullmatch(r"\d{6}", period):
                raise LoadError(f"invalid period in {name}")
            year, month = int(period[:4]), int(period[4:])
            quarter = (month - 1) // 3 + 1
            key = (year, quarter)
            if key not in versions:
                emit(f"creating version {year} Q{quarter}", 25)
                cur.execute("SELECT version_id FROM dataset_version WHERE year=%s AND quarter=%s AND is_active FOR UPDATE", key)
                old = cur.fetchone()
                if old:
                    cur.execute("UPDATE dataset_version SET is_active=false WHERE version_id=%s", old)
                cur.execute("SELECT COALESCE(max(version_no),0)+1 FROM dataset_version WHERE year=%s AND quarter=%s", key)
                version_no = cur.fetchone()[0]
                cur.execute("""INSERT INTO dataset_version(year,quarter,period_end,import_id,version_no,is_active,quality)
                               VALUES (%s,%s,%s,%s,%s,true,%s) RETURNING version_id""",
                            (year, quarter, date(year, month, calendar.monthrange(year, month)[1]), import_id, version_no, Json({"validation": {}, "files": []})))
                versions[key] = cur.fetchone()[0]
        if versions:
            cur.execute("INSERT INTO tmp_load_versions(year,quarter,version_id) VALUES " +
                        ",".join(["(%s,%s,%s)"] * len(versions)) + " ON CONFLICT DO NOTHING",
                        [value for key, value in versions.items() for value in (key[0], key[1], value)])

        group = typ.replace("tr_", "")
        cur.execute(sql.SQL("SELECT btrim(item), coalesce(btrim(label), ''), count(*) FROM {} WHERE NOT {} GROUP BY 1,2")
                    .format(table, sql.SQL(non_aggregate)))
        for item, label, count in cur.fetchall():
            item, label = item or "", label or ""
            info = sdd_map.get(item)
            method = "sdd" if info else "label"
            if not info:
                std = label_map.get((group, label))
                info = sdd_map.get(std) if std else None
            if not info:
                method = "own"
                std = item
                info = {"label": label or item, "group": group, "category": "Unclassified"}
            else:
                std = info.get("std_code", item)
            resolution[method] += count
            indicator = indicator_cache.get(std)
            if indicator is None:
                cur.execute("""INSERT INTO indicator(std_code,label,report_type,file_group,aggregation_rule)
                               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (std_code) DO NOTHING
                               RETURNING indicator_id""",
                            (std, info["label"], info.get("category") or "Unclassified", group,
                             "ratio" if "ratio" in info["label"].lower() else "flow" if info.get("category") == "P&L" else "stock"))
                indicator_row = cur.fetchone()
                if indicator_row is None:
                    cur.execute("SELECT indicator_id FROM indicator WHERE std_code=%s", (std,))
                    indicator_row = cur.fetchone()
                indicator = indicator_row[0]
                indicator_cache[std] = indicator
            cur.execute("INSERT INTO tmp_load_items(file_group,item,label,indicator_id) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (group, item, label, indicator))

        columns = staging_columns[fid]
        allowed = [c for c in target_columns[typ] if c in columns]
        fields = ["version_id", "bank_id", "indicator_id"] + allowed
        expressions = ["tv.version_id", "tb.bank_id", "ti.indicator_id"]
        for column in allowed:
            quoted = sql.Identifier(column).as_string(cur)
            if column == "amount":
                expressions.append(numeric_amount(quoted))
            elif column == "n_quarters":
                expressions.append(f"CASE WHEN {quoted} ~ '^[+-]?\\d+$' THEN {quoted}::smallint END")
            else:
                expressions.append(blank_text(quoted))
        quarter_expr = "((substring(btrim(s.period), 5, 2)::integer - 1) / 3 + 1)"
        cur.execute("SET LOCAL enable_nestloop = off")
        cur.execute(sql.SQL("""
            INSERT INTO {} ({})
            SELECT {}
            FROM {} s
            JOIN tmp_load_versions tv
              ON tv.year = substring(btrim(s.period), 1, 4)::integer
             AND tv.quarter = {}
            JOIN tmp_load_banks tb ON tb.lei = btrim(s.lei_code)
            JOIN tmp_load_items ti
              ON ti.file_group = {}
             AND ti.item = coalesce(btrim(s.item), '')
             AND ti.label = coalesce(btrim(s.label), '')
            WHERE NOT {}
        """).format(sql.Identifier(target_tables[typ]),
                    sql.SQL(", ").join(map(sql.Identifier, fields)),
                    sql.SQL(", ").join(sql.SQL(expression) for expression in expressions),
                    table, sql.SQL(quarter_expr), sql.Literal(group), sql.SQL(non_aggregate)))
        emit(f"loaded {name}", 70)
        cur.execute(sql.SQL("""
            SELECT count(*), count(*) FILTER (WHERE NOT {}),
                   coalesce(sum({}) FILTER (WHERE NOT {}), 0)
            FROM {}
        """).format(sql.SQL(non_aggregate), sql.SQL(numeric_amount("amount")),
                    sql.SQL(non_aggregate), table))
        staged, loaded, amount_sum = cur.fetchone()
        quality[typ] = {"file": name, "rows_staged": staged, "aggregate_rows_excluded": staged - loaded,
                        "rows_loaded": loaded, "amount_sum": float(amount_sum)}
    for key, version_id in versions.items():
        cur.execute("UPDATE dataset_version SET quality=%s WHERE version_id=%s", (Json({"validation": {}, "files": list(quality.values())}), version_id))
    for typ, report in quality.items():
        view = {"tr_oth": "v_tr_oth", "tr_cre": "v_tr_cre", "tr_mrk": "v_tr_mrk"}[typ]
        cur.execute(f"SELECT count(*), coalesce(sum(amount),0), count(*) FILTER (WHERE amount IS NULL) FROM {view} v JOIN dataset_version d USING (version_id) WHERE d.import_id=%s", (import_id,))
        actual_rows, actual_sum, actual_empty = cur.fetchone()
        tolerance = max(1e-6, abs(report["amount_sum"]) * 1e-12)
        if actual_rows != report["rows_loaded"] or abs(float(actual_sum) - report["amount_sum"]) > tolerance:
            raise LoadError(f"load-mismatch in {report['file']}")
    cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'item_resolution',%s)", (import_id, Json({"counts": dict(resolution)})))
    cur.execute("UPDATE import_batch SET status='loaded' WHERE import_id=%s", (import_id,))
    return list(versions.values())


def run_load(import_id: int, schema: str | None = None, emit=None) -> None:
    schema = schema or get_schema()
    emit = emit or (lambda message, progress: None)
    conn = connect(schema)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM import_batch WHERE import_id=%s FOR UPDATE", (import_id,))
            current = cur.fetchone()
            if not current:
                raise LoadError(f"import {import_id} does not exist")
            if current[0] == "loaded":
                raise LoadError(f"import {import_id} is already loaded")
            _check_load_status(cur, import_id)
            cur.execute("UPDATE import_batch SET status='loading' WHERE import_id=%s", (import_id,))
            versions = _load(cur, import_id, emit)
            cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_report',%s)",
                        (import_id, Json({"versions": versions, "staging_dropped": None})))
            conn.commit()
        import os
        dropped = os.getenv("EBA_DROP_STAGING_AFTER_LOAD", "true").lower() != "false"
        if dropped:
            try:
                with conn, conn.cursor() as cur:
                    repo.drop_staging_tables(cur, import_id)
            except Exception:
                dropped = False
        with conn, conn.cursor() as cur:
            cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_report',%s)",
                        (import_id, Json({"staging_dropped": dropped})))
    except Exception as exc:
        conn.rollback()
        failed_conn = connect(schema)
        with failed_conn, failed_conn.cursor() as cur:
            cur.execute("UPDATE import_batch SET status='failed' WHERE import_id=%s AND status <> 'loaded'", (import_id,))
        failed_conn.close()
        if isinstance(exc, UniqueViolation):
            constraint = getattr(exc.diag, "constraint_name", "") or ""
            table = next((name for name in ("fact_oth", "fact_cre", "fact_mrk") if name in constraint), "fact")
            raise LoadError(f"duplicate-facts: {table}") from exc
        raise
    finally:
        conn.close()
