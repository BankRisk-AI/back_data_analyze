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
