"""Read the panel for analysis: the standard rows of `load_panel`, filtered by the given arguments only."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from app.core.config import get_schema
from app.core.database import connect
from app.core.panel_reader import load_panel


def _as_date(value: date | str) -> date:
    """'2016-12-31' or '201612' (month end) -> date."""
    if isinstance(value, date):
        return value
    text = str(value).replace("-", "")
    if len(text) == 6:
        year, month = int(text[:4]), int(text[4:])
        next_month = date(year + (month == 12), month % 12 + 1, 1)
        return date.fromordinal(next_month.toordinal() - 1)
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


@contextmanager
def _read_only_cursor():
    conn = connect(get_schema())
    conn.commit()                            # keeps the session search_path set by connect()
    conn.set_session(readonly=True)          # SELECT only
    try:
        yield conn.cursor()
    finally:
        conn.rollback()
        conn.close()


def get_panel(bank_id: int | None = None, period: date | str | None = None,
              date_from: date | str | None = None, date_to: date | str | None = None,
              cur=None) -> list[dict]:
    """Rows of the active panel (list of dicts), filtered only by the arguments that are given.

    Columns: bank_id, period (date), frequency, dataset_version, cet1_ratio, tier1_ratio, total_capital_ratio,
    leverage_ratio, npl_ratio, stage2_share, roe_annualised, nace_hhi, sovereign_hhi, loan_growth_qoq,
    loan_growth_yoy, npl_delta_qoq, cet1_delta_qoq, min_headroom, flags (dict), is_specialist.
    bank_id: one bank; period: one period end; date_from / date_to: inclusive range.
    """
    if cur is None:
        with _read_only_cursor() as read_cursor:
            rows = load_panel(read_cursor).rows
    else:
        rows = load_panel(cur).rows
    if bank_id is not None:
        rows = [r for r in rows if r["bank_id"] == bank_id]
    if period is not None:
        rows = [r for r in rows if r["period"] == _as_date(period)]
    if date_from is not None:
        rows = [r for r in rows if r["period"] >= _as_date(date_from)]
    if date_to is not None:
        rows = [r for r in rows if r["period"] <= _as_date(date_to)]
    return rows
