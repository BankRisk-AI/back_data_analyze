"""Generate the reproducible analysis figures F1-F12 (thesis figures).

    python -m scripts.figures.generate --target test --out docs/figures [--lang ro] [--only F1,F3]
"""
from __future__ import annotations

import argparse

from scripts.common import select_target, target_summary
from scripts.figures.figures import generate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate analysis figures")
    p.add_argument("--target", choices=("test", "prod"), required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--lang", choices=("en", "ro"), default="en")
    p.add_argument("--only", help="comma-separated figure IDs, for example F1,F3")
    a = p.parse_args(argv)
    target, _ = select_target(a.target)
    only = [i.strip().upper() for i in a.only.split(",") if i.strip()] if a.only else None
    try:
        count = generate(target, a.out, a.lang, only)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(target_summary(target, f"figures-generated count={count} out={a.out}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
