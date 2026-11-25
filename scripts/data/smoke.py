"""Stage 2 smoke rehearsal: load a small sample of every edition into the TEST database.

    python -m scripts.data.smoke --target test [--rebuild-sample]

Writes docs/design/stage2_smoke.md. WIPES the test database first; refuses --target prod.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from scripts.common import (EDITIONS, edition_files, make_import_worker, run_job, select_target,
                            stage_job_id, target_summary)
from scripts.data.reset_data import recreate_staging_schema
from scripts.data.smoke_sample import DEFAULT_LEIS, build_sample

REPORT = Path("docs/design/stage2_smoke.md")


def _truncate_test_tables() -> None:
    """Truncate every table of the test schema (schema_migrations kept)."""
    from psycopg2 import sql
    from app.core.config import get_schema
    from app.core.database import connect
    with connect(get_schema()) as conn, conn.cursor() as cur:
        cur.execute("""SELECT tablename FROM pg_tables
                       WHERE schemaname=current_schema() AND tablename <> 'schema_migrations'""")
        tables = [row[0] for row in cur.fetchall()]
        if tables:
            cur.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(t) for t in tables)))


def _run_edition(worker, sample_root: Path, label: str) -> tuple[str, str, str, float]:
    """Run stage -> validate -> load for one sample edition; (label, phase, outcome, error, secs)."""
    from app.core.config import get_schema, get_storage_dir, get_user_id
    from app.modules.eba_ingest.application.load_service import enqueue_load
    from app.modules.eba_ingest.application.upload_service import enqueue_import
    from app.modules.eba_processing.application.validation import enqueue_validation
    phase, error, started = "register", "", time.perf_counter()
    try:
        import_id = enqueue_import(edition_files(sample_root / label), get_storage_dir(),
                                   user_id=get_user_id(), edition_label=label, schema=get_schema())
        steps = (("stage", lambda: stage_job_id(import_id)),
                 ("validate", lambda: enqueue_validation(import_id, get_schema())["job_id"]),
                 ("load", lambda: enqueue_load(import_id, get_schema())["job_id"]))
        for phase, job_id_of in steps:
            run_job(worker, job_id_of())
        outcome = "passed"
    except Exception as exc:
        outcome, error = "failed", str(exc)
    return label, phase, outcome, error, round(time.perf_counter() - started, 2)


def write_report(run_rows: list[tuple], runtime: float) -> None:
    """Write the markdown report; every failure stays listed."""
    lines = ["# Stage 2 smoke rehearsal", "", f"Runtime: {runtime:.2f}s", "", "## Sample", "",
             f"Selected LEIs: {', '.join(sorted(DEFAULT_LEIS))}; aggregate X/X rows retained.", "",
             "## Run", "", "| Edition | Last phase | Outcome | Error | Seconds |", "|---|---|---|---|---:|"]
    lines.extend(f"| {label} | {phase} | {outcome} | {error.replace('|', '/') if error else ''} | {secs} |"
                 for label, phase, outcome, error, secs in run_rows)
    lines += ["", "## Post-run", "",
              "The smoke command records active periods, bank counts, CET1 rows, and decision "
              "evidence in the TEST database; the run table above preserves every failure instead "
              "of stopping at the first one.", "", "## Where it fails", ""]
    failures = [f"- {row[0]}: {row[3]}" for row in run_rows if row[2] == "failed"]
    lines.extend(failures or ["- No pipeline failures in the sample."])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stage 2 smoke rehearsal (test database only)")
    p.add_argument("--target", choices=("test", "prod"), required=True)
    p.add_argument("--rebuild-sample", action="store_true")
    a = p.parse_args(argv)
    target, _ = select_target(a.target)
    if target != "test":
        raise SystemExit("smoke is restricted to --target test")
    from app.core.config import get_schema
    from app.core.dictionary import build_dictionary
    started = time.perf_counter()
    sample_root = build_sample(Path("eba_prepared"), "/tmp/eba_smoke", rebuild=a.rebuild_sample)
    _truncate_test_tables()
    recreate_staging_schema()
    build_dictionary(Path("eba_prepared"), get_schema())
    worker = make_import_worker()
    run_rows = [_run_edition(worker, sample_root, label) for label in EDITIONS]
    write_report(run_rows, time.perf_counter() - started)
    passed = len([r for r in run_rows if r[2] == "passed"])
    print(target_summary(target, f"smoke-{passed}/{len(run_rows)}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
