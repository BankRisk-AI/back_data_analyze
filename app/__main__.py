"""Server startup:  python -m app serve [--host H] [--port P] [--reload]  |  python -m app worker.

Every other terminal command (init-db, import, panel, thesis runs, hypotheses) lives in scripts/.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app", description="EBA Analyst")
    sub = ap.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="start the HTTP API with every module")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    sub.add_parser("worker", help="start the job worker (loads staging tables, runs validations)")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("app.main:app_from_env", factory=True, host=a.host, port=a.port, reload=a.reload)
    else:
        from app.worker import main as worker_main
        worker_main([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
