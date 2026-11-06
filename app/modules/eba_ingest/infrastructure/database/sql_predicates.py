"""Kept for compatibility: the predicate now lives in app.shared because other modules need it too."""
from app.shared.sql.predicates import aggregate_rows_predicate

__all__ = ["aggregate_rows_predicate"]
