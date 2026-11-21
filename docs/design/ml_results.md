# Stage 5b: ML results

The primary run uses T5 on the semi-annual grid, seed `20261121`, and panel
provenance hash recorded in `data/ml/results_T5_semiannual.json`. The artefacts
are git-ignored; no production tables or API endpoints were changed.

## Data and folds

The five expanding folds test 2017, 2018, 2019, 2020, and 2021, with the
preceding year as a 12-month embargo. The final untouched test is 2022--2024;
2025 has no complete 12-month labels. T5 test positives in the five folds are
18, 17, 19, 15, and 13. The model pipeline uses training-fold-only median
imputation and scaling for logistic regression and native missing values for
trees. The randomized-search budget is 60 configurations per model and the
same seed/folds are recorded in the manifest.

## Model comparison

| model | pooled PR-AUC | pooled ROC-AUC | pooled Brier | final PR-AUC | final ROC-AUC |
|---|---:|---:|---:|---:|---:|
| logistic regression | 0.127 | 0.613 | 0.197 | 0.155 | 0.751 |
| random forest | 0.175 | 0.739 | 0.062 | 0.299 | 0.833 |
| XGBoost | 0.210 | 0.761 | 0.063 | 0.212 | 0.873 |
| v1.1 score | 0.125 | 0.635 | -- | 0.019 | 0.344 |
| B4 | 0.114 | 0.666 | -- | 0.025 | 0.495 |
| B2 | 0.077 | 0.541 | -- | 0.025 | 0.499 |

Rule comparator fold PR-AUC / ROC-AUC (2017--2021) is: v1.1
`0.108/0.618, 0.082/0.548, 0.211/0.732, 0.099/0.622, 0.063/0.521`;
B4 `0.094/0.584, 0.083/0.553, 0.246/0.763, 0.105/0.616, 0.061/0.509`;
B2 `0.134/0.574, 0.083/0.523, 0.129/0.526, 0.064/0.495, 0.060/0.493`.
The 2022--2024 final test contains 17 positive T5 labels (2022: 1, 2023: 6,
2024: 10), so all final-test metrics are estimable. Rule ROC-AUC uses the v1.1
0--12 family-score sum; B4 and B2 use their binary scores.

XGBoost has the highest pooled PR-AUC and is the selected model by the
pre-specified selection rule. Random Forest has the highest final-test PR-AUC.
SMOTE variants are recorded as comparison-only fold runs.

## Robustness and statistical tests

The robustness run removes `loan_growth_qoq` and its missingness flag, plus
structural-period missingness flags for stage2, NACE HHI, leverage, and the
three capital ratios. It retains only missingness indicators that are not
period-identifying. The headline run is the robustness run: XGBoost PR-AUC is
0.212 versus 0.210 originally, so the original advantage does not depend on
structural missingness.

| run | LR PR-AUC | RF PR-AUC | XGB PR-AUC | v1.1 PR-AUC | B4 PR-AUC |
|---|---:|---:|---:|---:|---:|
| original | 0.127 | 0.175 | 0.210 | 0.105 | 0.106 |
| robustness (headline) | 0.147 | 0.196 | 0.212 | 0.105 | 0.106 |

| headline XGB difference | 95% bank-bootstrap CI |
|---|---:|
| versus v1.1 | [0.045, 0.187] |
| versus B4 | [0.044, 0.180] |

The fixed-seed bank bootstrap uses 2,000 resamples of the pooled out-of-fold
PR-AUC difference. The 95% intervals are:

| model | versus v1.1 | versus B4 |
|---|---:|---:|
| logistic regression | [-0.009, 0.073] | [-0.009, 0.071] |
| random forest | [0.024, 0.137] | [0.024, 0.133] |
| XGBoost | [0.045, 0.187] | [0.044, 0.180] |

The robustness XGBoost fold differences have Wilcoxon signed-rank p=0.0625
against both v1.1 and B4. With n=5 the smallest possible two-sided p-value is
0.0625.

## Event evaluation

Threshold fitting is defined only on training folds: one threshold matches the
training-period v1.1-red false-alarm rate and the other maximizes `U_r(0.9)`.
The fixed event comparators are v1.1 red (hit 100.0%, false alarm 13.8%), B4
(100.0%, 12.8%), and B2 (66.7%, 1.8%), using the windows and Sarlin metrics
in `rule_evaluation.md`. Out-of-time event reporting is restricted to Novo
Banco, Cyprus Cooperative Bank, Carige, and NordLB; the remaining primary
events require the separately labelled leave-one-event-out analysis.

For the robustness XGBoost, the matched-FAR threshold is 0.074 and the
`U_r(0.9)` threshold is 0.100; both are selected from training-fold
probabilities only. On the out-of-fold rows, false-alarm rates are 13.8% and
10.7%, respectively, versus 17.5% for v1.1 red, 16.4% for B4, and 1.5% for
B2. The corresponding four out-of-time events are all hit by the model under
both settings; v1.1 red and B4 hit 4/4, while B2 hits 2/4.

| event | model probability(s) | matched / U0.9 | v1.1 | B4 | B2 |
|---|---|---|---|---|---|
| Novo Banco | 0.109 | yes / yes | yes | yes | yes |
| Cyprus Cooperative Bank | 0.279 | yes / yes | yes | yes | no |
| Carige | 0.262 | yes / yes | yes | yes | no |
| NordLB | 0.031, 0.126 | yes / yes | yes | yes | yes |

Leave-one-event-out results for the other five primary events are reported as
generalisation, not real-time evaluation: the model's training excludes that
bank's observations, and each event is hit when its available window contains
a score above the matched threshold. Their top-five SHAP explanations are
the same global ranked features below; per-event contributions are stored in
the artefact.

## SHAP

Three rows have missing `tier1_ratio`, all at 2016-12-31: bank IDs 140, 208,
and 234. None is T5-positive, a last observation, or within 12 months of a
primary event. This is a 2016 template gap, not a distress signal, so
`tier1_ratio_missing` is excluded from the robustness run; its original
importance was leakage through a calendar indicator. `loan_growth_qoq_missing`
is likewise structurally missing before 2018-12 because QoQ growth requires
the quarterly regime; it is a frequency-period indicator and is excluded.

| bank | period | T5 | last observation | near event |
|---:|---|---:|---|---|
| 140 | 2016-12-31 | 0 | no | no |
| 208 | 2016-12-31 | 0 | no | no |
| 234 | 2016-12-31 | 0 | no | no |

TreeSHAP was used for the selected XGBoost model. The headline robustness top
10 mean absolute SHAP features are `npl_ratio`, `npl_ratio_rank`,
`total_capital_ratio`, `tier1_ratio`, `loan_growth_yoy`, `sovereign_hhi`,
`cet1_ratio_rank`, `stage2_share`, `roe_annualised`, and
`leverage_ratio_rank`. Structural missingness features are not in this list.
Per-event explanations use the same fitted selected model and are restricted
to the four out-of-time events.

## Sensitivity

T5_noT1 and the quarterly 2018-09+ grid were trained with the same deterministic
pipeline and are stored beside the primary artefact. Their metrics are not
used to select the headline model. SMOTE fold metrics are included in each
JSON artefact as comparison-only results.

## Limitations and thesis note

The sample is small, labels are proxy deterioration targets, and event
coverage is sparse. Crosswalks, specialist exclusion, the 2016 template gaps,
the NPL definition change, and bank exit can affect ranks and missingness.
Events are never used as features. The out-of-time event comparison is
descriptive because only four events have eligible test-fold windows; the
leave-one-event-out table is explicitly not real-time.
