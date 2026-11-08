from __future__ import annotations

from app.core.database import connect
from app.core.exceptions import NotFoundError


def periods(schema: str) -> list[dict]:
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """SELECT v.version_id, v.year, v.quarter, v.period_end, v.import_id,
                          (SELECT count(*) FROM fact_oth f WHERE f.version_id=v.version_id),
                          (SELECT count(*) FROM fact_cre f WHERE f.version_id=v.version_id),
                          (SELECT count(*) FROM fact_mrk f WHERE f.version_id=v.version_id)
                   FROM dataset_version v WHERE v.is_active ORDER BY v.year, v.quarter, v.version_no"""
            )
            return [{"version_id": r[0], "year": r[1], "quarter": r[2], "period_end": r[3].isoformat(),
                     "import_id": r[4], "rows_oth": r[5], "rows_cre": r[6], "rows_mrk": r[7]} for r in cur.fetchall()]
    finally:
        conn.close()


def preview(version_id: int, dataset: str, schema: str, page: int, page_size: int) -> dict:
    dataset = dataset.removeprefix("tr_")
    views = {"oth": "v_tr_oth", "cre": "v_tr_cre", "mrk": "v_tr_mrk"}
    if dataset not in views:
        raise NotFoundError(f"unknown dataset {dataset}")
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            view = views[dataset]
            cur.execute("SELECT 1 FROM dataset_version WHERE version_id=%s AND is_active", (version_id,))
            if not cur.fetchone():
                raise NotFoundError(f"active version {version_id} does not exist")
            cur.execute(f"SELECT count(*) FROM {view} WHERE version_id=%s", (version_id,))
            total = cur.fetchone()[0]
            cur.execute(f"SELECT * FROM {view} WHERE version_id=%s ORDER BY version_id, lei_code, item LIMIT %s OFFSET %s",
                        (version_id, page_size, (page - 1) * page_size))
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
            return {"version_id": version_id, "dataset": dataset, "columns": names, "rows": rows,
                    "total": total, "page": page, "page_size": page_size,
                    "pages": max(1, (total + page_size - 1) // page_size)}
    finally:
        conn.close()
