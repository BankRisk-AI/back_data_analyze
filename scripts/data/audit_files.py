#!/usr/bin/env python3
"""Inventory of the downloaded EBA transparency files, and an optional prepared copy with standard names.

Reads   <root>/<year>/<files>      (the originals are never modified)
Writes  inventory.md + inventory.json in the current folder (or --report-dir)
        <prepare>/<edition>/<standard name>  with --prepare (hard links, or copies if links are not possible)

Examples:
    python -m scripts.data.audit_files /var/projects/python/eba_analyst/eba_data
    python -m scripts.data.audit_files /var/projects/python/eba_analyst/eba_data --deep
    python -m scripts.data.audit_files /var/projects/python/eba_analyst/eba_data --prepare /var/projects/python/eba_analyst/eba_prepared

--deep also reads every CSV row (periods, number of banks); it takes a few minutes for ~2 GB.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

KINDS = ["tr_oth", "tr_cre", "tr_mrk", "tr_sov", "SDD", "TR_Metadata"]

# Name rules, checked in order on the lower-cased file name without extension.
NAME_RULES = [
    ("tr_oth", r"^tr_oth|other[ _-]*templates?|^others?$"),
    ("tr_cre", r"^tr_cre|credit[ _-]*risk"),
    ("tr_mrk", r"^tr_mrk|market[ _-]*risk"),
    ("tr_sov", r"^tr_sov|sovereign"),
    ("SDD", r"^sdd|data[ _-]*dictionary|dictionary"),
    ("TR_Metadata", r"^tr_metadata|metadata"),
]
DATA_EXT = {".csv", ".xlsx", ".xls", ".zip"}
STANDARD_EXT = {"tr_oth": ".csv", "tr_cre": ".csv", "tr_mrk": ".csv", "tr_sov": ".csv", "SDD": ".xlsx", "TR_Metadata": ".xlsx"}
DUP_SUFFIX = re.compile(r"^(?P<base>.+?)_(?P<n>[2-9])$")          # "tr_cre_2" -> second set of the edition
SOV_DATE = re.compile(r"_(?P<date>\d{6})$")                        # "tr_sov_201812"
SAMPLE = 1 << 20


def kind_of(stem: str) -> str | None:
    s = stem.lower().strip()
    for kind, rule in NAME_RULES:
        if re.search(rule, s):
            return kind
    return None


def detector_ok(name: str) -> bool:
    """Same rule as the application: the name must start with the type prefix."""
    n = name.lower()
    return n.startswith(("tr_oth", "tr_cre", "tr_mrk", "tr_sov", "sdd", "tr_metadata"))


def sniff_csv(path: Path) -> dict:
    with open(path, "rb") as f:
        raw = f.read(SAMPLE)
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text, encoding = raw.decode("utf-8-sig"), "utf-8" + ("-sig" if bom else "")
    except UnicodeDecodeError:
        text, encoding = raw.decode("cp1252", "replace"), "not utf-8 (cp1252?)"
    first = text.splitlines()[0] if text else ""
    try:
        delimiter = csv.Sniffer().sniff(first, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    header = next(csv.reader([first], delimiter=delimiter), [])
    body = text.splitlines()[1:200]
    decimal_comma = any(re.search(r"\d,\d", line) for line in body) if delimiter != "," else False
    return {"encoding": encoding, "delimiter": delimiter, "header": [h.strip() for h in header],
            "decimal": "comma?" if decimal_comma else "dot"}


def count_lines(path: Path) -> int:
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(SAMPLE * 8), b""):
            n += chunk.count(b"\n")
    return max(n - 1, 0)                                            # minus header


def deep_csv(path: Path, info: dict) -> dict:
    cols = [c.lower() for c in info["header"]]
    p_idx = cols.index("period") if "period" in cols else None
    l_idx = next((i for i, c in enumerate(cols) if c in ("lei_code", "lei")), None)
    periods, leis, rows = set(), set(), 0
    enc = "utf-8-sig" if info["encoding"].startswith("utf-8") else "cp1252"
    with open(path, newline="", encoding=enc, errors="replace") as f:
        reader = csv.reader(f, delimiter=info["delimiter"])
        next(reader, None)
        for row in reader:
            rows += 1
            if p_idx is not None and p_idx < len(row):
                periods.add(row[p_idx].strip())
            if l_idx is not None and l_idx < len(row):
                leis.add(row[l_idx].strip())
    agg = sum(1 for x in leis if re.fullmatch(r"x+", x, re.I))
    return {"rows": rows, "periods": sorted(periods), "banks": len(leis) - agg}


def read_xlsx(path: Path) -> dict:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"error": "openpyxl not installed (pip install openpyxl)"}
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        return {"error": f"cannot open: {e}"}
    sheets = []
    for ws in wb.worksheets:
        header, rows = None, 0
        for row in ws.iter_rows(values_only=True):
            if not any(v not in (None, "") for v in row):
                continue
            if header is None:
                header = [str(v).strip() for v in row if v not in (None, "")]
            else:
                rows += 1
        sheets.append({"sheet": ws.title, "header": header or [], "rows": rows})
    wb.close()
    return {"sheets": sheets}


def edition_key(year: str, stem: str) -> tuple[str, str]:
    """('2020', 'tr_cre_2') -> ('2020_2', 'tr_cre'); other names unchanged."""
    m = DUP_SUFFIX.match(stem)
    if m and not SOV_DATE.search(stem):
        return f"{year}_{m['n']}", m["base"]
    return year, stem


def standard_name(kind: str, stem: str, ext: str) -> str:
    if kind == "tr_sov":
        m = SOV_DATE.search(stem)
        if m:                                                       # keep the date of split sovereign files
            return f"tr_sov_{m['date']}.csv"
    return kind + STANDARD_EXT.get(kind, ext)


def scan(root: Path, deep: bool) -> list[dict]:
    files = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            ext = path.suffix.lower()
            if ext not in DATA_EXT:
                continue
            year = folder.name
            edition, base = edition_key(year, path.stem)
            kind = kind_of(base)
            rec = {"year": year, "edition": edition, "file": str(path.relative_to(root)), "kind": kind,
                   "size_mb": round(path.stat().st_size / 1e6, 1), "app_recognises_name": detector_ok(path.name),
                   "standard_name": standard_name(kind, base, ext) if kind else None}
            print(f"  {rec['file']}", file=sys.stderr)
            if ext == ".csv":
                info = sniff_csv(path)
                rec.update(info)
                rec.update(deep_csv(path, info) if deep else {"rows": count_lines(path)})
            elif ext in (".xlsx", ".xls"):
                rec.update(read_xlsx(path) if ext == ".xlsx" else {"error": ".xls (old Excel): open and save as .xlsx"})
            elif ext == ".zip":
                with zipfile.ZipFile(path) as z:
                    rec["zip_contents"] = z.namelist()
            files.append(rec)
    return files


def report(files: list[dict], deep: bool) -> str:
    out = ["# EBA data inventory", ""]
    by_ed = defaultdict(list)
    for f in files:
        by_ed[f["edition"]].append(f)

    out += ["## Completeness per edition", "", "| Edition | " + " | ".join(KINDS) + " | Problems |",
            "| --- | " + " | ".join("---" for _ in KINDS) + " | --- |"]
    for ed in sorted(by_ed):
        kinds = defaultdict(int)
        for f in by_ed[ed]:
            if f["kind"]:
                kinds[f["kind"]] += 1
        problems = []
        unknown = [Path(f["file"]).name for f in by_ed[ed] if not f["kind"]]
        if unknown:
            problems.append("unknown: " + ", ".join(unknown))
        rename = [Path(f["file"]).name for f in by_ed[ed] if f["kind"] and not f["app_recognises_name"]]
        if rename:
            problems.append("rename needed: " + ", ".join(rename))
        dup = [k for k, n in kinds.items() if n > 1 and k != "tr_sov"]
        if dup:
            problems.append("several files of type: " + ", ".join(dup))
        cells = [("ok" if kinds[k] == 1 else f"{kinds[k]} files") if kinds[k] else "**missing**" for k in KINDS]
        out.append(f"| {ed} | " + " | ".join(cells) + f" | {'; '.join(problems) or '-'} |")

    out += ["", "## Files", "", "| Edition | File | Type | MB | Rows | Encoding | Sep | Decimal |"
            + (" Banks | Periods |" if deep else ""), "| --- | --- | --- | --- | --- | --- | --- | --- |"
            + (" --- | --- |" if deep else "")]
    for f in sorted(files, key=lambda f: (f["edition"], f["kind"] or "~", f["file"])):
        line = (f"| {f['edition']} | {f['file']} | {f['kind'] or '?'} | {f['size_mb']} | {f.get('rows', '')} | "
                f"{f.get('encoding', '')} | {f.get('delimiter', '').replace('|', 'pipe')} | {f.get('decimal', '')} |")
        if deep:
            per = f.get("periods") or []
            line += f" {f.get('banks', '')} | {', '.join(per) if len(per) <= 8 else f'{per[0]} … {per[-1]} ({len(per)})'} |"
        out.append(line)

    out += ["", "## CSV columns per type and edition", ""]
    for kind in KINDS[:4]:
        recs = [f for f in files if f["kind"] == kind and f.get("header")]
        if not recs:
            continue
        all_cols = []
        for f in recs:
            for c in f["header"]:
                if c.lower() not in [x.lower() for x in all_cols]:
                    all_cols.append(c)
        eds = sorted({f["edition"] for f in recs})
        out += [f"### {kind}", "", "| Column | " + " | ".join(eds) + " |", "| --- | " + " | ".join("---" for _ in eds) + " |"]
        for c in all_cols:
            row = []
            for ed in eds:
                hdrs = [h.lower() for f in recs if f["edition"] == ed for h in f["header"]]
                row.append("x" if c.lower() in hdrs else "")
            out.append(f"| {c} | " + " | ".join(row) + " |")
        out.append("")

    out += ["## Excel workbooks (SDD, TR_Metadata)", ""]
    for f in sorted((f for f in files if f["kind"] in ("SDD", "TR_Metadata")), key=lambda f: (f["kind"], f["edition"])):
        out.append(f"**{f['edition']} – {f['file']}**" + (f" — {f['error']}" if f.get("error") else ""))
        for s in f.get("sheets", []):
            out.append(f"- `{s['sheet']}` ({s['rows']} rows): {', '.join(s['header'][:15])}{' …' if len(s['header']) > 15 else ''}")
        out.append("")
    return "\n".join(out)


def prepare(files: list[dict], root: Path, target: Path) -> list[str]:
    done, conflicts = [], []
    planned: dict[Path, str] = {}
    for f in files:
        if not f["kind"]:
            continue
        dest = target / f["edition"] / f["standard_name"]
        if dest in planned:
            conflicts.append(f"{f['file']} and {planned[dest]} -> {dest.relative_to(target)}")
            continue
        planned[dest] = f["file"]
    if conflicts:
        raise SystemExit("prepare stopped, two files map to the same name:\n  " + "\n  ".join(conflicts))
    for dest, src in planned.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            continue
        try:
            os.link(root / src, dest)                               # no extra disk space
        except OSError:
            shutil.copy2(root / src, dest)
        done.append(f"{src} -> {dest.relative_to(target)}")
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Inventory of downloaded EBA transparency files")
    ap.add_argument("root", help="folder with one sub-folder per edition, e.g. .../eba_data")
    ap.add_argument("--deep", action="store_true", help="read all CSV rows: periods and number of banks")
    ap.add_argument("--report-dir", default=".", help="where to write inventory.md and inventory.json")
    ap.add_argument("--prepare", metavar="DIR", help="build DIR/<edition>/<standard name> (originals untouched)")
    a = ap.parse_args(argv)

    root = Path(a.root).expanduser().resolve()
    if not root.is_dir():
        print(f"not a folder: {root}", file=sys.stderr)
        return 2
    print(f"scanning {root}", file=sys.stderr)
    files = scan(root, a.deep)
    rep = Path(a.report_dir)
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "inventory.json").write_text(json.dumps(files, indent=2, ensure_ascii=False), encoding="utf-8")
    md = report(files, a.deep)
    (rep / "inventory.md").write_text(md, encoding="utf-8")
    print(md.split("## Files")[0])
    print(f"full report: {rep.resolve() / 'inventory.md'}")

    if a.prepare:
        done = prepare(files, root, Path(a.prepare).expanduser().resolve())
        print(f"\nprepared {len(done)} file(s) in {a.prepare}")
        for d in done:
            print("  " + d)
    return 0


if __name__ == "__main__":
    sys.exit(main())