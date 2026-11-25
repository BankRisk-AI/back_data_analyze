"""Alert routes (paths and responses unchanged since the alert API lived in eba_public_analysis)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.core.api import problem_responses
from app.core.config import get_schema
from app.modules.eba_rules.application import alert_queries as alert_svc
from app.modules.eba_rules.domain.constants import MAX_PAGE_SIZE
from app.modules.eba_rules.presentation.schemas import (
    AlertDetail, AlertListResponse, AlertProfile, AlertSummaryResponse, BankAlerts)

TAG = "public-analysis"   # tag of the published API contract (docs/openapi.yaml); the module adds no tag of its own


def build_router(schema: str | None = None) -> APIRouter:
    schema = schema or get_schema()
    router = APIRouter(prefix="/api/public", tags=[TAG])

    @router.get("/alerts/profiles", response_model=list[AlertProfile],
                operation_id="list_alert_profiles", summary="List evaluated alert profiles")
    def list_alert_profiles():
        return alert_svc.alert_profiles(schema)

    @router.get("/alerts/summary", response_model=AlertSummaryResponse,
                operation_id="summarize_alerts", summary="Summarize alerts by period",
                responses=problem_responses(404, 422))
    def summarize_alerts(profile: Annotated[str | None, Query(description="Profile name, full SHA, or unique SHA prefix (8+ characters)")] = None):
        return alert_svc.alert_summary(profile, schema)

    @router.get("/alerts", response_model=AlertListResponse,
                operation_id="list_alerts", summary="List alerts for a period",
                responses=problem_responses(404, 422))
    def list_alerts(period: Annotated[str, Query(min_length=6, max_length=6)],
                    profile: Annotated[str | None, Query(description="Profile name, full SHA, or unique SHA prefix (8+ characters)")] = None,
                    level: str | None = None,
                    exclude_specialist: bool = True,
                    page: Annotated[int, Query(ge=1)] = 1,
                    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50):
        return alert_svc.alerts(period, profile, level, exclude_specialist, page, page_size, schema)

    @router.get("/banks/{bank_id}/alerts", response_model=BankAlerts,
                operation_id="get_bank_alerts", summary="Get a bank alert timeline",
                responses=problem_responses(404, 422))
    def get_bank_alerts(bank_id: Annotated[int, Path(ge=1)],
                        profile: Annotated[str | None, Query(description="Profile name, full SHA, or unique SHA prefix (8+ characters)")] = None):
        return alert_svc.bank_alerts(bank_id, profile, schema)

    @router.get("/alerts/{alert_id}", response_model=AlertDetail,
                operation_id="get_alert", summary="Get alert details",
                responses=problem_responses(404, 422))
    def get_alert(alert_id: Annotated[int, Path(ge=1)],
                  profile: Annotated[str | None, Query(description="Profile name, full SHA, or unique SHA prefix (8+ characters)")] = None):
        return alert_svc.alert_detail(alert_id, profile, schema)

    return router
