"""Row readers (streaming) for the original files: csv in utf-8 or cp1252, xlsx read as VALUES only (no formulas)."""
import csv
from app.modules.eba_ingest.domain import UnreadableFile

def csv_rows(path: str, encoding: str):
    enc = "utf-8-sig" if encoding == "utf-8" else encoding
    csv.field_size_limit(1 << 24)
    with open(path, newline="", encoding=enc) as f:
        yield from csv.reader(f)

def _cell(v):
    if v is None: return ""
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15: return str(int(v))   # 202003.0 -> 202003
    return str(v)

def xlsx_rows(path: str, sheet: str | None = None):
    from openpyxl import load_workbook
    try: wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e: raise UnreadableFile(f"cannot open the workbook: {e}") from e
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        for row in ws.iter_rows(values_only=True): yield [_cell(v) for v in row]
    finally: wb.close()

def xlsx_sheet_names(path: str):
    from openpyxl import load_workbook
    try: wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e: raise UnreadableFile(f"cannot open the workbook: {e}") from e
    try: return list(wb.sheetnames)
    finally: wb.close()

def xlsx_header(path: str):
    for row in xlsx_rows(path): return row
    return []
