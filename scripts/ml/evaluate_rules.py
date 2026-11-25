"""Evaluate a rule profile against an event catalogue (primary and all events).

    python -m scripts.ml.evaluate_rules --profile eu_eba --events <catalogue> --target test

Writes docs/design/rule_evaluation.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from scripts.common import select_target, target_summary
from scripts.ml.event_evaluation import evaluate_events, write_report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Evaluate rules against an event catalogue")
    p.add_argument("--profile", required=True)
    p.add_argument("--events", required=True)
    p.add_argument("--target", choices=("test", "prod"), required=True)
    a = p.parse_args(argv)
    target, _ = select_target(a.target)
    from app.core.config import get_schema
    from app.core.database import connect
    profile_path = Path("config/rules") / f"{a.profile}.yaml"
    conn = connect(get_schema())
    try:
        results = [evaluate_events(conn, profile_path, a.events, scope)
                   for scope in ("primary", "all")]
    finally:
        conn.close()
    write_report(results, "docs/design/rule_evaluation.md")
    print(target_summary(target, f"rules-evaluated-events profile={a.profile} "
                                 f"primary={results[0]['evaluable_events']} "
                                 f"all={results[1]['evaluable_events']}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
