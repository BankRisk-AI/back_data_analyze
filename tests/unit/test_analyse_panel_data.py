"""scripts.analyses.panel_data.get_panel filters only by the given arguments (load_panel stubbed, no database)."""
from datetime import date

import pytest

from scripts.analyses import panel_data


class _Panel:
    rows = [{"bank_id": b, "period": p} for b in (1, 2) for p in (date(2019, 12, 31), date(2020, 6, 30))]


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    monkeypatch.setattr(panel_data, "load_panel", lambda cur: _Panel)


def keys(rows):
    return [(r["bank_id"], r["period"].isoformat()) for r in rows]


def test_no_arguments_returns_every_row():
    assert len(panel_data.get_panel(cur=object())) == 4


def test_filters_by_bank_period_and_range():
    cur = object()
    assert keys(panel_data.get_panel(bank_id=2, cur=cur)) == [(2, "2019-12-31"), (2, "2020-06-30")]
    assert keys(panel_data.get_panel(period="202006", cur=cur)) == [(1, "2020-06-30"), (2, "2020-06-30")]
    assert keys(panel_data.get_panel(bank_id=1, date_from="2020-01-01", cur=cur)) == [(1, "2020-06-30")]
    assert keys(panel_data.get_panel(date_to=date(2019, 12, 31), bank_id=2, cur=cur)) == [(2, "2019-12-31")]
