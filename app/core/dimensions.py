"""Build versioned dimension-code dictionaries from EBA metadata workbooks."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_NON_DIMENSION_SHEETS = {
    "bank list", "banks list", "list of institutions",
    "list of financial institutions", "other banks", "dimensions used",
}


def _sheet_names(path: str) -> list[str]:
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def _rows(path: str, sheet: str) -> list[list[str]]:
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet]
        return [[
            "" if value is None else str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
            for value in row
        ] for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _normalised_key(sheet: str, label: str, extra: str = "") -> str | None:
    if sheet.casefold() == "country":
        return extra.upper() if extra else None
    if sheet.casefold() in {"nace_codes", "nace code"}:
        match = re.match(r"\s*([A-Z])(?:\s|$)", label.upper())
        return match.group(1) if match else None
    return None


def _dimension_rows(path: str, sheet: str) -> dict[str, dict[str, str | None]]:
    rows = _rows(path, sheet)
    header_index = next(
        (i for i, row in enumerate(rows)
         if len([v for v in row if str(v).strip()]) >= 2),
        None,
    )
    if header_index is None:
        return {}
    headers = [str(value).strip().casefold() for value in rows[header_index]]
    label_index = next(
        (i for i, value in enumerate(headers) if value in {"label", "description", "desc"}),
        1,
    )
    code_index = next(
        (i for i, value in enumerate(headers)
         if value and i != label_index and value not in {"iso_code", "iso code"}),
        0,
    )
    iso_index = next((i for i, value in enumerate(headers) if value in {"iso_code", "iso code"}), None)
    result: dict[str, dict[str, str | None]] = {}
    for row in rows[header_index + 1:]:
        values = list(row) + [""] * max(0, len(headers) - len(row))
        code = str(values[code_index]).strip()
        label = str(values[label_index]).strip()
        if not code or not label or code.casefold() in {"code", "nan"}:
            continue
        iso = str(values[iso_index]).strip() if iso_index is not None else ""
        result[code] = {
            "label": label,
            "normalised_key": _normalised_key(sheet, label, iso),
        }
    return result


def build_dimensions(source_root: str | Path, output_root: str | Path = "config/dimensions") -> list[Path]:
    """Build one deterministic YAML file per edition under ``output_root``."""
    source = Path(source_root)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    editions = sorted(path.name for path in source.iterdir() if path.is_dir())
    written: list[Path] = []
    for edition in editions:
        workbook = source / edition / "TR_Metadata.xlsx"
        data: dict[str, object] = {
            "edition": edition,
            "source": str(workbook),
            "status": "decoded" if workbook.is_file() else "undecoded",
            "dimensions": {},
        }
        destination = output / f"{edition}.yaml"
        existing = yaml.safe_load(destination.read_text(encoding="utf-8")) if destination.exists() else {}
        if isinstance(existing, dict) and existing.get("proofs"):
            data["proofs"] = existing["proofs"]
        if not workbook.is_file() and isinstance(existing, dict) and existing.get("dimensions"):
            data["dimensions"] = existing["dimensions"]
            data["status"] = "partial"
        if workbook.is_file():
            dimensions = {}
            for sheet in _sheet_names(str(workbook)):
                if sheet.casefold() in _NON_DIMENSION_SHEETS:
                    continue
                entries = _dimension_rows(str(workbook), sheet)
                if entries:
                    dimensions[sheet] = entries
            data["dimensions"] = dimensions
        destination.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        written.append(destination)
    return written
