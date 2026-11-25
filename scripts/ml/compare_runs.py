"""Golden check: are two runs identical, ignoring timestamps and paths? (thesis reproducibility)

    python -m scripts.ml.compare_runs data/ml/T3_primary data/ml/R1_golden

Compares results_*.json and hypotheses.json of two run directories key by key. Exit code 1 on
any difference. Replaces the former check_primary_reproducibility script.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

IGNORED_KEYS = {"run", "created_at", "timestamp", "elapsed_seconds", "path", "run_dir"}


def differences(a: Any, b: Any, where: str = "") -> list[str]:
    """Paths at which a and b differ (IGNORED_KEYS skipped; floats compared exactly)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted((set(a) | set(b)) - IGNORED_KEYS):
            if key not in a or key not in b:
                out.append(f"{where}/{key}: present in only one run")
            else:
                out += differences(a[key], b[key], f"{where}/{key}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{where}: length {len(a)} != {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{where}[{i}]")]
    return [] if a == b else [f"{where}: {a!r} != {b!r}"]


def compare_files(run_a: Path, run_b: Path, pattern: str) -> list[str]:
    """Differences between the first file matching pattern in each directory."""
    file_a, file_b = next(run_a.glob(pattern), None), next(run_b.glob(pattern), None)
    if file_a is None or file_b is None:
        return [f"{pattern}: missing in {'A' if file_a is None else 'B'}"]
    return differences(json.loads(file_a.read_text()), json.loads(file_b.read_text()), pattern)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("usage: python -m scripts.ml.compare_runs RUN_A RUN_B", file=sys.stderr)
        return 2
    run_a, run_b = Path(args[0]), Path(args[1])
    problems = [d for pattern in ("results_*.json", "hypotheses.json")
                for d in compare_files(run_a, run_b, pattern)]
    for line in problems[:50]:
        print("DIFF", line)
    print("IDENTICAL" if not problems else f"DIFFERENT: {len(problems)} differences")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
