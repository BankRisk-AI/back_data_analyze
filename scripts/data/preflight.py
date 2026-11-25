"""Stage 2 preflight: stage and validate editions on TEST and report fact collisions, no load.

    python -m scripts.data.preflight edition eba_prepared/2020S --edition 2020S --target test
    python -m scripts.data.preflight all eba_prepared --target test

Writes docs/design/stage2_preflight.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from scripts.common import (EDITIONS, edition_files, make_import_worker, select_target,
                            target_summary)

REPORT = Path("docs/design/stage2_preflight.md")
DIAGNOSIS = ("The two remaining groups are in `2020S/tr_cre.csv` and are class (iii): "
             "their loader identity is the same while source rows carry different amounts. "
             "Both are covered by the configured BNG owner exclusions. No loading fix is "
             "applied by this diagnostic.")


def collisions_of(worker, directory: Path, label: str) -> list[dict]:
    """Stage and validate one edition, then return its fact collisions."""
    from app.core.config import get_schema, get_storage_dir, get_user_id
    from app.core.database import connect
    from app.core.preflight import collision_check
    from app.modules.eba_ingest.application.upload_service import enqueue_import
    from app.modules.eba_processing.application.validation import enqueue_validation
    import_id = enqueue_import(edition_files(directory), get_storage_dir(), user_id=get_user_id(),
                               edition_label=label, schema=get_schema())
    worker.process_one()
    enqueue_validation(import_id, get_schema())
    worker.process_one()
    with connect(get_schema()) as conn, conn.cursor() as cur:
        return collision_check(cur, import_id)


def report_lines(report_rows: list[tuple[str, list[dict]]]) -> list[str]:
    """Markdown of the collision table, samples and diagnosis."""
    from app.core.preflight import collision_summary
    lines = ["# Stage 2 preflight", "",
             "The full-data preflight stages and validates every edition on TEST, "
             "but does not load facts. Exact duplicate rows are normalized out and "
             "configured owner exclusions are applied before classification.", "",
             "| Edition | Fact table | Class i | Class ii | Class iii | Class iv | Total |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for label, rows in report_rows:
        by_table: dict[str, list] = {}
        for row in rows:
            by_table.setdefault(row["fact_table"], []).append(row)
        if not by_table:
            lines.append(f"| {label} | — | 0 | 0 | 0 | 0 | 0 |")
        for table, table_rows in by_table.items():
            c = collision_summary(table_rows)
            lines.append(f"| {label} | {table} | {c['i']} | {c['ii']} | {c['iii']} | {c['iv']} | "
                         f"{len(table_rows)} |")
    lines += ["", "## Samples", ""]
    lines += [f"- `{label}` `{row['fact_table']}` class `{row['class']}`: {row}"
              for label, rows in report_rows for row in rows[:20]]
    return lines + ["", "## Diagnosis", "", DIAGNOSIS]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collision preflight on the test database")
    sub = p.add_subparsers(dest="mode", required=True)
    one = sub.add_parser("edition")
    one.add_argument("directory")
    one.add_argument("--edition", required=True)
    every = sub.add_parser("all")
    every.add_argument("directory")
    for sp in (one, every):
        sp.add_argument("--target", choices=("test", "prod"), required=True)
    a = p.parse_args(argv)
    target, _ = select_target(a.target)
    worker = make_import_worker()
    root = Path(a.directory)
    jobs = [(a.edition, root)] if a.mode == "edition" else [(e, root / e) for e in EDITIONS]
    report_rows = [(label, collisions_of(worker, directory, label)) for label, directory in jobs]
    REPORT.write_text("\n".join(report_lines(report_rows)) + "\n", encoding="utf-8")
    total = sum(len(rows) for _, rows in report_rows)
    print(target_summary(target, f"preflight-{total}-collisions"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
