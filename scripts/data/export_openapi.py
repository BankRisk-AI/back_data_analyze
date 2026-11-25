"""Write the OpenAPI description of the whole application (docs/openapi.yaml).

    python -m scripts.data.export_openapi --out docs/openapi.yaml
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export the OpenAPI document")
    p.add_argument("--out", help="file to write (.yaml or .json); default: standard output")
    a = p.parse_args(argv)
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
    raise SystemExit(main())
