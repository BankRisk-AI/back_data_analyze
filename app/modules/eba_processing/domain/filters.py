"""Parsing of the query-string filters (pure, no database)."""
from __future__ import annotations

from app.core.exceptions import InvalidParameter


def parse_dims(pairs: list[str] | None) -> dict[str, str]:
    """['portfolio:1', 'status:0'] -> {'portfolio': '1', 'status': '0'} (the value may itself contain ':')."""
    out: dict[str, str] = {}
    for p in pairs or []:
        name, sep, value = p.partition(":")
        if not sep or not name:
            raise InvalidParameter(f"dimension filters look like column:value, got '{p}'")
        out[name] = value
    return out
