
from dataclasses import dataclass, field


@dataclass
class PairReport:
    year: int
    quarter: int
    banks: int
    rows: int


@dataclass
class FileReport:
    name: str
    size_bytes: int
    sha256: str
    file_type: str
    recognised: bool
    encoding: str

    rows: int | None = None
    aggregate_rows: int | None = None
    columns: list[str] | None = None

    reason: str | None = None
    staging_table: str | None = None
    file_id: int | None = None
    seconds: float = 0.0

    pairs: list[PairReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
