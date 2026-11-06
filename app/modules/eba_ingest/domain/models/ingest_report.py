from dataclasses import asdict, dataclass

from app.modules.eba_ingest.domain.constants import DATA_TYPES

from .file_report import FileReport


@dataclass
class IngestReport:
    import_id: int
    status: str
    files: list[FileReport]

    seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def data_files(self) -> list[FileReport]:
        return [f for f in self.files if f.recognised and f.file_type in DATA_TYPES]
