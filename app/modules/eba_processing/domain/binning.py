"""Pure helpers for histograms: bin edges on a linear or logarithmic scale."""
from __future__ import annotations

import math

from app.core.exceptions import InvalidParameter


def make_edges(lo: float, hi: float, bins: int, scale: str = "linear") -> list[float]:
    """`bins + 1` edges from lo to hi. Linear: equal widths. Log: equal ratios (lo must be positive)."""
    if bins < 1:
        raise InvalidParameter("bins must be at least 1")
    if hi < lo:
        raise InvalidParameter("the upper bound is below the lower bound")
    if lo == hi:
        return [lo, hi]
    if scale == "log":
        if lo <= 0:
            raise InvalidParameter("a logarithmic scale needs positive values")
        a, b = math.log10(lo), math.log10(hi)
        return [10 ** (a + (b - a) * i / bins) for i in range(bins + 1)]
    return [lo + (hi - lo) * i / bins for i in range(bins + 1)]


def transform_bounds(lo: float, hi: float, scale: str) -> tuple[float, float]:
    """Bounds in the space where the bins are equal (the data are transformed the same way in SQL)."""
    return (math.log10(lo), math.log10(hi)) if scale == "log" else (lo, hi)


def clip_bounds(clip: str, mn: float, mx: float, p01: float, q1: float, q3: float, p99: float) -> tuple[float, float, str | None]:
    """Range shown by the histogram and a note. clip='none' shows everything; 'p01-p99' trims the tails; 'iqr' uses the Tukey fences."""
    if clip == "p01-p99":
        return p01, p99, "values outside the 1st and 99th percentiles are counted but not drawn"
    if clip == "iqr":
        fence = 1.5 * (q3 - q1)
        return max(mn, q1 - fence), min(mx, q3 + fence), "values outside the Tukey fences (1.5 x IQR) are counted but not drawn"
    return mn, mx, None
