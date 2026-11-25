"""eba_rules is an independent module: others use only its public.py; it knows no other module."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "app"
ROOTS = (APP, Path(__file__).resolve().parents[3] / "scripts")


def _imports(path: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_nothing_outside_eba_rules_imports_its_internals():
    inside = APP / "modules" / "eba_rules"
    allowed = {"app.modules.eba_rules.public", "app.modules.eba_rules.module"}  # module.py: registry only
    offenders = []
    for root in ROOTS:
        for p in root.rglob("*.py"):
            if inside in p.parents or "__pycache__" in p.parts:
                continue
            offenders += [f"{p} imports {n}" for n in _imports(p)
                          if n.startswith("app.modules.eba_rules") and n not in allowed]
    assert not offenders, offenders


def test_eba_rules_imports_no_other_module_and_no_scripts():
    offenders = []
    for p in (APP / "modules" / "eba_rules").rglob("*.py"):
        for n in _imports(p):
            other = n.startswith("app.modules.") and n.split(".")[2] != "eba_rules"
            if other or n == "scripts" or n.startswith("scripts."):
                offenders.append(f"{p.name} imports {n}")
    assert not offenders, offenders
