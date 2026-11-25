"""Dependency direction: scripts may import app; app must never import scripts."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _imported_modules(path: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_app_never_imports_scripts():
    offenders = [f"{p.relative_to(ROOT)} imports {name}"
                 for p in (ROOT / "app").rglob("*.py")
                 for name in _imported_modules(p)
                 if name == "scripts" or name.startswith("scripts.")]
    assert not offenders, offenders


def test_app_has_no_cli_entry_points_besides_server_and_worker():
    allowed = {"app/__main__.py", "app/worker.py"}
    offenders = [str(p.relative_to(ROOT)) for p in (ROOT / "app").rglob("*.py")
                 if "argparse" in _imported_modules(p) and str(p.relative_to(ROOT)) not in allowed]
    assert not offenders, offenders
