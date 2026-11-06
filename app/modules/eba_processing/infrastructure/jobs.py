"""Queue and storage side of the validation: its job rows, the report in decision_log and the import status."""
from __future__ import annotations

from psycopg2.extras import Json

from app.modules.eba_processing.domain import VALIDATION_JOB_KIND, VALIDATION_STEP


def active_job(cur, import_id: int):
    cur.execute("SELECT job_id, status FROM job WHERE import_id = %s AND kind = %s AND status IN ('pending', 'processing') ORDER BY job_id DESC LIMIT 1", (import_id, VALIDATION_JOB_KIND))
    return cur.fetchone()


def enqueue(cur, import_id: int) -> int:
    cur.execute("INSERT INTO job(import_id, kind, status, progress, message) VALUES (%s, %s, 'pending', 0, 'queued') RETURNING job_id", (import_id, VALIDATION_JOB_KIND))
    return cur.fetchone()[0]


def latest_job(cur, import_id: int) -> dict | None:
    cur.execute("SELECT job_id, status, progress, message, error, created_at, finished_at FROM job WHERE import_id = %s AND kind = %s ORDER BY job_id DESC LIMIT 1", (import_id, VALIDATION_JOB_KIND))
    r = cur.fetchone()
    if not r:
        return None
    return {"job_id": r[0], "status": r[1], "progress": r[2], "message": r[3], "error": r[4], "created_at": r[5].isoformat(), "finished_at": r[6].isoformat() if r[6] else None}


def save_report(cur, import_id: int, report: dict) -> None:
    cur.execute("INSERT INTO decision_log(import_id, step, detail) VALUES (%s, %s, %s)", (import_id, VALIDATION_STEP, Json(report)))


def latest_report(cur, import_id: int) -> dict | None:
    cur.execute("SELECT detail FROM decision_log WHERE import_id = %s AND step = %s ORDER BY log_id DESC LIMIT 1", (import_id, VALIDATION_STEP))
    r = cur.fetchone()
    return r[0] if r else None


def set_status_after_validation(cur, import_id: int, can_proceed: bool) -> str | None:
    """'uploaded' <-> 'validated' only; every other status (approved, loading, loaded, rejected ...) is left alone."""
    cur.execute("SELECT status FROM import_batch WHERE import_id = %s", (import_id,))
    row = cur.fetchone()
    if row is None:
        return None
    current = row[0]
    target = "validated" if can_proceed else "uploaded"
    if current in ("uploaded", "validated") and current != target:
        cur.execute("UPDATE import_batch SET status = %s WHERE import_id = %s", (target, import_id))
        return target
    return current


def import_status(cur, import_id: int) -> str | None:
    cur.execute("SELECT status FROM import_batch WHERE import_id = %s", (import_id,))
    r = cur.fetchone()
    return r[0] if r else None
