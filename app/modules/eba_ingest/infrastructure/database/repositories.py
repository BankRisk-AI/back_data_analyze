"""All SQL of the ingest module on the lineage tables (import_batch, source_file, job, decision_log, audit_log) and the staging schema.
Functions take a cursor: the caller owns the transaction."""
from __future__ import annotations

from dataclasses import dataclass

from psycopg2 import sql
from psycopg2.extras import Json

from app.shared.staging import STAGING_SCHEMA, staging_identifier


@dataclass(frozen=True)
class SourceFileRow:
    file_id: int
    name: str
    size_bytes: int
    sha256: str
    file_type: str
    encoding: str
    stored_path: str


# ---- registration -----------------------------------------------------------------------------------------
def user_exists(cur, user_id: int) -> bool:
    cur.execute("SELECT 1 FROM app_user WHERE user_id = %s", (user_id,))
    return cur.fetchone() is not None


def find_loaded_duplicate(cur, shas: list[str]) -> tuple[str, int] | None:
    """(file_name, import_id) of a file with one of these hashes in an import that is already 'loaded'."""
    cur.execute(
        """SELECT f.file_name, f.import_id FROM source_file f JOIN import_batch i USING (import_id)
           WHERE i.status = 'loaded' AND f.sha256 = ANY(%s) LIMIT 1""",
        (shas,),
    )
    return cur.fetchone()


def create_import(cur, user_id: int | None, edition_label: str | None) -> int:
    cur.execute("INSERT INTO import_batch(status, created_by, edition_label) VALUES ('uploaded', %s, %s) RETURNING import_id", (user_id, edition_label))
    return cur.fetchone()[0]


def add_source_file(cur, import_id: int, name: str, size: int, sha: str, file_type: str, encoding: str, stored_path: str) -> int:
    cur.execute(
        """INSERT INTO source_file(import_id, file_name, size_bytes, sha256, file_type, encoding, stored_path)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING file_id""",
        (import_id, name, size, sha, file_type, encoding, stored_path),
    )
    return cur.fetchone()[0]


def enqueue_job(cur, import_id: int, kind: str = "validate") -> int:
    cur.execute("INSERT INTO job(import_id, kind, status, progress, message) VALUES (%s, %s, 'pending', 0, 'queued') RETURNING job_id", (import_id, kind))
    return cur.fetchone()[0]


def source_files(cur, import_id: int) -> list[SourceFileRow]:
    cur.execute("SELECT file_id, file_name, size_bytes, sha256, file_type, encoding, stored_path FROM source_file WHERE import_id = %s ORDER BY file_id", (import_id,))
    return [SourceFileRow(*r) for r in cur.fetchall()]


def import_owner(cur, import_id: int) -> int | None:
    cur.execute("SELECT created_by FROM import_batch WHERE import_id = %s", (import_id,))
    row = cur.fetchone()
    return row[0] if row else None


# ---- results of processing --------------------------------------------------------------------------------
def set_import_status(cur, import_id: int, status: str) -> None:
    cur.execute("UPDATE import_batch SET status = %s WHERE import_id = %s", (status, import_id))


def finish_job(cur, import_id: int, job_id: int | None, ok: bool, error: str | None) -> None:
    """Closes the job of the synchronous path (job_id None: the row is created already finished) or of the worker path."""
    status, message = ("completed", "completed") if ok else ("failed", "rejected")
    if job_id is None:
        cur.execute(
            "INSERT INTO job(import_id, kind, status, progress, message, error, finished_at) VALUES (%s, 'validate', %s, 100, %s, %s, now())",
            (import_id, status, message, error),
        )
    else:
        cur.execute("UPDATE job SET status = %s, progress = 100, message = %s, error = %s, finished_at = now() WHERE job_id = %s", (status, message, error, job_id))


def save_report(cur, import_id: int, report: dict) -> None:
    cur.execute("INSERT INTO decision_log(import_id, step, detail) VALUES (%s, 'ingest_report', %s)", (import_id, Json(report)))


def add_audit(cur, user_id: int | None, action: str, entity: str, entity_id: str, detail: dict) -> None:
    cur.execute("INSERT INTO audit_log(user_id, action, entity, entity_id, detail) VALUES (%s, %s, %s, %s, %s)", (user_id, action, entity, entity_id, Json(detail)))


# ---- queries for the interface ----------------------------------------------------------------------------
def latest_report(cur, import_id: int) -> dict | None:
    cur.execute("SELECT detail FROM decision_log WHERE import_id = %s AND step = 'ingest_report' ORDER BY log_id DESC LIMIT 1", (import_id,))
    row = cur.fetchone()
    return row[0] if row else None


def staging_flags(cur, ids: list[int]) -> dict[int, bool]:
    cur.execute("SELECT import_id, bool_or(to_regclass(%s || '.f' || file_id) IS NOT NULL) FROM source_file WHERE import_id = ANY(%s) GROUP BY import_id", (STAGING_SCHEMA, ids))
    return dict(cur.fetchall())


def import_head(cur, import_id: int):
    cur.execute(
        """SELECT i.status, i.edition_label, i.created_at, u.username, j.job_id, j.status, j.progress, j.message, j.error
           FROM import_batch i
           LEFT JOIN app_user u ON u.user_id = i.created_by
           LEFT JOIN LATERAL (SELECT job_id, status, progress, message, error FROM job WHERE import_id = i.import_id AND kind = 'validate' ORDER BY job_id DESC LIMIT 1) j ON true
           WHERE i.import_id = %s""",
        (import_id,),
    )
    return cur.fetchone()


def list_import_rows(cur, limit: int):
    cur.execute(
        """SELECT i.import_id, i.status, i.edition_label, i.created_at, u.username,
                  (SELECT count(*) FROM source_file f WHERE f.import_id = i.import_id),
                  COALESCE((SELECT array_agg(f.file_name ORDER BY f.file_id) FROM source_file f WHERE f.import_id = i.import_id), '{}'),
                  j.error, j.status, j.progress, j.message
           FROM import_batch i LEFT JOIN app_user u ON u.user_id = i.created_by
           LEFT JOIN LATERAL (SELECT error, status, progress, message FROM job WHERE import_id = i.import_id AND kind = 'validate' ORDER BY job_id DESC LIMIT 1) j ON true
           ORDER BY i.import_id DESC LIMIT %s""",
        (limit,),
    )
    return cur.fetchall()


def drop_staging_tables(cur, import_id: int) -> int:
    cur.execute("SELECT file_id FROM source_file WHERE import_id = %s", (import_id,))
    ids = [r[0] for r in cur.fetchall()]
    for fid in ids:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(staging_identifier(fid)))
    return len(ids)
