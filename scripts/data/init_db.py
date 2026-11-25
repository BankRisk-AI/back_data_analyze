"""Create or upgrade the database tables (migrations of the core and every module).

    python -m scripts.data.init_db --target test
"""
from __future__ import annotations

import argparse

from scripts.common import init_all_modules, select_target, target_summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Create or upgrade the database tables")
    p.add_argument("--target", choices=("test", "prod"), required=True)
    a = p.parse_args(argv)
    target, _ = select_target(a.target)
    init_all_modules()
    print(target_summary(target, "database-ready"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
