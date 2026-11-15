from typing import Any
from pydantic import BaseModel


class PublicPeriod(BaseModel):
    version_id: int
    year: int
    quarter: int
    period_end: str
    import_id: int
    rows_oth: int
    rows_cre: int
    rows_mrk: int
    rows_sov: int


class Preview(BaseModel):
    version_id: int
    dataset: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    pages: int


class Profile(BaseModel):
    version_id: int
    dataset: str
    rows: int
    columns: list[dict[str, Any]]
    amount: dict[str, Any]


class Histogram(BaseModel):
    version_id: int
    dataset: str
    item: str
    period: str
    rows: int
    bins: list[dict[str, Any]]
    stats: dict[str, Any]


class Aggregate(BaseModel):
    version_id: int
    dataset: str
    item: str
    period: str
    function: str
    value: float | int | None


class Scatter(BaseModel):
    version_id: int
    dataset: str
    item_x: str
    item_y: str
    period: str
    points: list[dict[str, Any]]


class ReportType(BaseModel):
    name: str
    label: str
    datasets: list[str]


class ReportYear(BaseModel):
    year: int


class ReportQuarter(BaseModel):
    period: str
    quarter: str
    reporting_date: str


class BankSummary(BaseModel):
    bank_id: int
    lei: str
    name: str | None
    country: str | None
    first_period: str | None
    last_period: str | None
    periods: int
    specialist_institution: bool


class BankList(BaseModel):
    rows: list[BankSummary]
    total: int
    page: int
    page_size: int


class PanelSeries(BaseModel):
    bank_id: int
    periods: list[dict[str, Any]]


class CrossSection(BaseModel):
    period: str
    feature: str
    values: list[dict[str, Any]]


class FeatureDefinition(BaseModel):
    name: str
    label: str
    formula: str
    unit: str
    first_period: str
    risk_direction: str


class PanelFeatures(BaseModel):
    features: list[FeatureDefinition]
    flags: dict[str, str]


class IndicatorSeries(BaseModel):
    indicator_id: int
    bank_id: int
    rows: list[dict[str, Any]]
