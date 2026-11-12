"""Generic PostgreSQL job worker: claims pending jobs with FOR UPDATE SKIP LOCKED, runs the handler registered for the job kind,
keeps a heartbeat while it runs and requeues jobs whose worker disappeared."""

from __future__ import annotations

import threading
import time

from app.core.database import connect
from app.core.worker.registry import Job, JobHandlerRegistry
from app.core.logging import get_logger

logger = get_logger(__name__)


class _Heartbeat:
    """Refreshes job.heartbeat_at from a background thread while the handler runs, so a long job is never mistaken for a dead one."""

    def __init__(self, worker: "Worker", job_id: int, interval: float) -> None:
        self._worker, self._job_id, self._interval = worker, job_id, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._worker.touch(self._job_id)
            except Exception:                                   # a failed heartbeat must never kill the job
                logger.warning("heartbeat of job %s failed", self._job_id, exc_info=True)

    def __enter__(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


class Worker:
    def __init__(
        self,
        registry: JobHandlerRegistry,
        poll_interval: float = 1.0,
        stale_after: int = 900,
        schema: str = "public",
        heartbeat_interval: float = 30.0,
        recovery_interval: float = 60.0,
        max_attempts: int = 3,
    ) -> None:
        self.registry = registry
        self.poll_interval = poll_interval
        self.stale_after = stale_after
        self.schema = schema
        self.heartbeat_interval = heartbeat_interval
        self.recovery_interval = recovery_interval
        self.max_attempts = max_attempts

    # ---- small database operations (one short connection each) -------------------------------------------
    def _execute(self, sql: str, params: tuple = ()) -> tuple[int, tuple | None]:
        conn = connect(self.schema)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    row = cur.fetchone() if cur.description else None
                    return cur.rowcount, row
        finally:
            conn.close()

    def recover_stale_jobs(self) -> int:
        """Jobs still 'processing' whose heartbeat (or start) is older than stale_after seconds go back to 'pending'."""
        conn = connect(self.schema)
        abandoned: list[Job] = []
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """SELECT job_id, import_id, kind, attempts
                       FROM job
                       WHERE status = 'processing'
                         AND COALESCE(heartbeat_at, started_at) < now() - (%s * interval '1 second')
                       FOR UPDATE""",
                    (self.stale_after,),
                )
                rows = cur.fetchall()
                for job_id, import_id, kind, attempts in rows:
                    if attempts < self.max_attempts:
                        cur.execute(
                            """UPDATE job SET status='pending', message='requeued after worker stop',
                                      started_at=NULL, heartbeat_at=NULL
                               WHERE job_id=%s""",
                            (job_id,),
                        )
                    else:
                        cur.execute(
                            """UPDATE job SET status='failed', message='failed',
                                      error=%s, finished_at=now()
                               WHERE job_id=%s""",
                            (f"abandoned after {attempts} attempts (worker stopped)", job_id),
                        )
                        abandoned.append(Job(job_id, import_id, kind, attempts, self.schema))
        finally:
            conn.close()
        for job in abandoned:
            handler = self.registry.give_up_handler(job.kind)
            if handler:
                try:
                    handler(job)
                except Exception:
                    logger.exception("give-up handler failed for job id=%s kind=%s", job.job_id, job.kind)
        count = len(rows)
        if count:
            logger.warning("requeued %s stale job(s)", count)
        return count

    def claim(self) -> Job | None:
        _, row = self._execute(
            """WITH candidate AS (
                 SELECT job_id FROM job WHERE status = 'pending'
                 ORDER BY created_at, job_id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
               )
               UPDATE job
               SET status = 'processing', progress = 0, message = 'processing', attempts = attempts + 1,
                   started_at = now(), heartbeat_at = now()
               WHERE job_id IN (SELECT job_id FROM candidate)
               RETURNING job_id, import_id, kind, attempts"""
        )
        return Job(*row, schema=self.schema) if row else None

    def touch(self, job_id: int) -> None:
        self._execute("UPDATE job SET heartbeat_at = now() WHERE job_id = %s AND status = 'processing'", (job_id,))

    def update_progress(self, job_id: int, message: str, progress: int) -> None:
        self._execute(
            "UPDATE job SET progress = %s, message = %s, heartbeat_at = now() WHERE job_id = %s AND status = 'processing'",
            (max(0, min(progress, 99)), message, job_id),
        )

    def mark_failed(self, job: Job, error: str) -> None:
        self._execute(
            "UPDATE job SET status = 'failed', progress = 100, message = 'failed', error = %s, finished_at = now() WHERE job_id = %s",
            (error, job.job_id),
        )

    def mark_completed(self, job: Job) -> None:
        self._execute(
            "UPDATE job SET status = 'completed', progress = 100, message = 'completed', finished_at = now() WHERE job_id = %s AND status = 'processing'",
            (job.job_id,),
        )

    # ---- the loop ---------------------------------------------------------------------------------------------
    def process_one(self) -> bool:
        job = self.claim()
        if job is None:
            return False
        started = time.perf_counter()
        logger.info("job started id=%s kind=%s import_id=%s", job.job_id, job.kind, job.import_id)
        try:
            handler = self.registry.resolve(job.kind)
            with _Heartbeat(self, job.job_id, self.heartbeat_interval):
                handler(job, lambda message, progress: self.update_progress(job.job_id, message, progress))
            self.mark_completed(job)
            logger.info("job completed id=%s kind=%s duration_ms=%.2f", job.job_id, job.kind, (time.perf_counter() - started) * 1000)
        except Exception as exc:
            logger.exception("Job %s (%s) failed", job.job_id, job.kind)
            try:
                self.mark_failed(job, str(exc))
            except Exception:
                logger.exception("could not mark failed job id=%s kind=%s", job.job_id, job.kind)
            else:
                logger.error("job marked failed id=%s kind=%s", job.job_id, job.kind)
        return True

    def run(self) -> None:
        self.recover_stale_jobs()
        last_recovery = time.monotonic()
        while True:
            if not self.process_one():
                time.sleep(self.poll_interval)
            if time.monotonic() - last_recovery >= self.recovery_interval:
                self.recover_stale_jobs()
                last_recovery = time.monotonic()
