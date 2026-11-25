# AUD-1-fix — fixes and investigations from AUD-1

Date: 2026-11-25 · Tests: `pytest` default suite **246 passed, 7 deselected** (after the changes below).

## A1 — F1: name shadowing in `panel.py`

* **Fix:** `app/core/panel.py:154` — the local `specialist_leis = specialist_leis(...)` is now `specialist_banks_leis` (used at l.200).
* **Test:** `tests/integration/test_panel_build.py::test_build_panel_end_to_end` seeds a tiny panel in `eba_test` (2 banks, 2 periods, capital ratios, profit, CET1 amount, loan totals by `perf_status`, a decoded `Perf_status` dimension file, one specialist LEI) and runs `build_panel` twice. It asserts: 4 rows, CET1 copied, NPL = 20/200 = 0.1, RoCET1 annualised with `n_quarters` 4 (Dec) and 2 (Jun), specialist flag on the specialist only, rebuild does not duplicate. **Verified to fail on the old code** (`UnboundLocalError: cannot access local variable 'specialist_leis'`).
* **Why the suite did not catch it:** no test called `build_panel`. `tests/unit/test_panel.py` covers only the pure helpers (`growth_rate`, `hhi`, `annualise_profit`, …), and the R-3 follow-up (moving the specialist reader to `app/core/specialists.py`) only ran those plus the architecture tests. The only call sites of `build_panel` are the script `scripts.data.build_reference panel` and the worker-less CLI, neither covered. The module imported fine (the error is raised at call time), so import/collection tests passed.

## A2 — F2: default profile and labels

* **Behaviour now** (`app/modules/eba_rules/application/alert_queries.py:_resolve_profile`):
  * no `profile` → the **active profile** of `config/module.yaml` (`eu_eba` v1.1 → sha `28a28fa0…`); if its alerts are not in the table → `NotFound` listing what exists (no silent fallback);
  * `profile=eu_eba` (a registered name) → the registered file's sha (v1.1), not the newest created;
  * full sha or ≥8-char prefix → that exact alert set, so v0 (`1296bd8e…`), v0.9 (`794ea5ad…`) and v1.0 (`5a1ec1f4…`) stay selectable;
  * unregistered names fall back to their newest sha.
* **Labels** come from metadata per sha (`profiles.profile_labels`): the registered profile files (name, version, frozen) plus a new `historical_profiles` list in `config/module.yaml` (sha → name/version/frozen for the three profiles whose files no longer exist). `/alerts/profiles` and `/alerts/{id}` (`profile_version`) use it; an unknown sha gets `version: null, frozen: null`. No DB migration was needed (the metadata lives in module config).
* **Checked on prod data:** after the A3 rewrite the API default for `201612` returns, for bank 68, alert 44200 (sha 28a28fa0…, level red); `/alerts/profiles` lists 1.1 frozen, 1.0 frozen, 0 frozen, 0.9 frozen with the right shas; `/alerts/summary` and `/alerts/{id}` report sha 28a28fa0… / `profile_version 1.1`.
* **Tests:** `tests/unit/test_alert_profiles.py` (5 tests: default = active, not newest; name → registered sha; old shas by sha/prefix; ambiguity/unknown; labels by sha; missing active alerts → error).
* **Frontend change needed: none.** `latestEbaProfile` (`AlertsPages.tsx:13`) sorts by version string descending; with correct versions (`1.1` > `1.0` > `0.9` > `0`) it already selects v1.1, and all pages pass `profile.sha` explicitly. Optional hardening: expose an `active` flag in `AlertProfile` (would change `docs/openapi.yaml`) — not done.

## A3 — F5 and F6 and the prod rewrite

* **F5** (`domain/alert_level.py`): `REQUIRED_INPUTS = (cet1_ratio, tier1_ratio, total_capital_ratio)`; a row with any of them missing gets level `not_evaluated`, reason `required_input_missing:<features>`, score `None`.
* **F6** (`domain/rule_evaluation.py:_trend`, `alert_level.py:rule_result`): trend rules store the **tested change** as `input_value` (`None` when not evaluated) and the level in a new field `feature_value`.
* **Profile unchanged:** `eu_eba_v1.1.yaml` byte-identical, sha `28a28fa0…` verified at load.
* **Tests:** `tests/integration/test_rules.py` (helper rows now carry the three required ratios; new tests for never-green and for the trend change); thesis alert fixture `tests/data/eu_eba_v1_1_expected_alerts.json` regenerated (only the missing-input row's reason changed).
* **Diff of the in-memory recomputation against prod (4,367 rows):**

| change | rows |
|---|---|
| level green → not_evaluated | **5** (reason `no_material_family_trigger` → `required_input_missing:cet1_ratio`; score 0.0 → NULL; composite rule not_evaluated) |
| reason text only (already not_evaluated) | 3 (`all_families_not_evaluated` → `required_input_missing:cet1_ratio`) |
| trend rule `input_value` (cet1_yoy_drop, npl_yoy_rise) | 8,293 (change instead of level; plus new `feature_value`) |
| any other rule/family/level/score field | **0** |
| red | 577 → 577 (no red change); amber 2,370 → 2,370 |

* **Prod write** (as authorised, one transaction): `DELETE` + `INSERT` of the 4,367 alerts of sha `28a28fa0…` and one `audit_log` row (`audit_id 79`, action `alert re-evaluation`, entity `alert`, entity_id `28a28fa0f89d`, detail with before/after level counts). Levels before → after: green 1,135 → 1,130, not_evaluated 285 → 290, amber 2,370 → 2,370, red 577 → 577. Table total 17,468 → 17,468 (the other three shas untouched). **Side effect:** the rewritten rows have new `alert_id`s (e.g. MPS 2016-12 was 35466); bookmarked detail URLs of the old ids no longer resolve.

## A4 — F8 (was F10): profit facts where `n_quarters` ≠ quarter

63 profit facts (indicator 2520335), **5 banks only**, all in the editions 2016-2019; every one is a consistent **fiscal-year offset**, not a data error:

| bank | name | pattern |
|---|---|---|
| 79 | Mediobanca | June fiscal year: n_quarters 2 at Dec, 4 at Jun (34 of 36 periods; `fin_end_year` 2 = FY end June) |
| 84 | Bank of Valletta | 1 at Dec / 3 at Jun in 2015-17 (4 periods) |
| 117 | Commbank Europe Ltd | 2 at Dec, 4 at Jun (2 periods; profit 0) |
| 130 | MDB Group Limited | 3 at Dec, 1 at Jun (11 periods; `fin_end_year` 1) |
| 267 | Nationwide Building Society (April fiscal year) | 3 at Dec, 1 at Jun (12 periods) |

`annualise_profit` (`panel.py:74-80`) uses the reported `n_quarters`, which is **right** for fiscal-year banks. "Expected" below is the calendar quarter number (what a calendar-year bank would report); applying it would **under-/over-annualise**:

* RoCET1 used vs recomputed with the calendar quarter: see the table in Appendix A4 (63 rows).
* Impact if the calendar quarter were applied (in-memory evaluation, not applied anywhere): 63 RoCET1 values change; rule severities change on 39 rows; alert levels change on 16 rows (amber→red 3, amber→green 5, green→amber 8). **Conclusion:** the current logic is correct for these rows; no change recommended. Residual issue: for `fin_end_year` NULL (34 of the 63) the code flags `fiscal_year_assumed` although `n_quarters` is present, and `fin_end_year = '0'` (decoded: "2020-12-31", i.e. calendar year) is treated as present.

## A5 — Edition per period

* **Panel (36 periods → edition loaded):** 2014-12, 2015-06→2015 · 2015-12, 2016-06→2016 · 2016-12, 2017-06→2017 · 2017-12, 2018-06→2018 · 2018-09 … 2019-06→2019 · 2019-09, 2019-12→2020S · 2020-03, 2020-06→2020A · 2020-09 … 2021-06→2021 · 2021-09 … 2022-06→2022 · 2022-09 … 2023-06→2023 · 2023-09 … 2024-06→2024 · 2024-09 … 2025-06→2025 (exact list per version in the query `dataset_version ⨝ import_batch`; panel rows per period 105-135).
* **Overlap in the sources:** none. In `eba_data` (originals) and `eba_prepared` the `Period` column of `tr_oth` has disjoint periods per edition (2015: 201412/201506 … 2025: 202409–202506; the `2020` folder holds two sets: `tr_oth.csv` = 201909/201912 → prepared as `2020S`, `tr_oth_2.csv` = 202003/202006 → `2020A`). No period is present in two editions.
* **Code that decides (if it ever happened):** the prepare script `scripts/data/audit_files.py:prepare` (l.240) only renames/hard-links files and **stops** if two files map to the same name (l.252); it does not choose between editions. The loader `load_executor.py:309-320` decides: **latest loaded import wins** (older version deactivated, `version_no+1`); the panel reads `is_active` only. So the rule is "latest published/loaded", not "first published".
* **Examples with two values:** none exist in the data (no overlap), so no pair of differing values can be shown.

## A6 — F3: profile fields the evaluator ignores (proposal only)

Read by the evaluator: `profile`, `rules[].id/type/feature/condition/threshold/bands/percentile/periods/family`. Read **only by the schema validator** (checked, never used in evaluation): `rules[].severity`, `weight`, `source`, `status`, `consecutive_periods`, composite `cutoffs`, `weights_from`. Not read at all: `rules[].note`, `description`, `conversion`, and every key of `defaults` (`composite_logic`, `weights`, `null_input`, `specialist_institution`, `series_break`, `frequency`, `alert_levels`, `sources`) — those behaviours are hard-coded in `alert_level.py`/`rule_evaluation.py`.

**Proposal (not applied):**
1. In `profile_schema.py` keep one list `INERT_KEYS` = the fields above. For a **frozen** profile the loader accepts them and keeps them as inert metadata (the sha must not change).
2. For a **non-frozen** profile (new versions, adjustable copies) the loader **rejects** any key in `INERT_KEYS` (`ValueError: <key> is not used by the evaluator`), so a user cannot believe that editing `severity`, `weight` or `consecutive_periods` changes results.
3. Move the hard-coded behaviours that the YAML claims to configure (`consecutive_periods`, severity of `leverage_supervisory_low`, composite cutoffs) into real fields in a v1.2 profile, and delete the matching hard-coding.

---

## Appendix A4 — the 63 facts

| bank_id | bank | period | edition | n_quarters (reported) | fin_end_year | calendar quarter | RoCET1 used | RoCET1 with calendar quarter |
|---|---|---|---|---|---|---|---|---|
| 79 | Mediobanca - Banca di Credito Finanzia | 2015-12-31 | 2016 | 2 | None | 4 | 0.0887 | 0.0443 |
| 84 | Bank of Valletta Plc | 2015-12-31 | 2016 | 1 | None | 4 | 0.1838 | 0.0459 |
| 117 | Commbank Europe Ltd | 2015-12-31 | 2016 | 2 | None | 4 | 0.0000 | 0.0000 |
| 130 | MDB Group Limited | 2015-12-31 | 2016 | 3 | None | 4 | 0.1507 | 0.1130 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2016-06-30 | 2016 | 4 | None | 2 | 0.0934 | 0.1868 |
| 84 | Bank of Valletta Plc | 2016-06-30 | 2016 | 3 | None | 2 | 0.1893 | 0.2840 |
| 117 | Commbank Europe Ltd | 2016-06-30 | 2016 | 4 | None | 2 | 0.0000 | 0.0000 |
| 130 | MDB Group Limited | 2016-06-30 | 2016 | 1 | None | 2 | 0.0869 | 0.0434 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2016-12-31 | 2017 | 2 | None | 4 | 0.1272 | 0.0636 |
| 84 | Bank of Valletta Plc | 2016-12-31 | 2017 | 1 | None | 4 | 0.1625 | 0.0406 |
| 130 | MDB Group Limited | 2016-12-31 | 2017 | 3 | None | 4 | 0.0785 | 0.0589 |
| 267 | Nationwide Building Society | 2016-12-31 | 2017 | 3 | None | 4 | 0.1091 | 0.0819 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2017-06-30 | 2017 | 4 | None | 2 | 0.1058 | 0.2115 |
| 84 | Bank of Valletta Plc | 2017-06-30 | 2017 | 3 | None | 2 | 0.1522 | 0.2284 |
| 130 | MDB Group Limited | 2017-06-30 | 2017 | 1 | None | 2 | 0.1217 | 0.0609 |
| 267 | Nationwide Building Society | 2017-06-30 | 2017 | 1 | None | 2 | 0.1097 | 0.0548 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2017-12-31 | 2018 | 2 | None | 4 | 0.1423 | 0.0712 |
| 130 | MDB Group Limited | 2017-12-31 | 2018 | 3 | None | 4 | 0.1022 | 0.0767 |
| 267 | Nationwide Building Society | 2017-12-31 | 2018 | 3 | None | 4 | 0.0894 | 0.0671 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2018-06-30 | 2018 | 4 | None | 2 | 0.1286 | 0.2572 |
| 130 | MDB Group Limited | 2018-06-30 | 2018 | 1 | None | 2 | 0.0708 | 0.0354 |
| 267 | Nationwide Building Society | 2018-06-30 | 2018 | 1 | None | 2 | 0.0829 | 0.0414 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2018-09-30 | 2019 | 1 | None | 3 | 0.1505 | 0.0502 |
| 130 | MDB Group Limited | 2018-09-30 | 2019 | 2 | None | 3 | 0.0813 | 0.0542 |
| 267 | Nationwide Building Society | 2018-09-30 | 2019 | 2 | None | 3 | 0.0742 | 0.0494 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2018-12-31 | 2019 | 2 | None | 4 | 0.1375 | 0.0688 |
| 130 | MDB Group Limited | 2018-12-31 | 2019 | 3 | None | 4 | 0.0790 | 0.0593 |
| 267 | Nationwide Building Society | 2018-12-31 | 2019 | 3 | None | 4 | 0.0678 | 0.0508 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2019-03-31 | 2019 | 3 | None | 1 | 0.1290 | 0.3870 |
| 130 | MDB Group Limited | 2019-03-31 | 2019 | 4 | None | 1 | 0.0751 | 0.3003 |
| 267 | Nationwide Building Society | 2019-03-31 | 2019 | 4 | None | 1 | 0.0588 | 0.2352 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2019-06-30 | 2019 | 4 | None | 2 | 0.1266 | 0.2533 |
| 130 | MDB Group Limited | 2019-06-30 | 2019 | 1 | None | 2 | 0.0549 | 0.0274 |
| 267 | Nationwide Building Society | 2019-06-30 | 2019 | 1 | None | 2 | 0.0583 | 0.0292 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2019-09-30 | 2020S | 1 | 2 | 3 | 0.1712 | 0.0571 |
| 130 | MDB Group Limited | 2019-09-30 | 2020S | 2 | 1 | 3 | 0.0607 | 0.0405 |
| 267 | Nationwide Building Society | 2019-09-30 | 2020S | 2 | 1 | 3 | 0.0445 | 0.0297 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2019-12-31 | 2020S | 2 | 2 | 4 | 0.1409 | 0.0704 |
| 267 | Nationwide Building Society | 2019-12-31 | 2020S | 3 | 1 | 4 | 0.0482 | 0.0361 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2020-03-31 | 2020A | 3 | 2 | 1 | 0.1142 | 0.3426 |
| 267 | Nationwide Building Society | 2020-03-31 | 2020A | 4 | 1 | 1 | 0.0342 | 0.1369 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2020-06-30 | 2020A | 4 | 2 | 2 | 0.0777 | 0.1553 |
| 267 | Nationwide Building Society | 2020-06-30 | 2020A | 1 | 1 | 2 | 0.0488 | 0.0244 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2020-09-30 | 2021 | 1 | 2 | 3 | 0.1052 | 0.0351 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2020-12-31 | 2021 | 2 | 2 | 4 | 0.1046 | 0.0523 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2021-03-31 | 2021 | 3 | 2 | 1 | 0.1052 | 0.3157 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2021-06-30 | 2021 | 4 | 2 | 2 | 0.1052 | 0.2105 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2021-09-30 | 2022 | 1 | 2 | 3 | 0.1401 | 0.0467 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2021-12-31 | 2022 | 2 | 2 | 4 | 0.1431 | 0.0715 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2022-03-31 | 2022 | 3 | 2 | 1 | 0.1271 | 0.3812 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2022-06-30 | 2022 | 4 | 2 | 2 | 0.1152 | 0.2305 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2022-09-30 | 2023 | 1 | 2 | 3 | 0.1360 | 0.0453 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2022-12-31 | 2023 | 2 | 2 | 4 | 0.1401 | 0.0701 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2023-03-31 | 2023 | 3 | 2 | 1 | 0.1359 | 0.4076 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2023-06-30 | 2023 | 4 | 2 | 2 | 0.1259 | 0.2519 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2023-09-30 | 2024 | 1 | 2 | 3 | 0.1841 | 0.0614 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2023-12-31 | 2024 | 2 | 2 | 4 | 0.1628 | 0.0814 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2024-03-31 | 2024 | 3 | 2 | 1 | 0.1737 | 0.5210 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2024-06-30 | 2024 | 4 | 2 | 2 | 0.1767 | 0.3535 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2024-09-30 | 2025 | 1 | 2 | 3 | 0.1842 | 0.0614 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2024-12-31 | 2025 | 2 | 2 | 4 | 0.1895 | 0.0947 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2025-03-31 | 2025 | 3 | 2 | 1 | 0.1949 | 0.5846 |
| 79 | Mediobanca - Banca di Credito Finanzia | 2025-06-30 | 2025 | 4 | 2 | 2 | 0.1919 | 0.3838 |
