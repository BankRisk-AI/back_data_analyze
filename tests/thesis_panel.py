"""Small fixed synthetic panel for the v1.1 alert regression (no randomness)."""
from datetime import date

PERIODS = [date(2019, 12, 31), date(2020, 6, 30), date(2020, 12, 31), date(2021, 6, 30)]
# bank -> (cet1, tier1, total, leverage, npl, roe) per period
VALUES = {
    1: [(0.15, 0.16, 0.18, 0.06, 0.02, 0.10), (0.15, 0.16, 0.18, 0.06, 0.02, 0.10),
        (0.14, 0.15, 0.17, 0.06, 0.03, 0.09), (0.14, 0.15, 0.17, 0.06, 0.03, 0.09)],      # healthy
    2: [(0.10, 0.11, 0.13, 0.05, 0.05, 0.05), (0.09, 0.10, 0.12, 0.04, 0.06, 0.03),
        (0.075, 0.09, 0.11, 0.035, 0.08, 0.01), (0.065, 0.08, 0.10, 0.03, 0.09, -0.02)],   # declining to R0 breach
    3: [(0.12, 0.13, 0.15, 0.05, 0.04, 0.06), (0.12, 0.13, 0.15, 0.05, 0.10, 0.06),
        (0.12, 0.13, 0.15, 0.05, 0.12, 0.05), (0.12, 0.13, 0.15, 0.05, 0.13, 0.05)],       # NPL growth across the series break
    4: [(0.20, 0.21, 0.23, 0.08, 0.01, 0.12), (None, None, None, None, None, None),
        (0.20, 0.21, 0.23, 0.08, 0.01, 0.12), (0.20, 0.21, 0.23, 0.08, 0.01, 0.12)],       # missing period
}
NAMES = ("cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio", "npl_ratio", "roe_annualised")


def panel_rows() -> list[dict]:
    rows = []
    for bank, series in VALUES.items():
        for i, (period, values) in enumerate(zip(PERIODS, series)):
            row = {"bank_id": bank, "dataset_version": 100 + i, "period": period, "flags": {},
                   "stage2_share": None, "nace_hhi": None, "sovereign_hhi": None,
                   "loan_growth_qoq": None, "loan_growth_yoy": None}
            row.update(zip(NAMES, values))
            rows.append(row)
    return sorted(rows, key=lambda r: (r["period"], r["bank_id"]))
