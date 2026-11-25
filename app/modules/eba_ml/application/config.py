"""Single loader for config/ml.yaml (shared by the app and the thesis scripts)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ML_CONFIG_PATH = Path("config/ml.yaml")


def load_ml_config() -> dict[str, Any]:
    """Return the parsed contents of config/ml.yaml."""
    return yaml.safe_load(ML_CONFIG_PATH.read_text())
