from datetime import date

import pytest

from app.core.panel import (
    _outliers, annualise_profit, crosses_series_break, growth_rate, hhi,
    is_quarter_pair,
)


def test_annualise_profit_uses_reported_quarters():
    assert annualise_profit(100, 2, 6, "2024-06-30") == (200.0, False)


def test_annualise_profit_assumes_calendar_when_metadata_missing():
    assert annualise_profit(100, None, 12, None) == (100.0, True)


def test_hhi_ignores_zero_values_and_returns_concentration():
    assert hhi([50.0, 50.0, 0.0]) == 0.5
    assert hhi([0.0, 0.0]) is None


def test_outliers_support_configurable_k_and_positive_log_transform():
    rows = [{"value": float(i), "_flags": {"value": []}} for i in range(1, 21)]
    rows[-1]["value"] = 100.0
    _outliers(rows, "value", k=3, transform="raw")
    assert "outlier" in rows[-1]["_flags"]["value"]
    rows = [{"value": float(i), "_flags": {"value": []}} for i in range(1, 21)]
    rows[-1]["value"] = 100.0
    _outliers(rows, "value", k=5, transform="log")
    assert "outlier" not in rows[-1]["_flags"]["value"]


def test_growth_does_not_treat_frequency_boundary_as_qoq():
    assert not is_quarter_pair(date(2018, 9, 30), date(2018, 6, 30), "semi_annual")
    assert is_quarter_pair(date(2018, 12, 31), date(2018, 9, 30), "quarterly")
    assert growth_rate(130, 100) == pytest.approx(0.3)
    assert growth_rate(160, 100) == pytest.approx(0.6)
    assert growth_rate(160, 100) != growth_rate(130, 100)


def test_permanent_series_break_only_nulls_cross_definition_growth():
    break_period = date(2020, 6, 30)
    periods = [date(2020, 3, 31), date(2020, 6, 30),
               date(2020, 9, 30), date(2021, 6, 30)]
    assert [crosses_series_break(periods[i], periods[i - 1], break_period)
            for i in range(1, len(periods))] == [True, False, False]


# --- AUD-4b: configurable loan series break, ROE flags ---------------------------------

from app.core.panel import FactIndex, PanelContext, _flags, _roe, _yearly_growth, loan_series_break  # noqa: E402


def _ctx(loan_break):
    return PanelContext(version_ids=[1, 2], period={1: date(2019, 12, 31), 2: date(2020, 12, 31)},
                        year={1: 2019, 2: 2020}, edition={1: "x", 2: "x"}, bank_leis={}, loan_break=loan_break)


def _growth(loan_break):
    row = {"version_id": 2, "_loan": 110.0, "_flags": _flags()}
    prior = {"version_id": 1, "_loan": 100.0}
    _yearly_growth(row, prior, date(2020, 12, 31), _ctx(loan_break))
    return row


def test_loan_guard_reads_configured_break_date():
    assert _growth(date(2020, 6, 30))["loan_growth_yoy"] is None
    assert "series_break" in _growth(date(2020, 6, 30))["_flags"]["loan_growth_yoy"]
    moved = _growth(date(2021, 6, 30))   # break after both observations: no crossing
    assert moved["loan_growth_yoy"] == pytest.approx(0.1)
    moved = _growth(date(2019, 6, 30))   # break before both: no crossing
    assert moved["loan_growth_yoy"] == pytest.approx(0.1)


def test_loan_series_break_is_read_from_ml_yaml_and_required(tmp_path):
    (tmp_path / "ml.yaml").write_text('loan_series_break: "2021-03-31"\n')
    assert loan_series_break(tmp_path) == date(2021, 3, 31)
    (tmp_path / "ml.yaml").write_text('npl_series_break: "2020-06-30"\n')
    with pytest.raises(KeyError):
        loan_series_break(tmp_path)


def test_repo_config_loan_break_equals_npl_break():
    from pathlib import Path
    import yaml
    cfg = yaml.safe_load(Path("config/ml.yaml").read_text())
    assert cfg["loan_series_break"] == cfg["npl_series_break"] == "2020-06-30"


def _roe_row(profit, cet1):
    key = (1, 1)
    facts = FactIndex(capital={}, loans={}, profit={key: [(1, 1, 1, profit, 4, "2024")]} if profit is not None else {},
                      cet1={key: [(1, 1, 1, cet1)]} if cet1 is not None else {}, leverage_tier1={},
                      leverage_exposure={}, stage={}, nace={}, sov_by_code={})
    row = {"_flags": _flags()}
    _roe(row, key, 12, facts)
    return row


def test_roe_missing_profit_flags_numerator():
    row = _roe_row(None, 1000.0)
    assert row["roe_annualised"] is None
    assert row["_flags"]["roe_annualised"] == ["numerator_missing"]


def test_roe_missing_cet1_flags_denominator():
    row = _roe_row(50.0, None)
    assert row["roe_annualised"] is None
    assert row["_flags"]["roe_annualised"] == ["denominator_missing"]


def test_roe_complete_has_no_missing_flag_and_unchanged_value():
    row = _roe_row(50.0, 1000.0)
    assert row["roe_annualised"] == pytest.approx(0.05)
    assert row["_flags"]["roe_annualised"] == []
