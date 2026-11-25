"""After-panel-rebuild hook: queue a score_panel job for every champion model."""
from __future__ import annotations


def queue_score_jobs(conn, event) -> None:
    """One `score_panel` job per champion; the worker rescoring replaces the model's predictions."""
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT model_id FROM ml_model WHERE status='champion'")
            champions = [model_id for (model_id,) in cur.fetchall()]
            if not champions:
                return
            cur.execute("INSERT INTO import_batch(status) VALUES ('uploaded') RETURNING import_id")
            import_id = cur.fetchone()[0]
            for model_id in champions:
                cur.execute("""INSERT INTO job(import_id,kind,status,message)
                               VALUES (%s,'score_panel','pending',%s)""",
                            (import_id, f"score_panel model={model_id}"))
