"""Response models of the alert API."""
from typing import Any

from pydantic import BaseModel


class AlertProfile(BaseModel):
    profile_name: str
    version: str | None
    sha: str
    frozen: bool | None
    created_at: str
    rule_count: int
    families: list[str]


class AlertSummary(BaseModel):
    period: str
    counts: dict[str, int]
    shares: dict[str, float]


class AlertSummaryResponse(BaseModel):
    profile_name: str
    profile_sha256: str
    periods: list[AlertSummary]


class AlertListItem(BaseModel):
    alert_id: int
    bank_id: int
    lei: str
    bank_name: str | None
    period: str
    level: str
    reason: str | None
    family_scores: dict[str, Any] | None


class AlertListResponse(BaseModel):
    rows: list[AlertListItem]
    total: int
    page: int
    page_size: int


class BankAlerts(BaseModel):
    bank_id: int
    rows: list[dict[str, Any]]


class AlertDetail(BaseModel):
    alert_id: int
    bank_id: int
    version_id: int
    period: str
    level: str
    score: float | None
    reason: str | None
    family_scores: dict[str, Any] | None
    rules: list[dict[str, Any]]
    profile_name: str
    profile_version: str | None
    profile_sha256: str
