
"""Recognition and validation of EBA data file headers."""

import re

from app.modules.eba_ingest.domain.constants import DATA_TYPES


REQUIRED_COLUMNS = (
    "lei_code",
    "nsa",
    "period",
    "item",
    "amount",
)


def classify_name(filename: str) -> str | None:
    """Guess the EBA file type from its name."""

    name = filename.lower()

    for file_type in DATA_TYPES:
        if name.startswith(file_type):
            return file_type

    if name.startswith("sdd"):
        return "SDD"

    if name.startswith("tr_metadata"):
        return "TR_Metadata"

    return None


def normalise_header(columns: list) -> list[str]:
    """Normalize column names and reject duplicates."""

    normalized = [
        re.sub(r"\s+", "_", str(column).strip().lower())
        for column in columns
    ]

    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate column names in the header")

    return normalized


def missing_required(columns: list[str]) -> list[str]:
    """Return required columns that are missing."""

    return [
        column
        for column in REQUIRED_COLUMNS
        if column not in columns
    ]
