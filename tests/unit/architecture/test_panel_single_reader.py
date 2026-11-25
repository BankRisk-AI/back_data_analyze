"""panel_row has one writer (core/panel.py) and one reader (core/panel_reader.py:load_panel)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SQL_USE = re.compile(r"\b(FROM|JOIN|INTO|UPDATE|TRUNCATE)\s+panel_row\b", re.I)
ALLOWED = {"app/core/panel.py", "app/core/panel_reader.py"}


def test_no_code_outside_core_queries_panel_row():
    offenders = []
    for folder in ("app", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            relative = str(path.relative_to(ROOT))
            if relative not in ALLOWED and SQL_USE.search(path.read_text(encoding="utf-8")):
                offenders.append(relative)
    assert not offenders, offenders


def test_core_panel_knows_no_module_specific_table_or_job():
    text = (ROOT / "app/core/panel.py").read_text(encoding="utf-8")
    for forbidden in ("ml_model", "score_panel", "eba_ml", "eba_rules", "alert"):
        assert forbidden not in text, forbidden
