# AUD-4 — Missing-value gaps in the panel (read-only investigation)

Date: 2026-11-27. Prod DB read with a read-only session; `eba_prepared/` and `eba_data/` read only; no fixes applied.
Chain traced: raw file → `indicator_code_map` → `fact_oth/fact_cre` → `core/panel.py` → `panel_row`.
Scope: panel as stored (all banks, 105–135 rows per period). The `--missing` percentages refer to non-specialists (190 banks); counts below are all panel rows of the period.

## Gap table (unexpected gaps)

| # | indicator | period | edition / file | expected item code(s) | in raw file? | in facts? | in panel? | cause | proposed fix | rows affected |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | leverage_ratio | 2015-12, 2016-06 | edition 2016 / `eba_prepared/2016/tr_oth.csv` (identical to `eba_data/2016/tr_oth.csv`); versions 3, 4 | `2520905` (std) = `1620905` in this edition; numerator `2520901` (`1620901`), exposure `2520903` (`1620903`) | **No.** File holds 90 items (`1620101`–`1620336`: own funds, RWA, P&L). No leverage item under any code or label; `SDD.xlsx` 2016 has no "leverage" entry. `indicator_code_map` has no 2016 row for 184/185/224 either | No (0 rows for 2520905/901/903 in v3, v4) | No (0 of 131 in each period) | The 2016 EBA publication does not contain the leverage template; no other edition covers 2015-12 or 2016-06 (2015 edition = 2014-12/2015-06, 2017 edition = 2016-12/2017-06) | None from the data: not recoverable. Do not forward-fill (leverage not available at all). Keep NULL and document as structural "not published"; exclude these periods for models using leverage, or accept NULL | 0 fillable (262 rows stay NULL) |
| 2 | loan_growth_yoy | 2020-06 (v16), 2020-09 (v17), 2020-12 (v18), 2021-03 (v19) | 2020A (`tr_cre.csv`) and 2021 (`tr_cre.csv`); prior periods 2019-06 (2019), 2019-09, 2019-12 (2020S), 2020-03 (2020A) | loans level `2520603` (`2020603` in 2020A/2020S, `2120603` in 2021, `1920603` in 2019), rows with portfolio/country/rank/exposure/status all '0' and perf_status = "No breakdown" | Yes, in both periods of each pair | Yes, both periods | Inputs yes (`_loan` computed); output NULL, flag `series_break` | Deliberate guard, not a data gap: `_yearly_growth` (`core/panel.py:403`) sets NULL when `prior < 2020-06-30 <= current` (`crosses_series_break`). The break date comes from the NPL series change, but is applied to loans too. A real level shift exists: if forced, the median yoy at the break is −9 % (−8.8, −9.7, −9.1, −9.0 %) against +1.5–5 % in neighbouring periods (p10 −20…−31 %) | Keep the guard (recommended): the 2020 template change breaks the loan definition and the unguarded values are biased. Alternative only if the owner wants coverage: compute yoy without the guard for `loan_growth_yoy` and flag `series_break` (keep the flag, as already done for pre-2020 values); would add rows, but they carry the definitional shift | 414 rows fillable if guard removed (117 + 97 + 100 + 100); 0 recommended |
| 3 | cet1/tier1/total capital ratio; leverage_ratio | 2016-12 (v5) | edition 2017 / `tr_oth.csv`, period 201612 | `2520140/141/142/905` (`1720140/141/142/905`) | Rows present with **empty Amount** (leverage items `0`) for 3 banks: LEIs `9ZHRYM6F...OUG95` (RZB), `815600E4...5E30` (Banco BPM), `5493000L...7H35` (Pekao), with the EBA footnote "only June 2017 data will be presented" (merger / ownership change) | Yes with NULL amount (ratios) / 0 (leverage); 96 facts per bank | No (NULL; flag `missing_in_source`) | Source reports nothing for these 3 banks at 2016-12 (footnote) | None; correct as is. Optional: the 3 banks' 2016-12 rows could be dropped from the panel, they hold no ratio | 3 rows (2.3 % of 132) |
| 4 | cet1/tier1/total capital, leverage (5 %), roe_annualised (14 %) | 2025-03 (v35) | edition 2025 / `tr_oth.csv`, period 202503 | `2520140/141/142/905`, `2520335`, `2520102` | **No** for 5 banks: LEIs `549300GKFG0RYRRQ1414`, `549300Q3OIWRHQUQM052`, `7V6Z97IO7R1SEAO84Q32`, `5493009EIBTCB1X12G89`, `529900OE1FOAM50XLP72` have only 124 rows in 202503 (no capital, P&L, leverage items) whereas they report 205 in 202409/202412 and 207 in 202506. Rest of roe gap (12 banks): P&L item `2520335` absent in raw | Absent (5 banks: 124 other facts, 0 of the needed ones); roe: profit item absent for 12 banks | No: ratios NULL for the 5 banks (111/116 present); roe 99/116 | Incomplete Q1-2025 submission by 5 banks (they were present in 2024-09/12 and 2025-06); the other 12 roe NULLs are banks that never report P&L (the same ~12 banks are NULL in every period 2018-06…2025-06) | None possible from files. The 5 banks' 2025-03 rows contain no capital data; consider excluding rows with no capital data from the panel. Note: the flag `denominator_missing` is misleading, for the 12 banks the **numerator** (profit) is missing | 5 rows (ratios); 5 + 12 rows (roe), none fillable |

## Structural gaps (confirmed, no action)

- `stage2_share` NULL for 2014-12 … 2018-06 (8 periods, 105–132 rows each: 0 values), flag `not_applicable_before_ifrs9` (`core/panel.py:301`, rule `period < 2018-09-01`). From 2018-09 it is filled for 110/122 and 101/116 in 2025-03 (rest: no stage template).
- `loan_growth_yoy` NULL (0 values) in 2014-12 (v2), 2015-06 (v1): no data 12 months earlier (the panel starts 2014-12); 2018-09 (v9) and 2019-03 (v11): the t-12m period (2017-09, 2018-03) was never published, as the data are semi-annual before 2018-12. Flag `no_prior_period`.
- Smaller structural effect: ~12 banks have no P&L every period (roe NULL ~10 %), see row 4.

## Summary

| gap | verdict |
|---|---|
| leverage 2015-12 / 2016-06 | not in the 2016 edition files, not recoverable |
| loan_growth_yoy 2020-06…2021-03 | deliberate series-break guard; data exist; forcing it adds 414 rows with a −9 % definitional shift |
| capital ratios 2016-12 | 3 banks empty in source (mergers) |
| 2025-03 capital / roe | 5 banks missing Capital/P&L/Leverage items in source; 12 banks never report P&L |

## git status --short

```
AM scripts/analyses/data_quality.py
AM scripts/analyses/dataset.py
 M scripts/analyses/draw_graph.py
 M scripts/analyses/main.py
?? docs/audit/AUD-4_missing_gaps.md
```
The `scripts/analyses/*` changes were not made by this investigation (the owner's own work); only `docs/audit/AUD-4_missing_gaps.md` is new.

## Decisions (AUD-4b)

1. **Leverage 2015-12 / 2016-06**: stays NULL. Not published in the 2016 edition, not recoverable; no forward-fill. Documented as structural.
2. **loan_growth_yoy across 2020-06-30**: the guard stays (NULL + `series_break`, 414 rows). The break date is now its own key, `loan_series_break: "2020-06-30"` in `config/ml.yaml`, read by `_yearly_growth` via `core/panel.py:loan_series_break` (key required, no silent default). `npl_series_break` is unchanged and still drives NPL / ML evaluability. Behaviour identical: same NULL rows.
3. **Capital ratios 2016-12 (3 banks) and 2025-03 (5 banks)**: source gaps, no fix. Rows are kept.
4. **ROE flags**: a missing profit (numerator) now sets `numerator_missing`; a missing/zero CET1 amount (denominator) keeps `denominator_missing`; both flags when both are missing. Values unchanged. `numerator_missing` added to `FLAG_NAMES` and `docs/design/panel_design.md`.
5. The configuration hash stored in the panel provenance changes once (`config/ml.yaml` is hashed); no value changes.
