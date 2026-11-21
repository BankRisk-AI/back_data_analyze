# Stage 4d: event-based rule evaluation

Windows are the exact calendar interval from 12 to 3 months before each event date. An event is evaluable when at least one panel observation exists in that interval.

| set | profile SHA | evaluable events | threshold | hit rate | Wilson 95% CI | median lead (months) | false-alarm rate | precision |
|---|---|---:|---|---:|---|---:|---:|---:|
| primary | `28a28fa0f89d` | 9 | red | 100.0% | 70.1--100.0% | 12 | 13.8% | 2.6% |
| primary | `28a28fa0f89d` | 9 | amber_or_red | 100.0% | 70.1--100.0% | 12 | 72.0% | 0.5% |
| all | `28a28fa0f89d` | 11 | red | 81.8% | 52.3--94.9% | 12 | 13.8% | 2.6% |
| all | `28a28fa0f89d` | 11 | amber_or_red | 100.0% | 74.1--100.0% | 11 | 72.0% | 0.6% |

## Per-event observations

| set | bank | event date | type | eligible | observations |
|---|---|---|---|---|---|
| primary | Hamburg Commercial Bank AG (HSH Nordbank) | 2016-05-02 | state_support | yes | 2015-06-30 red (two_families:asset_quality,capital,profitability); 2015-12-31 red (two_families:asset_quality,profitability) |
| primary | Banco Popular Español SA | 2017-06-06 | foltf | yes | 2016-06-30 red (two_families:asset_quality,profitability) |
| primary | Banca Monte dei Paschi di Siena S.p.A. | 2017-07-04 | state_support | yes | 2016-12-31 red (two_families:asset_quality,capital,dynamics,profitability) |
| primary | Banca Popolare di Vicenza SCpA | 2017-06-23 | foltf | yes | 2016-06-30 red (two_families:asset_quality,capital,dynamics,profitability) |
| primary | Veneto Banca SCpA | 2017-06-23 | foltf | yes | 2016-06-30 red (two_families:asset_quality,capital,dynamics,profitability) |
| primary | Novo Banco, SA | 2017-10-11 | state_support | yes | 2016-12-31 red (two_families:asset_quality,profitability); 2017-06-30 red (two_families:asset_quality,capital,profitability) |
| primary | Co-operative Central Bank Ltd (Cyprus Cooperative Bank) | 2018-06-19 | state_support | yes | 2017-06-30 red (two_families:asset_quality,profitability) |
| primary | Banca Carige SpA | 2019-01-02 | early_intervention | yes | 2018-06-30 red (two_families:asset_quality,capital,profitability) |
| primary | Norddeutsche Landesbank - Girozentrale | 2019-12-05 | state_support | yes | 2018-12-31 red (regulatory_breach:leverage_regulatory_min); 2019-03-31 red (regulatory_breach:leverage_regulatory_min); 2019-06-30 red (regulatory_breach:leverage_regulatory_min); 2019-09-30 red (regulatory_breach:leverage_regulatory_min) |
| all | Hamburg Commercial Bank AG (HSH Nordbank) | 2016-05-02 | state_support | yes | 2015-06-30 red (two_families:asset_quality,capital,profitability); 2015-12-31 red (two_families:asset_quality,profitability) |
| all | Banco Popular Español SA | 2017-06-06 | foltf | yes | 2016-06-30 red (two_families:asset_quality,profitability) |
| all | Banca Monte dei Paschi di Siena S.p.A. | 2017-07-04 | state_support | yes | 2016-12-31 red (two_families:asset_quality,capital,dynamics,profitability) |
| all | Banca Popolare di Vicenza SCpA | 2017-06-23 | foltf | yes | 2016-06-30 red (two_families:asset_quality,capital,dynamics,profitability) |
| all | Veneto Banca SCpA | 2017-06-23 | foltf | yes | 2016-06-30 red (two_families:asset_quality,capital,dynamics,profitability) |
| all | Novo Banco, SA | 2017-10-11 | state_support | yes | 2016-12-31 red (two_families:asset_quality,profitability); 2017-06-30 red (two_families:asset_quality,capital,profitability) |
| all | ABLV Bank | 2018-02-23 | foltf | yes | 2017-06-30 amber (family_score:capital,asset_quality) |
| all | Co-operative Central Bank Ltd (Cyprus Cooperative Bank) | 2018-06-19 | state_support | yes | 2017-06-30 red (two_families:asset_quality,profitability) |
| all | Banca Carige SpA | 2019-01-02 | early_intervention | yes | 2018-06-30 red (two_families:asset_quality,capital,profitability) |
| all | Norddeutsche Landesbank - Girozentrale | 2019-12-05 | state_support | yes | 2018-12-31 red (regulatory_breach:leverage_regulatory_min); 2019-03-31 red (regulatory_breach:leverage_regulatory_min); 2019-06-30 red (regulatory_breach:leverage_regulatory_min); 2019-09-30 red (regulatory_breach:leverage_regulatory_min) |
| all | Sberbank Europe AG | 2022-02-28 | foltf | yes | 2021-03-31 amber (family_score:asset_quality,profitability); 2021-06-30 amber (family_score:asset_quality,profitability) |

## Baselines

Fixed baselines use the same event windows, eligibility, specialist exclusion, and non-event definition as v1.1. Wilson intervals are 95%.

| baseline | hit rate | Wilson 95% CI | false-alarm rate | precision | NSR | U_r(0.7) |
|---|---:|---|---:|---:|---:|---:|
| B1 NPL > 8% | 88.9% | 56.5--98.0% | 12.2% | 2.2% | 0.138 | -14.561 |
| B2 CET1 < 11% | 66.7% | 35.4--87.9% | 1.8% | 11.9% | 0.027 | -1.653 |
| B3 RoCET1 < 0 | 88.9% | 56.5--98.0% | 7.5% | 3.2% | 0.084 | -8.694 |
| B4 NPL > 8% or CET1 < 11% | 100.0% | 70.1--100.0% | 12.8% | 2.8% | 0.128 | -14.918 |
| B5 regulatory minima | 11.1% | 2.0--43.5% | 0.2% | 35.7% | 0.020 | -0.020 |
| B6 naive persistence | 100.0% | 70.1--100.0% | 31.4% | 1.2% | 0.314 | -38.184 |
| B7 random baseline | 24.1% expected hit rate | analytical | 13.1% | 24.1% | 0.545 | 0.000 |

## Usefulness

Relative usefulness follows Sarlin (2013). For event-window observations, `T1 = FN/(TP+FN)`, `T2 = FP/(FP+TN)`, `P1 = (TP+FN)/(TP+FN+FP+TN)`, and `P2 = 1-P1`. The loss is `L(mu) = mu*T1*P1 + (1-mu)*T2*P2`; absolute usefulness is `U_a = min(mu*P1, (1-mu)*P2) - L`, and relative usefulness is `U_r = U_a / min(mu*P1, (1-mu)*P2)`. Every value below is produced by the same `relative_usefulness` function; `mu*` is the smallest tested mu with positive usefulness.

`P1 = 0.003430` for this primary evaluation.

| method | U_r(.5) | U_r(.7) | U_r(.8) | U_r(.9) | U_r(.95) | U_r(.99) | mu* |
|---|---:|---:|---:|---:|---:|---:|---:|
| B1 NPL > 8% | -34.929 | -14.561 | -8.196 | -3.246 | -1.162 | 0.354 | .99 |
| B2 CET1 < 11% | -4.714 | -1.653 | -0.696 | 0.048 | 0.048 | 0.589 | .9 |
| B3 RoCET1 < 0 | -21.143 | -8.694 | -4.804 | -1.778 | -0.504 | 0.423 | .99 |
| B4 NPL > 8% or CET1 < 11% | -36.143 | -14.918 | -8.286 | -3.127 | -0.955 | 0.625 | .99 |
| B5 regulatory minima | -0.429 | -0.020 | 0.107 | 0.206 | 0.248 | 0.278 | .8 |
| B6 naive persistence | -90.429 | -38.184 | -21.857 | -9.159 | -3.812 | 0.076 | .99 |
| B7 random baseline | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | -- |
| v1.1 red | -39.214 | -16.235 | -9.054 | -3.468 | -1.117 | 0.594 | .99 |
| v1.1 amber_or_red | -208.500 | -88.786 | -51.375 | -22.278 | -10.026 | -1.116 | -- |

Because event windows are rare, usefulness is negative at moderate mu for nearly every signal. Signals are useful only when a missed distress event costs much more than a false alarm.

## Lead time

Uncensored lead time is measured from the start of the uninterrupted alert run that reaches the last observation before the event; it is not truncated to the 3--12 month evaluation window. The v1.1 primary median is 30 months (red) and 30 months (amber+); windowed median lead is 12 months.

| threshold | median months | min | max |
|---|---:|---:|---:|
| v1.1 red | 30 | 12 | 49 |
| v1.1 amber+ | 30 | 17 | 60 |

## Sensitivity

Excluding the Greek banks listed in the excluded-event catalogue (bank IDs 134, 123, 128, and 135), the v1.1 red false-alarm rate is 12.9% overall; yearly rates are reported in the generated evaluation extract. The primary set excludes these first-observation recapitalisations; no event outcome was used for tuning.

## NordLB diagnostic

| period | CET1 | Tier 1 | leverage | family scores | reason |
|---|---:|---:|---:|---|---|
| 201812 | 6.63% | 7.53% | 2.02% | capital 3; dynamics 2; asset quality 1; profitability 2 | regulatory_breach:leverage_regulatory_min |
| 201903 | 6.54% | 7.25% | 2.01% | capital 3; asset quality 1; profitability 2; dynamics NE | regulatory_breach:leverage_regulatory_min |
| 201906 | 6.63% | 7.34% | 2.09% | capital 3; dynamics 2; asset quality 1; profitability 1 | regulatory_breach:leverage_regulatory_min |
| 201909 | 6.50% | 7.21% | 2.06% | capital 3; dynamics 2; asset quality 1; profitability 1 | regulatory_breach:leverage_regulatory_min |

The regulatory breach wins the final reason because leverage is below 3%; the other family scores remain diagnostic contributors but cannot replace the regulatory-breach reason.

## Version history

Each row uses only its own `profile_sha256` alert rows; the denominators and event windows are otherwise identical.

| profile | red hit rate | red false-alarm rate | NSR | U_r(0.7) | annual red share (2014,...,2025) |
|---|---:|---:|---:|---:|---|
| v0 | 100.0% | 16.1% | 0.161 | -18.990 | 45.0,37.9,30.9,23.5,20.1,16.4,22.9,14.7,10.9,4.2,4.2,3.1% |
| v0.9 | 100.0% | 14.2% | 0.142 | -16.694 | 45.0,37.4,30.9,22.7,19.8,15.1,17.5,11.9,8.3,1.8,3.1,3.1% |
| v1.0 | 100.0% | 28.2% | 0.282 | -34.112 | 64.0,55.3,50.4,45.0,39.7,34.9,32.0,25.6,21.0,10.1,8.4,5.4% |
| v1.1 | 100.0% | 13.8% | 0.138 | -16.235 | 45.0,37.4,30.9,22.7,18.1,14.9,16.5,11.9,8.0,1.8,2.9,2.7% |

The version comparison is for transparency; only v1.1 is the pre-registered profile. The apparently unchanged historical figures were previously calculated from mixed/current rows; filtering by each version's own rows exposes the v1.0 false-alarm increase and the distinct annual red-share paths.

## Limitations

The primary set contains nine events. Semi-annual data provides at most two observations in the window before 2018-09. The sensitivity set includes exogenous events, and the 2020-06 NPL definition change can make comparisons not evaluated. This is an observational evaluation with no profile tuning.

## Thesis note

The evaluation tests whether a frozen, interpretable alert profile provides advance signal before documented distress events without using event outcomes to tune thresholds.
