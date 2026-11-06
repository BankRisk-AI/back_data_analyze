"""Command line of the application:  python -m app <serve|worker|init-db|openapi>"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app", description="EBA Analyst")
    sub = ap.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="start the HTTP API with every module")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    sub.add_parser("worker", help="start the job worker (loads staging tables, runs validations)")
    sub.add_parser("init-db", help="create or upgrade the database tables (migrations)")
    spec = sub.add_parser("openapi", help="write the OpenAPI description of the whole application")
    spec.add_argument("--out", help="file to write (.yaml or .json); default: standard output")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("app.main:app_from_env", factory=True, host=a.host, port=a.port, reload=a.reload)
        return 0
    if a.cmd == "worker":
        from app.worker import main as worker_main
        worker_main([])
        return 0
    if a.cmd == "init-db":
        from app.core.config import get_schema
        from app.core.database import init_database
        from app.modules import MODULES
        applied = init_database(get_schema(), {m.name: m.migrations_dir for m in MODULES if m.migrations_dir})
        print("database ready" + (f"; applied: {', '.join(applied)}" if applied else "; already up to date"))
        return 0
    from app.main import create_app
    doc = create_app(schema="public").openapi()
    if a.out and a.out.endswith((".yaml", ".yml")):
        import yaml
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    elif a.out:
        Path(a.out).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    else:
        print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
