# AUD-1 — How the rule engine gets its data (read-only audit)

Date: 2026-11-25 · Database: prod `eba` (SELECT only) · Code state: after R-3 (module `eba_rules`).
No code, data or repository state was changed. All numbers below were read from the database or computed
from it; line numbers refer to the working tree at audit time.

Profile used throughout: `eu_eba` v1.1, sha256 `28a28fa0f89da8435abdb0d6042a69cb2bff421c456926374dd202e0089f7e40`
(4,367 alerts: 2,370 amber, 1,135 green, 577 red, 285 not_evaluated).

---

## 1. Flow map

### D1 — Imported facts and `dataset_version`

| | |
|---|---|
| Input | prepared EBA CSV/XLSX per edition (`eba_prepared/<edition>/tr_oth.csv`, `tr_cre.csv`, `tr_mrk.csv`, `tr_sov*.csv`, `SDD.xlsx`, `TR_Metadata.xlsx`) → staging tables |
| Output | `fact_oth`, `fact_cre`, `fact_mrk`, `fact_sov` (one row per bank, indicator, dimension combination, version); `dataset_version(year, quarter, period_end, import_id, version_no, is_active)`; `bank`, `indicator` |
| Code | `app/modules/eba_ingest/application/load_executor.py:_load` (l.120); version creation l.304-321; item→indicator mapping l.330-366; fact insert l.421 |
| Configuration | `indicator_code_map` (edition, dataset, source_item → indicator); `config/data_decisions.yaml` (`app/core/data_decisions.py`) for owner exclusions; `config/bank_crosswalk.yaml` is **not** used here |
| Which version is active | One `dataset_version` is created per (year, quarter) found in the files of an import (l.309-320). If an active version for that (year, quarter) already exists it is set `is_active=false` (l.312-315) and the new one gets `version_no = max+1`. So **the last loaded import wins per quarter**. Downstream code uses `WHERE v.is_active`. |
| In prod now | 36 versions (2014-12 … 2025-06), all `version_no=1`, all active, 0 inactive; 12 imports, each loading distinct periods (checked on the raw files: no period appears in two editions) |
| What can change a value | amounts are stored as delivered, in the delivered unit (ratios as fractions, amounts in million EUR); aggregate rows are excluded (`non_aggregate` predicate) and never reach the facts; decisions in `data_decisions.yaml` drop/override rows; an unmapped item keeps its source code (`method='unmapped'`, l.350-355); a LEI is resolved to a bank through current or `previous_leis` (l.265-285) |

### D2 — Panel construction into `panel_row`

| | |
|---|---|
| Input | active `dataset_version`; `fact_oth` (indicators 2520140/41/42/905 ratios, 2520335 profit, 2520102 CET1 amount, 2520901/903 leverage parts, 2521017/19 stages), `fact_cre` (2520603 gross loans, 2521301 NACE), `fact_sov`; `config/dimensions/<edition>.yaml`; `config/bank_crosswalk.yaml`; `config/specialist_institutions.yaml` (via `app/core/specialists.py`) |
| Output | `panel_row(version_id, bank_id, 11 features, npl_delta_qoq, cet1_delta_qoq, flags jsonb, build_provenance)`; 4,367 rows, 203 banks |
| Code | `app/core/panel.py:build_panel` l.149-439 (run by `python -m scripts.data.build_reference panel`) |
| Row set | every (version, bank) that has at least one fact in any of the four fact tables (l.173-181). Nothing is dropped for specialists or missing values. |
| Capital ratios | copied from the reported item, not recomputed: CET1 `2520140`, Tier 1 `2520141`, total capital `2520142`, leverage `2520905` (l.269-280); first non-null value `_first(..., 3)` (no ORDER BY; the unique fact key makes it a single row in practice). Leverage `0` → recomputed check `2520901/2520903`, else `NULL` + `implausible_value` (l.272-278). Missing → `NULL` + `missing_in_source`. |
| NPL ratio | `numerator / denominator` over `fact_cre` item 2520603, only the "total" rows (`portfolio, country, country_rank, exposure, status` all `0`, l.281-282); denominator = `Perf_status` code labelled "No breakdown…", numerator = code labelled exactly "Non Performing" (decoded per edition from `config/dimensions/<edition>.yaml`, l.283-304). `NULL` if denominator ≤ 0. |
| Stage 2 share | from 2018-09 only (l.306); Stage 2 / (Stage 1+2+3) from `ASSETS_Stages` labels |
| RoCET1 | `profit × 4 / n_quarters / CET1 amount` (item 2520335 / 2520102); `n_quarters` from the fact, else derived from the month (l.74-80, 320-330); `fiscal_year_assumed` when `n_quarters` or `fin_end_year` is empty |
| NACE / sovereign HHI | l.331-344; sovereign only for months 6 and 12 |
| Frequency | `semi_annual` if period ≤ 2018-06-30, else `quarterly` (l.268) |
| Series break | NPL: `series_break` flag on every period < 2020-06-30 (l.303-304; the 2016 branch l.283-293 always flags). Growth features: set to `NULL` + `series_break` when the comparison crosses 2020-06-30 (l.372-401). The NPL value itself is **not** altered or rescaled. |
| Crosswalk merge | approved groups of `bank_crosswalk.yaml` give a `continuity_key` (l.192-198) used **only** to find the prior row for QoQ/YoY growth and deltas (l.349-407). `bank_id` is not merged; rows keep their own `bank_id`. Flag `group_crosswalk` on 494 rows (30 banks). |
| Specialist exclusion | flag `specialist_institution` on all features (l.199-205): 282 rows, 13 banks. Rows are kept; exclusion happens in eba_rules (E) and in the API (F/G). |
| Outliers | per version and feature, MAD rule k=3 (l.122-141, 408-413): flag only, value unchanged |
| What can change a value | dimension decoding (wrong label → wrong numerator); `status/portfolio…='0'` filter silently drops differently-keyed totals; `denom<=0 → NULL`; `n_quarters` from the file drives the annualisation factor; CET1 amount `0/NULL → ROE NULL` |

### E — `eba_rules` evaluation

| | |
|---|---|
| Input | `panel_row ⨝ dataset_version` for active versions (`eba_rules/infrastructure/alert_repository.py:fetch_active_panel` l.16): the 11 features, `flags`, `period = period_end` |
| Output | per row: `level`, `score`, `rule_results{rules, family_scores, level_reason}` |
| Code | worker job `evaluate_rules` (`application/handler.py`) → `application/evaluate.py:evaluate_panel` l.18 → `application/profiles.py:load_profile` l.50 (module.yaml registry, **sha256 check of frozen profiles**, strict schema `domain/profile_schema.py`) → `domain/alert_level.py:evaluate_rows` l.59 → `domain/rule_evaluation.py:evaluate_rule` l.140 |
| Configuration | `app/modules/eba_rules/config/module.yaml`, `profiles/eu_eba_v1.1.yaml` (frozen), `regulatory_levels.yaml` (R0/R1, not used by the alert levels) |
| Thresholds | level rules: single threshold (`_condition`, l.47-58) or bands red/amber/green (`band_of`, l.60-70). trend: value − value(comparison period) with `decrease_over`/`increase_over` (`_trend` l.97). persistence: condition true now and half a year ago (`_persistence` l.111, prior = previous half-year end, l.81). relative: percentile of the cross-section of the same period without specialists (`_relative` l.124). |
| Family severity | `rule_severity` l.169: id ending `_regulatory_min` or `cet1_buffer_warning` → 3; relative → 1; trend/persistence → 2; `leverage_supervisory_low` → 1 (hard-coded); band rules → 2 if the value is in the red band else 1; other → 1. `rule_family` l.153 from `family` or feature. |
| Family score / level | per family the maximum severity of evaluated rules (`family_scores`, `alert_level.py` l.26); score = sum of the four family scores; specialist → `not_evaluated`; no family evaluated → `not_evaluated`; any family 3 → red; ≥2 families with score ≥2 → red; sum ≥ 2 → amber; else green (`alert_level` l.40-56). The `cutoffs` of `composite_alert` in the YAML are **not** read. |
| What can change a value | `NULL` features (rule `not_evaluated`, family drops out); `flags` (`specialist_institution`, `series_break`) ; comparison-period availability (`_comparison_period` l.73: before 2018-09 index shift of the global period list, after: calendar year, 2-period trends return `None`); the percentile cross-section; the frozen-profile sha |

### F — `alert` table

| | |
|---|---|
| Output | one row per (bank_id, version_id, profile_sha256): `alert_id, profile_name, profile_sha256, score, level, rule_results jsonb, created_at` (`011_alert.sql`) |
| Code | `alert_repository.replace_alerts` l.23: `DELETE WHERE profile_sha256=…` then insert, one transaction |
| Keys | `(profile_sha256, version_id, bank_id)` unique; the period is reached through `dataset_version.period_end` |
| In prod | 4 profile shas × 4,367 rows: `28a28fa0…` (v1.1, 2026-11-21 12:05), `5a1ec1f4…` (v1.0, **2026-11-21 13:30, newest**), `794ea5ad…` (v0.9), `1296bd8e…` (v0). 0 panel rows without alerts, 0 alerts without panel rows. |

### G — API and UI

| | |
|---|---|
| Routes | `GET /api/public/alerts/profiles`, `/alerts/summary`, `/alerts?period=YYYYMM`, `/banks/{id}/alerts`, `/alerts/{alert_id}` — `app/modules/eba_rules/presentation/router.py`, services `application/alert_queries.py` (`alert_profiles` l.76, `alert_summary` l.94, `alerts` l.118, `bank_alerts` l.147, `alert_detail` l.164) |
| Profile resolution | `_resolve_profile` l.36: no `profile` → the **most recently created sha of the name `eu_eba`**; name, full sha or ≥8-char prefix accepted |
| UI (`/var/projects/webstorm/eba-ingest-ui/src`) | `api/client.ts` l.103-109; `pages/AlertsPages.tsx`: `latestEbaProfile` l.13 (default profile), `AlertsOverviewPage` l.44, `AlertsHeatmapPage` l.66, `BankAlertsTab` l.78, `AlertDetailPage` l.86 (table "Rule results": Input = `input_value`, Threshold, Severity, Status) |
| What can change a value | API drops specialist banks from the summary always and from lists unless `exclude_specialist=false`; `profile_version`/`frozen` shown come from the **current file of the same name**, not from the sha (finding F2) |

---

## 2. Three traced cases (profile `28a28fa0…`)

### 2a. Banca Monte dei Paschi di Siena (bank_id 68), 2016-12-31

**D1** — `dataset_version` 5 (2016-Q4), import 3 (edition `2017`), `version_no 1`, active.
Facts, `fact_oth`, version 5, bank 68 (all `n_quarters=4`, `fin_end_year` NULL):

| item | indicator | amount |
|---|---|---|
| 2520140 CET1 ratio (transitional) | 134 | 0.0817042838 |
| 2520141 Tier 1 ratio | 135 | 0.0817042838 |
| 2520142 total capital ratio | 136 | 0.1040468848 |
| 2520905 leverage ratio | 185 | 0.03167 |
| 2520102 CET1 capital | 101 | 5,353.39973 |
| 2520335 profit/loss for the year | 181 | −3,241.148199 |
| 2520901 / 2520903 leverage T1 / exposure | 224 / 184 | 5,353.399731 / 169,024.39811 |

`fact_cre`, item 2520603 (gross loans), total rows (portfolio=country=rank=exposure=0), by `perf_status`/`status`:
`perf 0, status 0`: 139,737.3871 · `perf 2 (Non Performing), status 0`: 45,770.982329 · `perf 3, status 0`: 1,263.088143 ·
`perf 4, status 2`: 45,770.982328 (dropped by the `status='0'` filter).

**D2** — `panel_row(5, 68)`: cet1 0.0817042838, tier1 0.0817042838, total 0.1040468848, leverage 0.03167,
**NPL 0.32755000847586335 = 45,770.982329 / 139,737.3871** (code: denominator = `perf_status` "No breakdown", numerator = "Non Performing"),
**RoCET1 −0.6054373598961571 = (−3,241.148199 × 4/4) / 5,353.39973**, loan_growth_yoy −0.00983.
Flags: npl `['series_break','outlier']`, roe `['fiscal_year_assumed','outlier']` (assumed because `fin_end_year` is NULL), `stage2_share not_applicable_before_ifrs9`, `nace_hhi/sovereign_hhi template_gap`, `frequency semi_annual`. Not a specialist, not in a crosswalk group.
Recomputation of ratios from the amounts: Tier 1 = CET1 (identical in the source); leverage 0.03167 vs 5,353.399731/169,024.39811 = 0.03167 ✓.

**E** — rule results (value → threshold → severity):

| rule | input | threshold | trig. | sev. | family |
|---|---|---|---|---|---|
| cet1_regulatory_min | 0.0817 | < 0.045 | no | 0 | capital |
| tier1_regulatory_min | 0.0817 | < 0.06 | no | 0 | capital |
| total_capital_regulatory_min | 0.1040 | < 0.08 | no | 0 | capital |
| leverage_regulatory_min | 0.03167 | < 0.03 | no | 0 | capital |
| cet1_buffer_warning | 0.0817 | < 0.07 | no | 0 | capital |
| tier1_dashboard_band | 0.0817 | red < 0.12 | yes | 2 | capital |
| cet1_supervisory_low | 0.0817 | red < 0.11 | yes | 2 | capital |
| leverage_supervisory_low | 0.03167 | red < 0.05 | yes | 1 (hard-coded) | capital |
| cet1_worst_decile | 0.0817 | ≤ P10 = 0.11607 | yes | 1 | capital |
| npl_high | 0.3276 | > 0.05 | yes | 1 | asset_quality |
| npl_dashboard_band | 0.3276 | red > 0.08 | yes | 2 | asset_quality |
| high_npl_persistence | 0.3276 | > 0.05 now and 2016-06 (0.3331) | yes | 2 | asset_quality |
| npl_worst_decile | 0.3276 | ≥ P90 = 0.22485 | yes | 1 | asset_quality |
| rocet1_supervisory_low | −0.6054 | red < 0.0720087 | yes | 2 | profitability |
| negative_rocet1_persistence | −0.6054 | < 0 now **and** 2016-06 (+0.0703) | **no** | 0 | profitability |
| cet1_yoy_drop | stored 0.0817 (the value; the tested change is 0.0817 − 0.1201 [2015-12] = −0.0383) | decrease > 0.02 | yes | 2 | dynamics |
| npl_yoy_rise | 0.3276 (change −0.0047) | increase > 0.01 | no | 0 | dynamics |

Family scores: capital 2 (`tier1_dashboard_band`), asset_quality 2 (`npl_dashboard_band`), profitability 2 (`rocet1_supervisory_low`),
dynamics 2 (`cet1_yoy_drop`). No severity-3 rule → no regulatory breach. Score 8 (sum). Four families ≥ 2 → **level red**,
reason `two_families:asset_quality,capital,dynamics,profitability`. Persistence check: the negative-ROE persistence is false because
the previous half-year (2016-06-30) RoCET1 was positive; the NPL persistence is true (both periods above 5%).

**F** — `alert_id 35466`, version 5, bank 68, sha `28a28fa0…`, score 8.0, level red. (Same bank/period under the other shas:
39833 = `5a1ec1f4…` red 8.0; 22365 = `1296bd8e…` red 13.0; 17998 = `794ea5ad…` red 6.0.)

**G** — `GET /api/public/alerts?period=201612&profile=28a28fa0…&exclude_specialist=false` row for bank 68:
`{"alert_id":35466,"bank_id":68,"lei":"J4CP7MHCXR8DAQMKIL78","bank_name":"Banca Monte dei Paschi di Siena S.p.A.","period":"201612","level":"red","reason":"two_families:asset_quality,capital,dynamics,profitability","family_scores":{"capital":{"score":2,"rule_id":"tier1_dashboard_band","not_evaluated":false},"dynamics":{"score":2,"rule_id":"cet1_yoy_drop",…},"asset_quality":{"score":2,"rule_id":"npl_dashboard_band",…},"profitability":{"score":2,"rule_id":"rocet1_supervisory_low",…}}}`.
`GET /api/public/alerts/35466` adds `score 8.0`, `profile_name eu_eba`, `profile_version "1.1"`, `profile_sha256 28a28fa0…` and the 17 rule rows
(`cet1_yoy_drop`: `input_value 0.0817042838`, `threshold 0.02`, `triggered true`, `severity 2`). UI: `AlertDetailPage` shows these rows; the heatmap cell (`AlertsHeatmapPage`) and the bank strip (`BankAlertsTab`) show the red level.
Trajectory 2015-06 … 2017-12 for the same bank: red in all six half-years (scores 6, 7, 7, 8, 9, 5).

### 2b. Large bank without problems, 2019-12-31 — ING Groep N.V. (bank_id 89), quarterly regime

None of the large banks I checked is *green*: Santander, BNP, Rabobank, Danske, Deutsche, Crédit Agricole, ING, Intesa, Lloyds, Nordea, Nationwide are **amber** at 2019-12 and 2020-06 (finding F4). ING was chosen: CET1 14.6 %, NPL 1.4 %.

**D1** — `dataset_version` 14 (2019-Q4), import 6 (edition `2020S`), active. `fact_oth` bank 89: 2520140 = 0.1456804694, 2520141 = 0.1670225462, 2520142 = 0.1908703958, 2520905 = 0.046, 2520335 = 4,879.34 (`n_quarters 4`, `fin_end_year 0`), 2520102 = 47,552.20208. `fact_cre` 2520603 totals: perf 0 = 741,935.591; perf 2 = 10,549.383; perf 3 = 1,654.982.
**D2** — `panel_row(14, 89)`: cet1 0.1456804694, tier1 0.1670225462, total 0.1908703958, leverage 0.046, **NPL 0.014218731555634457 = 10,549.383 / 741,935.591**, **RoCET1 0.10261017968823369 = 4,879.34 × 4/4 / 47,552.20208**, loan_growth_yoy 0.0046. Flags: `frequency quarterly`, npl `series_break`, loan_growth_qoq/yoy `series_break`. (`fin_end_year = "0"` is truthy → no `fiscal_year_assumed`, unlike the 2018-12 row.)
**E** — evaluated rules: all regulatory/dashboard CET1, Tier 1, total capital, NPL rules not triggered (e.g. `cet1_supervisory_low` 0.1457 > 0.14 green band; `npl_dashboard_band` 0.0142 < 0.03 green). Triggered: `leverage_supervisory_low` (0.046 < 0.05, red band but severity **1** by the hard-coded exception), `rocet1_supervisory_low` (0.1026, amber band 0.072–0.120 → severity 1). `cet1_yoy_drop`, `negative_rocet1_persistence`, `high_npl_persistence` evaluated and false. Families: capital 1, profitability 1, asset_quality 0, dynamics 0 → score 2, **level amber** (`family_score:capital,profitability`; rule `amber` cutoff = sum ≥ 2).
**F** — `alert_id 36623`, level amber, score 2.0. **G** — `alert_detail(36623)` returns `level amber`, `reason family_score:capital,profitability`, `profile_version "1.1"`.

### 2c. The same bank, 2020-06-30 — NPL around the series break

**D1** — `dataset_version` 16 (2020-Q2), import 7 (edition `2020A`). `fact_cre` 2520603 totals: perf 0 = 698,745.239; **perf 2 = 13,082.575**; perf 23 ("NON performing — of which Stage 3") = 12,983.552 (not summed: the code takes the exact label "Non Performing" = code 2, and excludes `of which` codes); perf 3 = 1,169.567. `fact_oth`: 2520905 = 0.0433, 2520335 = 1,005.062 with `n_quarters 2`, 2520102 = 48,222.1642083.
**D2** — **NPL 0.018722954046489042 = 13,082.575 / 698,745.239** (+0.45 pp vs 2019-12, 0.0142). **No `series_break` flag on this row** — the flag is only set on periods < 2020-06-30 (`panel.py:303-304`); the row is the first on the new definition. RoCET1 = 1,005.062 × 4/2 / 48,222.1642083 = 0.04168464922721195.
**E** — level NPL rules evaluated normally (documented "evaluate with known limitation", profile `defaults.series_break`): `npl_high` 0.0187 < 0.05, `npl_dashboard_band` green, `npl_worst_decile` P90 = 0.0936, all false. Rules that compare across the break are **not evaluated**: `npl_yoy_rise` (comparison 2019-06-30 < break ≤ 2020-06-30; flag `series_break`, `not_evaluated true`) and `high_npl_persistence` (previous half-year 2019-12-31 < break; `not_evaluated true`). `rocet1_supervisory_low`: 0.0417 < 0.072 → red band, severity 2; `leverage_supervisory_low` 0.0433 → severity 1. Families: capital 1, profitability 2 → score 3, **level amber**.
**F** — `alert_id 36883`, amber, score 3.0. **G** — `alert_detail(36883, profile=28a28fa0…)`: `"level":"amber","score":3.0,"reason":"family_score:capital,profitability"`; rule `high_npl_persistence`: `input_value 0.018722954046489042, threshold 0.05, triggered false, not_evaluated true, input_flags ["series_break"]` (the UI shows `false` for the status column of an evaluated=false rule, see F6).

---

## 3. Overlaps — same bank, period and item in more than one `dataset_version`

* **Rule (code):** `load_executor.py:309-320` — a new import that contains a (year, quarter) already loaded **deactivates** the old version (`is_active=false`) and creates `version_no+1`; the old version and its facts stay in the database. `panel.py:163-166` and `fetch_active_panel` (`alert_repository.py:11-14`) read `WHERE v.is_active` only, so the **latest loaded import** feeds `panel_row`.
* **In prod this never happened:** `SELECT year,quarter,count(*) FROM dataset_version GROUP BY 1,2 HAVING count(*)>1` returns 0 rows; 0 inactive versions; each edition delivers different periods (checked in the 12 raw `tr_oth.csv`: 2015: 201412/201506 … 2025: 202409–202506, no period twice). So there is **no concrete example with two values** in this database; the rule above is untested on real data. (`tests/integration/test_load.py::test_a_new_import_for_the_same_period_deactivates_the_old_version` covers it on synthetic data.)
* **Closest real overlap — the same institution under two LEIs/bank_ids** (crosswalk): Crédit Agricole is bank 54 (`969500TJ5KRTCJQWXH05`, 2014-12, 2015-06) and bank 120 (`FR969500TJ5KRTCJQWXH`, 2015-12 …). Periods do not overlap, so no double count; CET1 0.1262 (2015-06, bank 54) → 0.1352 (2015-12, bank 120). `bank_crosswalk.yaml` links them (`credit_agricole_group`, approved), but only the panel growth features use the link (`panel.py:349-407`); the rules key by `bank_id` (`PanelIndex.by_key`, `rule_evaluation.py:18-31`), so for bank 120 at 2015-12 `cet1_yoy_drop`/persistence have no prior row (F7).
* **Within one version** the capital items cannot repeat: 0 duplicate (version, bank, item) rows for the eight items used (unique fact key, migration 004).

---

## 4. Findings (nothing was fixed)

**Defects / regressions**

* **F1 — `build_panel` is broken since the R-3 follow-up.** `app/core/panel.py:154` is `specialist_leis = specialist_leis(Path(dictionary_root))`: assigning a local with the same name as the imported function raises `UnboundLocalError: cannot access local variable 'specialist_leis'` (reproduced: `build_panel(None)`). `python -m scripts.data.build_reference panel` and the panel rebuild fail; the unit tests do not call `build_panel`. The stored `panel_row` (built before) is unaffected. One-line fix: rename the local variable.
* **F2 — API/UI show the wrong default profile and wrong version labels.** `_resolve_profile` (`alert_queries.py:36-42`) takes the newest-created sha of the name `eu_eba`: that is `5a1ec1f4…` (v1.0, created 13:30) and not the frozen `28a28fa0…` (v1.1, 12:05). `alert_profiles` (l.76-92) labels **every** sha with `version/frozen` of the *current* file of that name, so all four shas are listed as "1.1 · frozen" (checked: first entry `5a1ec1f4…` → `version "1.1"`, `frozen true`). The UI default `latestEbaProfile` (`AlertsPages.tsx:13`) sorts by version string, all equal → keeps API order → also `5a1ec1f4…`. The overview/heatmap/bank tab therefore show v1.0 results labelled v1.1 unless the user picks a sha. The thesis comparator sha in `config/ml.yaml` is `28a28fa0…`.

**Silent defaults / dropped or ignored data**

* **F3 — YAML fields that look like configuration but are ignored by the evaluator:** `severity` (`amber`/`red`), `weight`, `consecutive_periods` (always exactly 2 half-years, `_previous_half_year`), composite `cutoffs`/`weights_from`, `status: verified|to_verify` (all rules, including the many `to_verify`, are evaluated the same). Severity is derived from rule **ids** (`_regulatory_min`, `cet1_buffer_warning`, `leverage_supervisory_low`) in `rule_severity`.
* **F4 — Two dashboard-band rules fire for most banks.** `leverage_supervisory_low` (amber 5–8 %, median leverage ratio 6.2 %, 27 % of rows < 5 %) is triggered in 3,058 of 4,097 evaluated rows; `rocet1_supervisory_low` in 2,712 of 4,013. Sum of two severity-1 families = 2 = amber: 1,053 alerts are amber for exactly `capital + profitability`. Result: 54 % amber, 26 % green; no large bank in the check is green. The leverage rule is red-banded but forced to severity 1.
* **F5 — Missing CET1 is not an alert-blocker.** 8 panel rows have no capital ratios; 3 are `not_evaluated`, **5 are `green`** because other families evaluate to 0 (silent default: a bank without a CET1 observation can be green).
* **F6 — Trend/persistence rules report the level as `input_value`.** `rule_result` (`alert_level.py:16-24`) stores `row[feature]`, not the change tested: `cet1_yoy_drop` shows `0.0817042838` with threshold `0.02`, although the tested quantity is −0.0383. The UI table ("Input" vs "Threshold") is misleading. Also `triggered=false` is shown for rules with `not_evaluated=true` and the UI "Status" column prints `triggered`.
* **F7 — Crosswalk is applied to the panel growth features only.** Rules use `bank_id`; split identities (e.g. banks 54 → 120, LEI changes in `bank_crosswalk.yaml`, 15 approved groups, 27 banks with `previous_leis`) lose their prior row in trend/persistence rules and in the relative cross-section; the 7 proposed (unapproved) groups are ignored.
* **F8 — NPL series-break flag is not on the first post-break row** (2020-06-30 has none; earlier rows have `series_break`). The values are not rescaled: the ING NPL steps from 0.0142 (2019-12, "Non Performing", code 2, edition 2020S) to 0.0187 (2020-06, edition 2020A) with the same numerator code, and the 2020A edition adds sub-codes (21, 22, 23) that are correctly excluded only because the match is exact on the label.
* **F9 — Outlier/implausible handling is flag-only.** 40 rows have `cet1_ratio` > 1 (Kommuninvest, 1.01–5.30 = 101–530 %; all `not_evaluated` because specialist), 16 rows have NPL > 0.5 (MPS 2014-2016 included, 0.33); none is dropped or capped. MPS NPL 0.3276 is a real reported ratio flagged `outlier` and `series_break` but evaluated normally.
* **F10 — `n_quarters` inconsistent with the quarter in 63 profit facts** (e.g. quarter 2 with `n_quarters` 4 or 3; quarter 4 with 1–3). `annualise_profit` trusts `n_quarters` (`panel.py:74-80`), so RoCET1 for those rows is scaled by the reported, not the calendar, count. `fin_end_year` equal to the string `"0"` is treated as present (no `fiscal_year_assumed`).
* **F11 — Row selection quirks.** `total_loans` keeps only rows where portfolio/country/rank/exposure/status are `0` (`panel.py:281-282`), so a bank reporting the total only under a different key yields `npl_ratio NULL` (372 NULLs; flag `invalid_denominator`); `_first(..., 3)` has no ORDER BY (harmless with the unique key); `fact_sov` is aggregated by `sum(amount)` per country before use.

**Duplicated logic**

* **F12 —** R0/R1 breach checks exist in `eba_rules/domain/levels.py` and, as alert rules, in the profile (`cet1_regulatory_min` 4.5 %, `total_capital_regulatory_min` 8 %, `cet1_buffer_warning` 7 %) with different levels from `regulatory_levels.yaml` (7 / 8.5 / 10.5 %); an `r0_alert` therefore does not imply a profile red. Specialist detection also exists twice: the flag written by `panel.py` and `specialist_leis()` used by the API; and `build_reference` re-reads the YAML (`app/core/specialists.py` is now the single reader, but panel and API still use it independently).
* **F13 —** `eba_processing/application/session.py:read_session` is a second read-session implementation (different return contract).

**Consistency checks that passed**

* Recomputed vs stored: CET1/Tier 1/total capital/leverage ratios: 0 of 4,367 differ by > 0.1 pp from the fact (they are copied); leverage reported vs Tier 1/exposure: 0 of 3,887 differ > 0.1 pp; NPL recomputed independently from `fact_cre` + decoded dimensions: 0 of 4,367 differ (max difference 0); RoCET1 recomputed: 0 of 4,013 differ > 0.1 pp.
* Rows without alerts / alerts without rows: 0 / 0 (4,367 each, 4 profile shas). Banks with facts but no panel row: 0.
* Golden check of R-3 (in-memory recomputation of the v1.1 alerts equals the stored rows) holds for all 4,367 rows.
