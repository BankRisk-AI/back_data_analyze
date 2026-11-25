"""Specialist institutions (config/specialist_institutions.yaml): the single place that reads the list."""
from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_ROOT = Path("config")


def specialist_leis(root: Path = DEFAULT_ROOT) -> set[str]:
    """LEIs of the specialist institutions (empty set when the file does not exist)."""
    path = Path(root) / "specialist_institutions.yaml"
    if not path.exists():
        return set()
    return {str(item["lei"]).strip() for item in yaml.safe_load(path.read_text(encoding="utf-8")) or []}
