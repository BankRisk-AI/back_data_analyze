"""Load prepared EBA editions through the normal pipeline: stage -> validate -> load.

    python -m scripts.data.import_data edition eba_prepared/2024 --edition 2024 --target test
    python -m scripts.data.import_data all eba_prepared --target prod
"""
from __future__ import annotations

import argparse
from pathlib import Path

from scripts.common import (EDITIONS, edition_files, make_import_worker, run_job, select_target,
                            stage_job_id, target_summary)


def import_edition(worker, directory: Path, label: str) -> None:
    """Stage, validate and load one edition; SystemExit names the failing phase."""
    from app.core.config import get_schema, get_storage_dir, get_user_id
    from app.modules.eba_ingest.application.load_service import enqueue_load
    from app.modules.eba_ingest.application.upload_service import enqueue_import
    from app.modules.eba_processing.application.validation import enqueue_validation
    import_id = enqueue_import(edition_files(directory), get_storage_dir(), user_id=get_user_id(),
                               edition_label=label, schema=get_schema())
    phases = (("stage", lambda: stage_job_id(import_id)),
              ("validation", lambda: enqueue_validation(import_id, get_schema())["job_id"]),
              ("load", lambda: enqueue_load(import_id, get_schema())["job_id"]))
    for phase, job_id_of in phases:
        try:
            run_job(worker, job_id_of())
        except RuntimeError as exc:
            raise SystemExit(f"{label}: {phase} failed: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import prepared EBA editions")
    sub = p.add_subparsers(dest="mode", required=True)
    one = sub.add_parser("edition", help="load one prepared edition")
    one.add_argument("directory")
    one.add_argument("--edition", required=True)
    every = sub.add_parser("all", help="load all prepared editions, oldest first")
    every.add_argument("directory", nargs="?", default="eba_prepared")
    for sp in (one, every):
        sp.add_argument("--target", choices=("test", "prod"), required=True)
    a = p.parse_args(argv)
    target, _ = select_target(a.target)
    worker = make_import_worker()
    if a.mode == "edition":
        import_edition(worker, Path(a.directory), a.edition)
    else:
        for label in EDITIONS:
            import_edition(worker, Path(a.directory) / label, label)
    print(target_summary(target, "imports-loaded"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
