"""The processing module on its own:  python -m app.modules.eba_processing <serve|validate|config>"""
from __future__ import annotations

import argparse
import json
import sys

from app.core.config import get_schema


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.modules.eba_processing", description="Preview, profile, charts and validation of staged EBA data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="start the HTTP API of this module alone")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8001)
    val = sub.add_parser("validate", help="run the validation of an import now, without the worker, and print the result")
    val.add_argument("import_id", type=int)
    val.add_argument("--json", action="store_true", help="print the whole report")
    sub.add_parser("config", help="print limits, enumerations and the rule catalogue")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        from app.modules.eba_processing.presentation.api.api import create_app
        uvicorn.run(create_app(get_schema()), host=a.host, port=a.port)
        return 0
    if a.cmd == "config":
        from app.modules.eba_processing.presentation.api.router import build_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI(); app.include_router(build_router(get_schema()))
        print(json.dumps(TestClient(app).get("/api/processing/config").json(), indent=2))
        return 0
    from app.core.exceptions import AppError
    from app.modules.eba_processing.application.validation import report_to_dict, run_validation
    try:
        report = report_to_dict(run_validation(a.import_id, get_schema(), emit=lambda message, percent: print(f"  {percent:3d}%  {message}", file=sys.stderr)))
    except AppError as e:
        print(f"REFUSED ({e.kind}): {e.detail}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(report, indent=2))
        return 0 if report["summary"]["can_proceed"] else 3
    s = report["summary"]
    print(f"import {a.import_id}: {s['errors']} errors, {s['warnings']} warnings, {s['infos']} notes in {report['seconds']} s -> {'can proceed' if s['can_proceed'] else 'cannot proceed'}")
    for f in report["files"]:
        print(f"  {f['file_name']} ({f['rows']:,} rows)")
        for i in f["issues"]:
            if i["status"] == "failed":
                print(f"    {i['rule']} {i['severity']:7} {i['affected_rows']:>9,}  {i['detail']}")
    return 0 if s["can_proceed"] else 3


if __name__ == "__main__":
    sys.exit(main())
