import argparse
import json
import sys
from app.core.config import get_max_upload_bytes, get_schema, get_storage_dir

from app.modules.eba_ingest.application.ingest_service import (
    drop_staging,
    ingest,
    init_db,
    show,
)
from app.modules.eba_ingest.domain import IngestError


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m scripts.data.ingest_cli",
        description="Module 1 of the EBA Data Explorer: loading of the original files",
    )

    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create the database tables and staging schema")

    load = sub.add_parser("load", help="store and stage original files")
    load.add_argument("files", nargs="+")
    load.add_argument("--storage", default=get_storage_dir())
    load.add_argument("--user", type=int)
    load.add_argument("--edition")
    load.add_argument("--json", action="store_true")
    load.add_argument("--max-mb", type=float, default=get_max_upload_bytes() / 1024 / 1024)

    show_parser = sub.add_parser("show", help="show an import report")
    show_parser.add_argument("import_id", type=int)

    serve = sub.add_parser("serve", help="start the HTTP API")
    serve.add_argument("--storage", default=get_storage_dir())
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--ui-dir")
    serve.add_argument("--max-mb", type=float, default=get_max_upload_bytes() / 1024 / 1024)
    serve.add_argument("--user", type=int)

    drop = sub.add_parser("drop-staging", help="drop staging tables")
    drop.add_argument("import_id", type=int)

    args = ap.parse_args(argv)

    if args.cmd == "init-db":
        init_db(get_schema())
        print("schema created")
        return 0

    if args.cmd == "serve":
        import uvicorn
        from app.modules.eba_ingest.presentation.api.api import create_app

        uvicorn.run(
            create_app(
                storage_dir=args.storage,
                schema=get_schema(),
                max_bytes=int(args.max_mb * 1024 * 1024),
                user_id=args.user,
                ui_dir=args.ui_dir,
            ),
            host=args.host,
            port=args.port,
        )
        return 0

    if args.cmd == "show":
        print(json.dumps(show(args.import_id, get_schema()), indent=2))
        return 0

    if args.cmd == "drop-staging":
        count = drop_staging(args.import_id, get_schema())
        print(f"dropped {count} staging tables")
        return 0

    try:
        report = ingest(
            args.files,
            args.storage,
            args.user,
            args.edition,
            int(args.max_mb * 1024 * 1024),
            get_schema(),
            progress=lambda message: print("  " + message, file=sys.stderr),
        )
    except IngestError as exc:
        print(f"REFUSED ({exc.kind}): {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print(f"import {report.import_id}: {report.status} in {report.seconds} s")

    for file in report.files:
        status = "" if file.recognised else f" (NOT recognised: {file.reason})"
        print(
            f"  {file.name}: {file.file_type}{status}, "
            f"{file.size_bytes / 1e6:.1f} MB, {file.encoding}"
        )

        if file.rows is not None:
            print(
                f"    {file.rows:,} rows "
                f"({file.aggregate_rows:,} aggregate) -> {file.staging_table}"
            )

        for pair in file.pairs:
            print(
                f"      {pair.year} Q{pair.quarter}: "
                f"{pair.banks} banks, {pair.rows:,} rows"
            )

        for warning in file.warnings:
            print(f"      warning: {warning}")

    return 0 if report.status != "rejected" else 3


if __name__ == "__main__":
    sys.exit(main())
