# Stage 5a: ML design (waiting for owner decisions)

This is a design-only document. No model is trained, no migration is proposed,
and the frozen v1.1 rule profile is not changed. The production panel currently
contains 2,516 non-specialist bank-period observations on the semi-annual
2014-06--2025-06 grid after removing specialist institutions. The 9 primary
events remain evaluation labels only.

## Target candidates

For every observation at `t`, labels use only observations strictly after `t`
and no later than `t+12 months`. A bank's observations after its event are
removed. The table reports positive bank-periods, base rate over the 2,516
eligible rows, primary events whose event date falls in a positive window, and
the share of positive rows already red under v1.1 at `t` (a circularity
diagnostic, not a feature).

| target | definition | positives | base rate | primary events covered | v1.1 red overlap |
|---|---|---:|---:|---:|---:|
| T1 | primary event in `(t,t+12m]` | 13 | 0.517% | 9/9 | 100.00% |
| T2 | CET1 >= 11% at `t`, then <11% | 20 | 0.795% | 1/9 | 75.00% |
| T3 | CET1 falls >=3 percentage points | 86 | 3.418% | 1/9 | 20.93% |
| T4 | future RoCET1 <0 and NPL >8%, not both at `t` | 46 | 1.828% | 1/9 | 80.43% |
| T5 | union of T1--T4 | 151 | 6.002% | 9/9 | 45.70% |

Positive counts by year (2014,...,2024; 2025 has no eligible future year) are:
T1 `0,2,5,3,2,1,0,0,0,0,0`; T2 `3,1,9,2,1,2,2,0,0,0,0`;
T3 `1,4,8,13,12,6,13,12,1,6,10`; T4 `2,16,8,2,3,11,3,1,0,0,0`;
T5 `6,20,26,18,17,19,15,13,1,6,10`.

**Owner decision:** use T5 as the primary target. Its event coverage comes
from T1; T2--T4 each cover only 1/9 events because those event banks were
already weak (median uncensored lead 30 months), so onset targets miss them.
Use `T5_noT1 = T2 OR T3 OR T4` as the sensitivity target; T2 alone is
dropped. The event evaluation remains fixed and independent of this choice.

## Sampling grid and features

The primary grid is June/December 2014--2025. Quarterly observations from
2018-09 onward are a sensitivity dataset. Banks flagged
`specialist_institution` are excluded, and observations after that bank's
event are censored. The 11 panel features are:
`cet1_ratio`, `tier1_ratio`, `total_capital_ratio`, `leverage_ratio`,
`npl_ratio`, `stage2_share`, `roe_annualised`, `nace_hhi`, `sovereign_hhi`,
`loan_growth_qoq`, and `loan_growth_yoy`.

For each feature, add the cross-sectional percentile rank within period, a
12-month change (same economic bank and a valid prior observation), and a
missingness indicator. Ranks are calculated using only that period's banks,
making them robust to the NPL definition and frequency breaks. No feature uses
future values. Missing values are never zero-filled: tree models use native
NaN handling; logistic regression imputes the training-fold median only and
retains the missingness indicator. A feature unavailable before IFRS 9 or
because of a template gap remains missing.

## Models and validation

Compare logistic regression with L1 and L2 penalties and
`class_weight=balanced`, Random Forest with balanced class weights, and
XGBoost with its equivalent positive weighting. SMOTE is a comparison-only
pipeline, never the main imbalance strategy. Each model receives the same
randomized-search budget and seed. Select by mean validation PR-AUC, not ROC
AUC. Explain the selected model with SHAP values.

Use five expanding temporal folds with a 12-month embargo. The owner-selected
tests are 2017, 2018, 2019, 2020, and 2021; fold `k` trains on 2014 through
`test_year-2`, with `test_year-1` as the embargo. The final untouched test is
2022--2024 because 2025 has no complete labels:

| fold | train years | embargo | test year | T5 test positives |
|---|---|---|---|---:|
| 1 | 2014--2015 | 2016 | 2017 | 18 |
| 2 | 2014--2016 | 2017 | 2018 | 17 |
| 3 | 2014--2017 | 2018 | 2019 | 19 |
| 4 | 2014--2018 | 2019 | 2020 | 15 |
| 5 | 2014--2019 | 2020 | 2021 | 13 |

The untouched final test period is 2022--2024. Fold preprocessing, percentile
parameters, imputation, class weights, SMOTE, and alert thresholds are fitted
inside each training fold only. Report fold PR-AUC distributions and use a
Wilcoxon signed-rank test across paired folds.

## Comparison with the frozen rules (H2)

Model alerts use the same event windows and denominators as
`rule_evaluation.md`: hit rate, false-alarm rate, NSR, Sarlin relative
usefulness for `mu` in `{0.5, 0.7, 0.8, 0.9, 0.95, 0.99}`, and uncensored lead
time. Choose thresholds using training folds only in two settings: (a) match
the v1.1 red false-alarm rate in the training period, and (b) maximize
`U_r(0.9)` on the training folds. The fixed baselines to beat are B4
(`NPL >8% OR CET1 <11%`) and B2 (`CET1 <11%`). No event outcome is used for
training, threshold selection, or feature construction.

## Leakage and bias checklist

- Apply approved crosswalk groups before constructing changes and ranks.
- Do not compare NPL values across the 2020-06 definition break without a
  missing/break flag.
- Preserve the 2016 decoding/template gaps and do not infer zeros.
- Track banks leaving the sample; do not treat attrition as a negative label.
- Exclude specialists consistently in training and evaluation denominators.
- Use events only for the fixed final evaluation, never target construction
  except for the explicitly measured T1/T5 candidates.

## Waiting for owner decision

1. **Primary target:** decided — T5.
2. **Sensitivity target:** decided — T5_noT1; T2 alone is dropped.
3. **Quarterly sensitivity:** decided — 2018-09 onward.
4. **Model search budget:** decided — 60 configurations per model, common seed/folds.
5. **Threshold policy:** decided — matched-FAR and maximum `U_r(0.9)`.
6. **Interpretability:** decided — TreeSHAP for RF/XGBoost and linear SHAP for LR.
