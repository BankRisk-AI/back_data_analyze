# Stage 3a: `panel_row` design

This is a design based on read-only queries against production `eba` on
2026-11-15.  There are 36 native periods: semi-annual `201412`--`201806` and
quarterly `201809`--`202506`.  Counts below are banks with a usable source
value, not a claim that the value is economically valid.

## Existing schema alignment

`core/001_baseline.sql` already has all requested concepts except that the
requested `roe` name is currently `roe_annualised`. Keep that column name for
compatibility, but call the feature **RoCET1** (return on CET1 capital), not
accounting ROE. The existing `npl_delta_qoq`, `cet1_delta_qoq`,
`min_headroom`, `indicators`, and `flags` remain derived/auxiliary columns.
No migration is proposed in this design.  Optional fully-loaded values should
be placed in `indicators` (or added deliberately in Stage 3b), rather than
silently replacing the transitional columns.

## Shared conventions and source mappings

The canonical master codes are resolved through `indicator_code_map` and the
SDD chain.  A source code is the edition prefix plus the canonical suffix
(for example `1820140` in 2018 and `2520140` in 2025), except 2015 capital
codes (`150135`, `150136`, `150137`) and leverage (`151003`).  The labels below
are the master labels; exact source labels are retained in the map.
Dimension names and values are decoded from the edition's `TR_Metadata.xlsx`
(`Perf_Status`, `Exposure`, `ASSETS_Stages`, `NACE`, and sovereign country
sheets), not inferred from numeric order.

The production bank counts by native period are:

| period | 201412 | 201506 | 201512 | 201606 | 201612 | 201706 | 201712 | 201806 | 201809 | 201812 | 201903 | 201906 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| banks |105|105|131|131|132|132|130|130|122|128|127|131|
| period | 201909 | 201912 | 202003 | 202006 | 202009 | 202012 | 202103 | 202106 | 202109 | 202112 | 202203 | 202206 |
| banks |123|127|131|135|112|116|116|120|107|112|113|122|
| period | 202209 | 202212 | 202303 | 202306 | 202309 | 202312 | 202403 | 202406 | 202409 | 202412 | 202503 | 202506 |
| banks |116|121|119|123|117|120|120|123|116|119|116|119|

### Capital ratios

Features: `cet1_ratio` = master `2520140`, “COMMON EQUITY TIER 1 CAPITAL
RATIO (transitional period)”; `tier1_ratio` = `2520141`, “TIER 1 CAPITAL
RATIO (transitional period)”; `total_capital_ratio` = `2520142`, “TOTAL
CAPITAL RATIO (transitional period)”.  All are `fact_oth.amount`, with the
capital template's total dimensions (`0` where present).  Source chains are
`150135/150136/150137` (2015), `1620140/1620141/1620142` (2016), and
`<edition-prefix>20140/<edition-prefix>20141/<edition-prefix>20142` for
2017--2025.  The 2020+ fully-loaded alternatives are
`2520146` (CET1 ratio; similarly decoded per edition); retain them as optional
columns, not the primary series.  First period: 201412; last: 202506.
Coverage for each ratio is identical:
`105,105,131,131,129,132,130,130,122,128,127,131,123,127,131,135,112,116,
116,120,107,112,113,122,116,121,119,123,117,120,120,123,116,119,111,119`
in the period order above.  Options are transitional (recommended: full
span and regulatory comparability), fully loaded (less transitional distortion
but not full-span), or a paired sensitivity series (most information but more
missingness).  Missing source values get `missing_in_source`.

`leverage_ratio` uses master `2520905`, “Leverage ratio - using a transitional
definition of Tier 1 capital”, from `151003` (2015), no 2016 source, and
`1720905`--`2520905` thereafter.  It is `fact_oth.amount` with total
dimensions.  First available: 201412; last: 202506.  Coverage is 105, 105,
then no values in 201512 or 201606. The observed series has 2015 values and
full bank coverage from 201612 onward: 201412 105; 201506 105; 201612 132;
201706 132; 201712 130; 201806 onward follows the native bank counts except
202503=111.  Options are null for the 2016 template gap (recommended), use
fully-loaded leverage where available, or exclude the feature until 2017;
the first preserves information and exposes the gap.

### `npl_ratio`

Use master `2520603`, “Gross carrying amount on Loans and advances (including
at amortised cost and fair value)”, in `fact_cre`.  The source item is
`<edition-prefix>0603` (`150603` in 2015); total dimensions are
`Portfolio=0`, `Country=0`, `Country_Rank=0`, `Exposure=0`, `Status=0`.
Denominator is the total `Perf_Status=0`; numerator is the
`Perf_Status=2` non-performing row.  This is the gross NPE / gross loans
definition requested, and is preferable to the by-exposure item `2520605`.
Coverage by period is
`96,96,119,120,118,121,119,119,113,118,117,119,115,118,119,122,102,105,
106,109,101,105,106,114,109,112,109,112,106,109,108,111,104,107,104,107`.
First: 201412; last: 202506. Three-bank checks at 201412, 201606, 201812,
202112, and 202506 used the first three available banks in each period; their
observed ranges were 0.0152--0.0920, 0.0141--0.0893, 0.0043--0.1289,
0.0078--0.0325, and 0.0208--0.0688 respectively. All are in [0,1] and
plausible (PASS). The 202506 check was
`0W2PZJM8XOY22M4GG883=0.0223`,
`2138008AVF4W7FMW8W87=0.0688`, and
`2138009Y59EAR7H1UO97=0.0208`: all are in [0,1] and plausible (PASS).
The builder intentionally removes 2016 values because the required
additivity proof failed; those rows carry `template_gap`.
Options are this regulatory Perf_Status definition (recommended), sum all
non-performing substatuses (more inclusive but risks double counting), or
derive from `2520605` by exposure (more detail, less stable).  Add
`missing_in_source` and `invalid_denominator` flags; never impute.

### `stage2_share`

Use `fact_oth` master items `2521017` and `2521019`, respectively “Gross
carrying amount: Financial assets at fair value through other comprehensive
income, Loans and advances” and “... at amortised cost, Loans and advances”.
The source is `1921017/1921019` in 2019 and the edition-prefixed equivalents
through 2025.  Sum both items by `ASSETS_Stages=2` for the numerator and by
stages 1, 2, and 3 for the denominator (the total gross carrying amount of
loans and advances); use all other total dimensions.  Stage 2 starts
201809 (IFRS 9); pre-201809 is NULL with
`not_applicable_before_ifrs9`, not zero.  Coverage 201809--202506 is
`110,115,114,116,112,115,116,119,99,102,103,106,98,102,103,111,106,109,
106,109,103,106,105,108,101,104,101,104`; first 201809, last 202506.
Three-bank 202506 values were 0.0639, 0.0668, and 0.0599 (all [0,1], PASS).
Options are combined FVOCI+amortised-cost (recommended), amortised-cost only
(simpler but incomplete), or include debt securities (not the requested
loans concept).  Flag `template_gap` where stages are absent.

### `roe_annualised` (RoCET1)

Use master `2520335`, “PROFIT OR (-) LOSS FOR THE YEAR”, from `fact_oth.amount`
and `n_quarters`, `fin_end_year`. The amount is YTD: annualised profit is
`profit_ytd * 4 / n_quarters`; use the reported fiscal-year end. If either
field is missing, assume a calendar fiscal year (December = 4 quarters,
June = 2) and set `fiscal_year_assumed`. The feature is RoCET1, not
accounting ROE. The recommended denominator is end-of-period transitional
CET1 capital (`2520102`, edition chain), producing a consistent all-period
proxy: `roe_annualised = annualised_profit / CET1_capital`.  Average CET1
would be preferable economically but requires a prior valid period and makes
entry/exit handling less reproducible.  Total equity (`2521216`) is preferable
accounting ROE but is only available from 2020A, so it cannot be the primary
36-period series.  Tier 1 is a reasonable sensitivity denominator.
Profit coverage is the native bank count in every period, first 201412 and
last 202506; denominator coverage must be intersected and flagged.  Options:
end CET1 (recommended full-span), end Tier 1 (similar span), or average/ending
equity (best accounting meaning, short span).  Add `denominator_missing` and
`fiscal_year_mismatch` flags.

### Loan growth

The base is master `2520603` and the total dimensions above.  `loan_growth_qoq`
is `loans_t / loans_(t-1)` minus one only from 201812, when both observations
belong to the quarterly regime; 201809 has no quarterly predecessor because
201806 is semi-annual.  `loan_growth_yoy` is
`loans_t / loans_(t-4 quarters)` minus one;
for semi-annual history, use `t` versus `t-2 semesters`, so the first
available is 201512.  Require both observations, positive denominator, the
same economic bank, and a continuous source series.  Match LEIs through
`bank.previous_leis`; do not calculate across an unresolved LEI change or
bank entry/exit.  Options are strict continuity (recommended), LEI-crosswalk
continuity with an explicit `identity_crosswalk` flag, or cross-sectional
growth (not recommended).  First QoQ: 201812; first YoY: 201512; last both:
202506.  Missing flags are `no_prior_period`, `bank_entry_exit`, and
`lei_change`.

### `nace_hhi`

Use master `2521301`, “Gross carrying amount”, in `fact_cre`, NACE breakdown
(`nace_codes != 0`) for loans to non-financial corporations; use the
NACE-template total for all other dimensions.  The source is `2021301` (2020S onward) and the edition-prefixed equivalent
through 2025. Check B counted non-zero/non-null NACE rows by master item as
follows: 2020S 13,281; 2020A 16,055; 2021 32,072; 2022 32,376; 2023
33,592; 2024 32,984; and 2025 32,072. No rows exist in earlier editions.
Thus the first usable edition is 2020S
and first period 201909, not a different earlier item or template. Require
`Perf_Status=0` (total/no breakdown) and calculate
`HHI = sum((sector_amount / total_amount)^2)` after excluding null/negative
sectors and require a positive total. First usable period is 201909; last is
202506. Options are raw HHI (recommended), normalized HHI for changing
sector counts (more comparable but less familiar), or entropy (different
concentration measure). Flag `template_gap` for pre-201909 and
`missing_sector`.

### `sovereign_hhi`

Use sovereign master `2520810`, “Direct exposures - On balance sheet - Total
gross carrying amount of non-derivative financial assets”, and its 2018
source `1820810`; 2019 source `1920810` maps to the master.  Use
`fact_sov.country` rows, total accounting portfolio/maturity dimensions
decoded from each edition's sovereign `TR_Metadata` country sheet, and
`HHI = sum((country_amount / total_amount)^2)`.  Country codes are
edition-local and must be normalized through a versioned per-edition code list;
never compare numeric codes directly.  2015--2018 have sovereign data, but
the 2019 template changes both the item/dimensions and code list. `tr_sov` is
semi-annual in every edition, so the feature is NULL in March and September
quarters with `not_reported_this_period`. Same-bank
totals (old `1820810` at 201806 versus new mapped `2520810` at 201812) differ
materially, e.g. LEI `0W2PZJM8XOY22M4GG883`: 17,378.07 versus 13,410.41,
and `2138005O9XJIJN4JPN90`: 210,919.14 versus 145,977.84. Check C found 110
common banks,
mean absolute HHI difference 0.04395, median 0.02704, and Spearman rank
correlation 0.97536. Five examples (201806/201812) are
`0W2PZJM8XOY22M4GG883` (0.69287/0.58528),
`2138004FIUXU3B2MR537` (0.65887/0.74833),
`2138005O9XJIJN4JPN90` (0.22916/0.24747),
`213800TC9PZRBHMJW403` (0.24510/0.25174), and
`213800X3Q9LSAKRUWY91` (0.28002/0.25374). With a combination threshold of
median absolute difference <= 0.05 and Spearman >= 0.90, combine the feature
with a `sovereign_template` flag. Coverage is available from 201412 for the
old item and 201812 for the new template, through 202506.

## Dimension configuration and verification

`python -m app dimensions build eba_prepared` generates the 12 committed
files in `config/dimensions/`: `2015`, `2017`, `2018`, `2019`, `2020S`,
`2020A`, and `2021`--`2025` are decoded; `2016.yaml` is explicitly partial
because its workbook is absent, while its total and non-performing meanings
were proven by continuity. Each decoded sheet stores code, label, and normalized keys where
available (ISO country code and NACE section letter). Check A confirms
`Perf_Status=0` is total and `Perf_Status=2` is the total non-performing
category in every decoded edition; 2016 remains undecoded and must resolve by
meaning only after a continuity proof. The Stage 3c-fix proof established code
0 as total and code 2 as non-performing for 78 common banks; within-period
additivity remains unproven because code 1 is absent, but 2016 NPL is
populated from the proven pair.
For sovereigns, item `1820801` total versus country-breakdown item `1820802`
passed additivity for 178 bank-periods out of 178 within
`max(0.5% of total, 0.5 currency units)`; country code `0` is the verified
total code. These results are recorded in `config/dimensions/2016.yaml`.

## Cross-cutting decisions

Use native periods plus a `frequency` flag (`semi_annual` through 201806,
`quarterly` thereafter), not an invented quarterly grid.  `panel_row` never
imputes values; feature-level JSON flags distinguish `missing_in_source`,
`not_applicable_before_ifrs9`, `template_gap`, invalid denominators, and
identity gaps.  Store cross-sectional outlier flags per feature and period
(robust rule: outside median ± 3 MAD, with a minimum cross-section of 20);
the ML stage decides treatment.

Keep dimension decoding in a version-controlled configuration generated from
each edition's `TR_Metadata.xlsx`, alongside the existing dictionary mapping,
unless audit requirements force a database table.  A new table would change
the current schema count (15); avoiding it is recommended for Stage 3b.
Version panel rows by all active `dataset_version.version_id` values and the
dictionary/configuration hash.  Reloading an edition deactivates its old
version and must rebuild all affected rows plus every dependent growth row.

## Owner decisions recorded

1. Approved transitional capital ratios and leverage as primary.
2. Approved the decoded-meaning NPL definition, subject to Check A (passed).
3. Approved NULL, not zero, for pre-IFRS-9 `stage2_share`.
4. Approved RoCET1 using end-of-period CET1 and YTD annualisation.
5. Approved native semi-annual/quarterly periods with a frequency flag.
6. Approved strict bank/LEI continuity for growth with explicit flags.
7. Modified: NACE is subject to Check B; sovereign HHI is computed separately
   by template and combined only after Check C (passed).
8. Approved configuration-based decoding and no new table.

## Thesis notes

- Table 3.4 replaces `large_exposure_ratio` with `nace_hhi` and
  `sovereign_hhi`.
- RoCET1 is annualised YTD profit divided by end-period CET1 capital; it is
  not accounting ROE.
- Stage 2 begins in 201809 and is not applicable before IFRS 9.
- Sovereign data is semi-annual even while the main panel becomes quarterly.
- The leverage series has gaps for 201512 and 201606.
- NPL before 202006 uses a wider denominator because the `tr_cre` loans and
  advances scope changed from 202006. The published facts do not expose an
  adjustment row; the median scale is about 11%, so affected values retain
  the `series_break` flag rather than being restated.

## Feature flags

`missing_in_source`, `invalid_denominator`, `not_applicable_before_ifrs9`,
`template_gap`, `not_reported_this_period`, `fiscal_year_assumed`,
`denominator_missing`, `fiscal_year_mismatch`, `no_prior_period`,
`bank_entry_exit`, `lei_change`, `identity_crosswalk`, `missing_sector`,
`outlier`, `extreme_growth`, `implausible_value`, `specialist_institution`.
