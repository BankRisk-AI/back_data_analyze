
"""Application configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv


# Project root: directory containing .env and requirements.txt
PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")


def get_database_url() -> str:
    """Return the PostgreSQL connection URL from environment variables."""

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Check the project .env file."
        )

    return database_url


def get_storage_dir() -> str:
    return os.getenv("EBA_STORAGE", "storage")


def get_schema() -> str:
    return os.getenv("EBA_SCHEMA", "public")


def get_max_upload_bytes() -> int:
    return int(float(os.getenv("EBA_MAX_MB", "100")) * 1024 * 1024)


def get_user_id() -> int | None:
    """User recorded as the author of imports until authentication exists."""
    value = os.getenv("EBA_USER_ID")
    return int(value) if value else None


def get_ui_dir() -> str | None:
    return os.getenv("EBA_UI_DIR") or None


def get_cors_origins() -> list[str]:
    """Comma-separated origins allowed to call the API from a browser (empty: same origin only)."""
    return [o.strip() for o in os.getenv("EBA_CORS_ORIGINS", "").split(",") if o.strip()]
