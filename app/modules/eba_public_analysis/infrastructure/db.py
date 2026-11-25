from __future__ import annotations

from app.core.exceptions import InvalidParameter, NotFoundError
from app.modules.eba_public_analysis.domain import MAX_PAGE_SIZE


def ensure_active(cur, version_id: int) -> None:
    cur.execute("SELECT 1 FROM dataset_version WHERE version_id=%s AND is_active", (version_id,))
    if not cur.fetchone():
        raise NotFoundError(f"active version {version_id} does not exist")


def validate_page(page: int, page_size: int) -> None:
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise InvalidParameter(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
