"""Request and response models of the ingest API (they define the OpenAPI schemas)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PairModel(BaseModel):
    """A (year, quarter) found in the Period column of a data file."""

    year: int = Field(examples=[2020])
    quarter: int = Field(ge=1, le=4, examples=[2])
    banks: int = Field(description="Distinct banks (aggregate bucket excluded)", examples=[135])
    rows: int = Field(description="Rows (aggregate bucket excluded)", examples=[210083])


class FileModel(BaseModel):
    name: str = Field(examples=["tr_cre_2.csv"])
    size_bytes: int
    sha256: str
    file_type: str = Field(description="tr_oth, tr_cre, tr_mrk, tr_sov, SDD, TR_Metadata or unrecognised", examples=["tr_cre"])
    recognised: bool | None = Field(default=None, description="null until the worker has inspected the file; then true when name and content match a known EBA file")
    encoding: str = Field(description="utf-8, cp1252 or xlsx", examples=["cp1252"])
    rows: int | None = Field(default=None, description="Rows loaded into the staging table (aggregate bucket included)")
    aggregate_rows: int | None = Field(default=None, description="Rows of the bucket 'All other banks' (LEI of X characters or country OT)")
    columns: list[str] | None = Field(default=None, description="Normalised column names of a data file")
    reason: str | None = Field(default=None, description="Why the file was not recognised")
    staging_table: str | None = Field(default=None, examples=["staging.f6"])
    file_id: int | None = None
    seconds: float = 0.0
    pairs: list[PairModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImportDetail(BaseModel):
    import_id: int
    status: str = Field(description="uploaded, validated, approved, loading, loaded, rejected, cancelled or failed", examples=["uploaded"])
    files: list[FileModel]
    seconds: float = 0.0
    error: str | None = None
    edition_label: str | None = None
    created_at: str | None = None
    created_by: str | None = None
    has_staging: bool = Field(default=False, description="True while the staging tables of the import exist")
    job_id: int | None = None
    job_status: str | None = Field(default=None, description="State of the loading job: pending, processing, completed or failed")
    progress: int = Field(default=0, ge=0, le=100)
    progress_message: str | None = None


class ImportSummary(BaseModel):
    import_id: int
    status: str
    edition_label: str | None
    created_at: str
    created_by: str | None
    files: int
    file_names: list[str]
    error: str | None
    has_staging: bool
    job_status: str | None = None
    progress: int = 0
    progress_message: str | None = None


class IngestConfig(BaseModel):
    max_upload_mb: float = Field(description="Largest accepted file, in MB", examples=[170.0])
    accepted_extensions: list[str] = Field(examples=[[".csv", ".xlsx"]])
    authentication: bool = Field(default=False, description="False until the application has users")


class DroppedStaging(BaseModel):
    dropped: int = Field(description="Number of staging tables dropped")


class LoadQueued(BaseModel):
    job_id: int
    status: str
    created: bool
