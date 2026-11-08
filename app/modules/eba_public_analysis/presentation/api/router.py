from __future__ import annotations

from typing import Annotated, Literal
from fastapi import APIRouter, Path, Query

from app.core.api import problem_responses
from app.core.config import get_schema
from app.modules.eba_public_analysis.application import analysis
from app.modules.eba_public_analysis.domain import MAX_PAGE_SIZE
from app.modules.eba_public_analysis.presentation.api.schemas import (
    Aggregate, Histogram, Preview, Profile, PublicPeriod, Scatter,
)

TAG = "public-analysis"
Dataset = Literal["oth", "cre", "mrk", "tr_oth", "tr_cre", "tr_mrk"]
AggregateFunction = Literal["sum", "avg", "min", "max", "count"]


def build_router(schema: str | None = None) -> APIRouter:
    schema = schema or get_schema()
    router = APIRouter(prefix="/api/public", tags=[TAG])

    @router.get("/periods", response_model=list[PublicPeriod], operation_id="list_public_analysis_periods",
                summary="List active public periods")
    def list_periods():
        return analysis.periods(schema)

    @router.get("/versions/{version_id}/datasets/{dataset}/preview", response_model=Preview,
                operation_id="preview_public_analysis", summary="Preview promoted public data",
                responses=problem_responses(404, 422))
    def preview(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")],
                page: Annotated[int, Query(ge=1)] = 1,
                page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50):
        return analysis.preview(version_id, dataset, schema, page, page_size)

    @router.get("/versions/{version_id}/datasets/{dataset}/profile", response_model=Profile,
                operation_id="profile_public_analysis", summary="Profile promoted public data",
                responses=problem_responses(404, 422))
    def public_profile(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")]):
        return analysis.profile(version_id, dataset, schema)

    @router.get("/versions/{version_id}/datasets/{dataset}/histogram", response_model=Histogram,
                operation_id="histogram_public_analysis", summary="Histogram data for a public item",
                responses=problem_responses(404, 422))
    def public_histogram(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")],
                         item: Annotated[str, Query(description="Indicator code")],
                         period: Annotated[str, Query(description="YYYYMM period")],
                         bins: Annotated[int, Query(ge=1, le=200, description="Number of histogram bins")] = 20):
        return analysis.histogram(version_id, dataset, item, period, schema, bins)

    @router.get("/versions/{version_id}/datasets/{dataset}/aggregate", response_model=Aggregate,
                operation_id="aggregate_public_analysis", summary="Calculate a backend public aggregation",
                responses=problem_responses(404, 422))
    def public_aggregate(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")],
                         item: Annotated[str, Query(description="Indicator code")],
                         period: Annotated[str, Query(description="YYYYMM period")],
                         function: Annotated[AggregateFunction, Query(description="Aggregation function")] = "sum"):
        return analysis.aggregate(version_id, dataset, item, period, function, schema)

    @router.get("/versions/{version_id}/datasets/{dataset}/scatter", response_model=Scatter,
                operation_id="scatter_public_analysis", summary="Scatter plot points for two public items",
                responses=problem_responses(404, 422))
    def public_scatter(version_id: int, dataset: Annotated[Dataset, Path(description="Public dataset or tr_ alias")],
                       item_x: Annotated[str, Query(description="Indicator code for the x axis")],
                       item_y: Annotated[str, Query(description="Indicator code for the y axis")],
                       period: Annotated[str, Query(description="YYYYMM period")]):
        return analysis.scatter(version_id, dataset, item_x, item_y, period, schema)

    return router
