"""Small, deterministic source samples for the Stage 2 smoke rehearsal."""
from __future__ import annotations

import csv
import shutil
from pathlib import Path


DEFAULT_LEIS = {
    "0W2PZJM8XOY22M4GG883",
    "0SK1ILSPWNVBNQWU0W18",
    "529900GGYMNGRQTDOO93",
    "213800TC9PZRBHMJW403",
    "213800X3Q9LSAKRUWY91",
    "2138004FIUXU3B2MR537",
}


def _encoding(path: Path) -> str:
    raw = path.read_bytes()
    try:
        raw.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1252"


def _dialect(path: Path, encoding: str) -> csv.Dialect:
    with path.open("r", encoding=encoding, newline="") as stream:
        return csv.Sniffer().sniff(stream.read(65536))


def build_sample(source_root: str | Path, destination: str | Path,
                 leis: set[str] | None = None, rebuild: bool = False) -> Path:
    source_root, destination = Path(source_root), Path(destination)
    if destination.exists() and not rebuild:
        return destination
    if destination.exists():
        shutil.rmtree(destination)
    selected = leis or DEFAULT_LEIS
    for edition in sorted(p for p in source_root.iterdir() if p.is_dir()):
        target = destination / edition.name
        target.mkdir(parents=True)
        for source in edition.iterdir():
            if source.name.lower() in {"sdd.xlsx", "tr_metadata.xlsx"}:
                shutil.copy2(source, target / source.name)
            elif source.name.lower().startswith("tr_") and source.suffix.lower() == ".csv":
                encoding = _encoding(source)
                dialect = _dialect(source, encoding)
                with source.open("r", encoding=encoding, newline="") as input_stream:
                    reader = csv.reader(input_stream, dialect)
                    header = next(reader)
                    normalized = [str(value).strip().lower().replace(" ", "_") for value in header]
                    lei_index = normalized.index("lei_code")
                    with (target / source.name).open("w", encoding=encoding, newline="") as output_stream:
                        writer = csv.writer(output_stream, dialect)
                        writer.writerow(header)
                        for row in reader:
                            lei = row[lei_index].strip() if lei_index < len(row) else ""
                            if lei in selected or (lei and set(lei.lower()) == {"x"}):
                                writer.writerow(row)
    return destination
