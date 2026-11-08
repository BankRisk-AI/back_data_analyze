"""Atomic promotion of validated staging data into the Chapter 4 tables."""
from __future__ import annotations

import calendar
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from psycopg2 import sql
from psycopg2.extras import Json

from app.core.config import get_schema
from app.core.database import connect
from app.core.exceptions import AppError
from app.modules.eba_ingest.infrastructure.database import repositories as repo
from app.shared.staging import staging_identifier

LOAD_KIND = "load"
NUMBER = r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"


class LoadError(AppError):
    kind = "load-error"
    status = 409
    title = "Import could not be loaded"


def enqueue_load(import_id: int, schema: str | None = None) -> dict:
    conn = connect(schema or get_schema())
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM import_batch WHERE import_id=%s", (import_id,))
            row = cur.fetchone()
            if not row:
                raise LoadError(f"import {import_id} does not exist")
            if row[0] == "loaded":
                raise LoadError(f"import {import_id} is already loaded")
            if row[0] not in ("validated", "failed", "approved"):
                raise LoadError(f"import {import_id} is not ready for load: {row[0]}")
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


def _amount(value):
    return None if value is None or not str(value).strip() else float(value) if re.fullmatch(NUMBER, str(value).strip()) else None


def _column(cur, table: str, name: str):
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s", (table, name))
    return cur.fetchone() is not None


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
    for fid, typ, _ in data:
        if not all(_column(cur, {"tr_oth": "fact_oth", "tr_cre": "fact_cre", "tr_mrk": "fact_mrk"}[typ], c)
                   for c in ("amount", "version_id", "bank_id", "indicator_id")):
            raise LoadError("schema-mismatch")
    emit("resolving banks and indicators", 10)
    for lei, name, country, finrep, previous in _metadata(paths.get("TR_Metadata", "")):
        cur.execute("""INSERT INTO bank(lei,name,country_code,finrep_reported,previous_leis)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (lei) DO UPDATE SET name=EXCLUDED.name,country_code=EXCLUDED.country_code,
                       finrep_reported=EXCLUDED.finrep_reported,previous_leis=EXCLUDED.previous_leis""",
                    (lei, name, country, finrep, previous))
    cur.execute("SELECT bank_id, lei, previous_leis FROM bank")
    bank_cache = {}
    for bank_id, current_lei, previous_leis in cur.fetchall():
        bank_cache[str(current_lei).strip()] = bank_id
        bank_cache.update({str(lei).strip(): bank_id for lei in (previous_leis or [])})
    indicator_cache = {}
    cur.execute("SELECT indicator_id, std_code FROM indicator")
    indicator_cache.update({code: indicator_id for indicator_id, code in cur.fetchall()})
    target_tables = {"tr_oth": "fact_oth", "tr_cre": "fact_cre", "tr_mrk": "fact_mrk"}
    target_columns = {}
    for typ, target in target_tables.items():
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema = current_schema() AND table_name = %s""", (target,))
        target_columns[typ] = {r[0] for r in cur.fetchall()}
    versions = {}
    resolution = Counter()
    quality = defaultdict(dict)
    for fid, typ, name in data:
        table = staging_identifier(fid)
        cur.execute(sql.SQL("SELECT * FROM {}").format(table))
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
        total_rows = len(rows)
        period_idx = columns.index("period")
        lei_idx = columns.index("lei_code")
        item_idx = columns.index("item")
        label_idx = columns.index("label") if "label" in columns else None
        amount_idx = columns.index("amount")
        bucket = 0
        for row_number, row in enumerate(rows, 1):
            lei, country, period = str(row[lei_idx] or "").strip(), str(row[columns.index("nsa")] or "").strip(), str(row[period_idx] or "").strip()
            if re.fullmatch(r"x+", lei, re.I) or country.upper() == "OT":
                bucket += 1
                continue
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
                last = cur.execute("SELECT 1")  # keep transaction explicit
                cur.execute("SELECT COALESCE(max(version_no),0)+1 FROM dataset_version WHERE year=%s AND quarter=%s", key)
                version_no = cur.fetchone()[0]
                cur.execute("""INSERT INTO dataset_version(year,quarter,period_end,import_id,version_no,is_active,quality)
                               VALUES (%s,%s,%s,%s,%s,true,%s) RETURNING version_id""",
                            (year, quarter, date(year, month, calendar.monthrange(year, month)[1]), import_id, version_no, Json({"validation": {}, "files": []})))
                versions[key] = cur.fetchone()[0]
            item = str(row[item_idx] or "").strip()
            group = typ.replace("tr_", "")
            info = sdd_map.get(item)
            method = "sdd" if info else "label"
            if not info and label_idx is not None:
                std = label_map.get((group, str(row[label_idx] or "").strip()))
                info = sdd_map.get(std) if std else None
            if not info:
                method = "own"
                std = item
                info = {"label": str(row[label_idx] or item).strip() if label_idx is not None else item, "group": group, "category": "Unclassified"}
            else:
                std = info.get("std_code", item)
            resolution[method] += 1
            indicator = indicator_cache.get(std)
            if indicator is None:
                cur.execute("""INSERT INTO indicator(std_code,label,report_type,file_group,aggregation_rule)
                               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (std_code) DO NOTHING
                               RETURNING indicator_id""",
                            (std, info["label"], info.get("category") or "Unclassified", group,
                             "ratio" if "ratio" in info["label"].lower() else "flow" if info.get("category") == "P&L" else "stock"))
                indicator = cur.fetchone()
                if indicator is None:
                    cur.execute("SELECT indicator_id FROM indicator WHERE std_code=%s", (std,))
                    indicator = cur.fetchone()
                indicator = indicator[0]
                indicator_cache[std] = indicator
            bank_id = bank_cache.get(lei)
            if bank_id is None:
                cur.execute("INSERT INTO bank(lei) VALUES (%s) ON CONFLICT (lei) DO NOTHING RETURNING bank_id", (lei,))
                bank_row = cur.fetchone()
                if bank_row is None:
                    cur.execute("SELECT bank_id FROM bank WHERE lei=%s", (lei,))
                    bank_row = cur.fetchone()
                bank_id = bank_row[0]
                bank_cache[lei] = bank_id
            vals = {c: row[columns.index(c)] if c in columns else None for c in columns}
            target = target_tables[typ]
            source_only = {"lei_code", "nsa", "period", "item", "label"}
            unknown = [c for c in columns if c not in source_only and c not in target_columns[typ]]
            if unknown:
                raise LoadError(f"schema-mismatch: {', '.join(unknown)}")
            allowed = [c for c in columns if c not in source_only]
            fields = ["version_id", "bank_id", "indicator_id"] + allowed
            def typed(c):
                value = str(vals[c] or "").strip()
                if not value:
                    return None
                if c == "amount":
                    return _amount(value)
                if c == "n_quarters":
                    return int(value) if re.fullmatch(r"[+-]?\d+", value) else None
                return value
            values = [versions[key], bank_id, indicator] + [typed(c) for c in allowed]
            placeholders = sql.SQL(",").join(sql.Placeholder() for _ in fields)
            cur.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(sql.Identifier(target), sql.SQL(",").join(map(sql.Identifier, fields)), placeholders), values)
            if row_number == total_rows or row_number % 10000 == 0:
                emit(f"loading {name}: {row_number}/{total_rows}", 25 + int(45 * row_number / max(total_rows, 1)))
        quality[typ] = {"file": name, "rows_staged": len(rows), "aggregate_rows_excluded": bucket,
                        "rows_loaded": len(rows) - bucket, "amount_sum": sum(_amount(r[amount_idx]) or 0 for r in rows if not (re.fullmatch(r"x+", str(r[lei_idx] or "").strip(), re.I) or str(r[columns.index("nsa")] or "").upper() == "OT"))}
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
            cur.execute("UPDATE import_batch SET status='loading' WHERE import_id=%s", (import_id,))
            versions = _load(cur, import_id, emit)
            cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_report',%s)",
                        (import_id, Json({"versions": versions, "staging_dropped": None})))
            conn.commit()
        dropped = __import__("os").getenv("EBA_DROP_STAGING_AFTER_LOAD", "true").lower() != "false"
        if dropped:
            try:
                with conn, conn.cursor() as cur:
                    repo.drop_staging_tables(cur, import_id)
            except Exception:
                dropped = False
        with conn, conn.cursor() as cur:
            cur.execute("INSERT INTO decision_log(import_id,step,detail) VALUES (%s,'load_report',%s)",
                        (import_id, Json({"staging_dropped": dropped})))
    except Exception:
        conn.rollback()
        failed_conn = connect(schema)
        with failed_conn, failed_conn.cursor() as cur:
            cur.execute("UPDATE import_batch SET status='failed' WHERE import_id=%s AND status <> 'loaded'", (import_id,))
        failed_conn.close()
        raise
    finally:
        conn.close()
