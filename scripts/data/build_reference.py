"""Build derived reference data: item dictionary, dimension codes, panel, rule profile results.

    python -m scripts.data.build_reference dictionary --target test [DIR]
    python -m scripts.data.build_reference dimensions [DIR] [--out config/dimensions]
    python -m scripts.data.build_reference panel --target test
    python -m scripts.data.build_reference rules --profile eu_eba --target test
"""
from __future__ import annotations

import argparse
from pathlib import Path

from scripts.common import init_all_modules, select_target, target_summary


def build_dictionary_cmd(a: argparse.Namespace) -> int:
    from app.core.config import get_schema
    from app.core.dictionary import build_dictionary
    target, _ = select_target(a.target)
    build_dictionary(a.directory, get_schema())
    print(target_summary(target, "dictionary-built"))
    return 0


def build_dimensions_cmd(a: argparse.Namespace) -> int:
    from app.core.dimensions import build_dimensions
    paths = build_dimensions(a.directory, a.out)
    print(f"dimensions-built editions={len(paths)} output={a.out}")
    return 0


def build_panel_cmd(a: argparse.Namespace) -> int:
    from app.core.config import get_schema
    from app.core.database import connect
    from app.core.dimensions import build_dimensions
    from app.core.panel import build_panel
    from app.core.hooks import register_module_hooks
    from app.modules import MODULES
    target, _ = select_target(a.target)
    init_all_modules()
    register_module_hooks(MODULES)
    build_dimensions("eba_prepared", "config/dimensions")
    conn = connect(get_schema())
    try:
        count = build_panel(conn)
    finally:
        conn.close()
    print(target_summary(target, f"panel-built rows={count}"))
    return 0


def evaluate_rules_cmd(a: argparse.Namespace) -> int:
    from app.core.config import get_schema
    from app.core.database import connect
    from app.modules.eba_rules.public import evaluate_panel, load_profile
    target, _ = select_target(a.target)
    init_all_modules()
    try:
        load_profile(a.profile)
    except KeyError as exc:
        raise SystemExit(str(exc)) from exc
    conn = connect(get_schema())
    try:
        count = len(evaluate_panel(conn, a.profile))
    finally:
        conn.close()
    print(target_summary(target, f"rules-evaluated profile={a.profile} rows={count}"))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build derived reference data")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dictionary", help="cross-edition item dictionary")
    d.add_argument("directory", nargs="?", default="eba_prepared")
    d.add_argument("--target", choices=("test", "prod"), required=True)
    d.set_defaults(func=build_dictionary_cmd)
    m = sub.add_parser("dimensions", help="dimension-code dictionaries")
    m.add_argument("directory", nargs="?", default="eba_prepared")
    m.add_argument("--out", default="config/dimensions")
    m.set_defaults(func=build_dimensions_cmd)
    pa = sub.add_parser("panel", help="derived panel data")
    pa.add_argument("--target", choices=("test", "prod"), required=True)
    pa.set_defaults(func=build_panel_cmd)
    r = sub.add_parser("rules", help="evaluate a version-controlled rule profile")
    r.add_argument("--profile", required=True)
    r.add_argument("--target", choices=("test", "prod"), required=True)
    r.set_defaults(func=evaluate_rules_cmd)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
