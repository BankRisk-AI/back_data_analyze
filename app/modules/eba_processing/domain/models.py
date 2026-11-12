"""Results of the processing module as plain dataclasses (the API turns them into JSON)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Filters:
    period: str | None = None
    lei: str | None = None
    item: str | None = None
    dims: dict[str, str] = field(default_factory=dict)
    exclude_aggregate: bool = False


@dataclass
class ValidationIssue:
    rule: str
    title: str
    severity: str                       # error, warning, info
    passed: bool
    affected_rows: int = 0
    detail: str = ""
    examples: list[dict] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class FileValidation:
    file_id: int
    file_name: str
    file_type: str
    rows: int
    issues: list[ValidationIssue] = field(default_factory=list)

    def count(self, severity: str) -> int:
        return sum(1 for i in self.issues if not i.passed and i.severity == severity)


@dataclass
class ValidationReport:
    import_id: int
    files: list[FileValidation] = field(default_factory=list)
    generated_at: str = ""
    seconds: float = 0.0

    @property
    def errors(self) -> int:
        return sum(f.count("error") for f in self.files)

    @property
    def warnings(self) -> int:
        return sum(f.count("warning") for f in self.files)

    @property
    def infos(self) -> int:
        return sum(f.count("info") for f in self.files)

    @property
    def can_proceed(self) -> bool:
        return self.errors == 0 and bool(self.files)
