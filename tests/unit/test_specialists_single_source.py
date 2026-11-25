"""The specialist list and the read session each have exactly one definition (app/core)."""
import re
from pathlib import Path

from app.core.specialists import specialist_leis

APP = Path(__file__).resolve().parents[2] / "app"


def test_specialist_list_is_read_in_one_place_only():
    readers = [str(p.relative_to(APP)) for p in APP.rglob("*.py")
               if "specialist_institutions.yaml" in p.read_text(encoding="utf-8")]
    assert readers == ["core/specialists.py"]


def test_read_session_is_defined_once_for_analysis_and_rules():
    defs = [str(p.relative_to(APP)) for p in APP.rglob("*.py")
            if re.search(r"^def read_session\(schema", p.read_text(encoding="utf-8"), re.M)]
    assert sorted(defs) == ["core/read_session.py", "modules/eba_processing/application/session.py"]


def test_specialist_leis_reads_the_given_root(tmp_path):
    assert specialist_leis(tmp_path) == set()
    (tmp_path / "specialist_institutions.yaml").write_text("- lei: ' ABC '\n  name: x\n")
    assert specialist_leis(tmp_path) == {"ABC"}
    assert len(specialist_leis()) > 0
