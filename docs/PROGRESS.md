# Progress

## Done

- Stage 4e (2026-11-21): approved three continuity crosswalk groups
  (Bank of Cyprus, Bpifrance, and Magyar Bankholding), added predecessor-LEI
  continuity handling to loads, froze EU/EBA profile v1.1
  (`28a28fa0...e0089f7e40`) with calendar persistence, rebuilt production
  panel rows, evaluated v1.1, regenerated F1-F6 deterministically, and
  exported `data/banks.csv`.
- Stage 4e-data (2026-11-21): approved the remaining owner-directed
  crosswalks, linked two prefix-shifted provisional identifiers, normalized
  country codes, added wind-down specialists, and rebuilt production outputs.
- Stage 4d (2026-11-21): evaluated the nine-event primary set and eleven-event
  sensitivity set against frozen v1.1; primary red hit rate was 100.0%
  (Wilson 95% CI 70.1--100.0%) and amber-or-red hit rate was 100.0%
  (CI 70.1--100.0%), with 12-month median lead time. See
  [rule evaluation](design/rule_evaluation.md).
- Stage 4d-baseline (2026-11-21): added fixed dashboard/random baselines,
  relative usefulness, uncensored lead times, excluded-bank sensitivity,
  NordLB diagnostics, and deterministic F7 hit-rate/false-alarm figure.
- Stage 4d-fix (2026-11-21): corrected Sarlin relative usefulness, event-window
  prevalence, noise-to-signal ratios, and profile-version-specific denominators.
  Stage 4 is closed. Next = Stage 5a ML design (design only).

- Stage 0: make the project installable and testable (2026-11-12)
- Stage 1a: set-based staging-to-fact promotion (2026-11-12); measured
  benchmark improved from about 34.1s to about 4.8s for 100,000 rows on the local
  PostgreSQL setup (promotion-only measurement)
- Stage 1b: fact uniqueness and data-safety guards (2026-11-12)
- Stage 1c: bounded worker retries, give-up handling, job-kind migration, and
  removal of duplicate processing public endpoints (2026-11-12)
- Stage 1d: real-file pipeline performance limits (2026-11-12); stage 9.24s,
  validation 13.10s, load 26.48s

## Stage 2a

- Done (2026-11-14): real-file design analysis for item mappings, column drift,
  bank metadata, and `fact_sov`; see
  [data inventory](design/data_inventory.md),
  [item dictionary](design/item_dictionary.md),
  [column drift](design/column_drift.md),
  [bank metadata](design/bank_metadata.md), and
  [fact_sov](design/fact_sov.md).

## Stage 2b

- Done (2026-11-14): optional-column ingestion, source spreadsheet locations,
  generic bank-list discovery, and real-edition staging/validation; see
  [results](design/stage2b_results.md).

## Stage 2b-fix

- Done (2026-11-14): 2018/2019 grouped-thousands amounts are normalised during
  staging; exact duplicates are informational and deduplicated at load time;
  see [results](design/stage2b_results.md).

## Stage 2b-decision

- Done (2026-11-14): applied the two final 2020S owner exclusions, validated
  with zero errors, and loaded the edition successfully. Four conflicting rows
  were excluded and 127 distinct fact banks were loaded; see
  [results](design/stage2b_results.md).

### Data decisions

- `2020s-2020501-bng-exclude`: exclude both conflicting 2020501 values for
  BNG Bank N.V.
- `2020s-2020502-bng-exclude`: exclude both conflicting 2020502 values for
  BNG Bank N.V.
- Source of truth: [config/data_decisions.yaml](../config/data_decisions.yaml).

## Stage 2c

- Done (2026-11-14): promoted `tr_sov` into `fact_sov` with aggregate exclusion,
  source locations, nullable identity `country + accounting_portfolio +
  maturity`, and a `NULLS NOT DISTINCT` unique index. Public analysis now
  supports `sov`; see [results](design/stage2c_results.md).

## Stage 2d

- Done (2026-11-14): built the cross-edition SDD chain in the existing
  `indicator` dictionary, added `indicator_code_map`, and documented coverage,
  Table 3.4 chains, and unresolved gap candidates in
  [the report](design/item_dictionary_report.md). Existing facts were not
  migrated; every edition must be reloaded in Stage 2e.

## Stage 2d-verify

- Done (2026-11-14): fixed dataset derivation for historical SDD rows, reduced
  master indicators from 1,121 to 390, retained 3,126 mappings, isolated
  sovereign template changes, and completed the required TEST reload proof for
  2015, 2016, 2019, and 2025.

## Changes for the React UI

- The ingest worker job kind is now `stage` instead of `validate`; clients
  should read job kinds from `/api/meta`.
- Job responses now include `attempts`.
- The processing-module `/api/periods` and
  `/api/versions/{version_id}/datasets/{dataset}/preview` routes were removed;
  use `/api/public/periods` and `/api/public/versions/{version_id}/datasets/{dataset}/preview`.
- Public analysis now also exposes the additive `sov` and `tr_sov` datasets.
- Alert screens should use the read-only `/api/public/alerts/*` and
  `/api/public/banks/{bank_id}/alerts` endpoints.
- Stage 3d adds `/api/public/report-types`, cascading years and quarters,
  `/api/public/banks` and bank panels, panel cross-sections and feature
  definitions, plus raw `/api/public/indicators/{indicator_id}/series`.

## Next step

- Stage 2 closed (2026-11-15): corrected the 2015 capital-ratio dictionary
  chain, completed the TEST/DEV rehearsal, backed up and reloaded production
  through all 12 editions, and passed checks a–g. See
  [the final report](design/stage2_final_report.md).
- Stage 2e rehearsal (2026-11-15): completed the full twelve-edition rehearsal.
- Stage 2e 2-smoke (2026-11-15): production smoke checks passed.
- Stage 2e 2-preflight (2026-11-15): production preflight checks passed.
- Stage 2e-dev (2026-11-15): DEV full reload completed.
- Stage 2e-prod (2026-11-15): production full reload completed.
- Stage 2e-cleanup (2026-11-15): storage and temporary data cleanup completed.
- Stage 3b (2026-11-15): dimension decoding configurations generated,
  verification checks A--C passed, and the final panel design recorded.
- Stage 3c (2026-11-15): panel builder implemented and production panel
  rebuilt; see [panel statistics](design/panel_stats.md).
- Stage 3c-fix (2026-11-15): calendar-aligned QoQ/YoY growth, configurable
  MAD outlier detection, 2016 NPL continuity proof, extreme-value review, and
  production rebuild completed; see [panel statistics](design/panel_stats.md).
- Stage 3c-fix-2 (2026-11-15): independent calendar-join verification returned
  zero YoY and QoQ mismatches, per-period outliers were restored, leverage
  reporting errors were nulled, and production was rebuilt; see
  [panel statistics](design/panel_stats.md).
- Stage 3d (2026-11-15): completed the loan-definition and specialist checks,
  specialist configuration, and additive public report, bank, panel,
  cross-section, feature, and raw-indicator endpoints.
- Stage 3d-fix (2026-11-15): corrected the 202006 finding to a permanent
  `tr_cre` definition change, found no separate Exposure row to subtract,
  applied `series_break` handling, rebuilt production, and documented the
  evidence in [panel statistics](design/panel_stats.md).
- Stage 3 closed (2026-11-15): panel checks and public analysis contract are
  complete.
- Stage 4a (2026-11-16): rule-engine design drafted in
  [rule_engine.md](design/rule_engine.md), with EU/EBA and BNM profiles and an
  empty event-catalogue format.
- Stage 4b (2026-11-16): migration 011 added the atomic `alert` table,
  profile evaluator and `evaluate_rules` worker kind; EU/EBA alerts were
  evaluated on production. The schema now has 16 logical tables; see
  [rule results](design/rule_results.md).
- Stage 4b-calibrate (2026-11-16): replaced correlated-rule summation with
  fixed family-maximum scoring, preserved the historical 4b profile SHA,
  evaluated the calibrated EU/EBA profile on production, and documented the
  before/after results in [rule results](design/rule_results.md).
- Stage 4b-final (2026-11-16): froze EU/EBA profile v1.0, moved persistence
  into feature families, reduced relative severity, added public-funding
  specialists, rebuilt panel flags, and reevaluated production.
- Stage 4c done (2026-11-16): added read-only public alert profile, summary,
  period, bank timeline, and detail endpoints with old-format compatibility.
- Stage 4c-fix (2026-11-16): fixed profile resolution to use the latest
  evaluated alert SHA from the database, with name/full-SHA/prefix support;
  the previous YAML/path resolution caused production bank timelines to 404.
- Next = Stage 4c-ui (React alert screens), then Stage 4d evaluation once
  `config/events.yaml` is curated.
- Environments: `eba` is production via `DATABASE_URL`, `eba_test` is test via
  `TEST_DATABASE_URL`, and production storage is
  `/var/projects/python/eba_analyst/prod/eba_storage`.

## Backlog

- Stage 3: panel_row (Table 3.4 indicators) + time-series and report->year->quarter endpoints
- Stage 4: configurable rule engine (EU/EBA, BNM) + alert table
- Stage 5: ML + temporal CV + SHAP
- Stage 6: auth, safe public scatter, approve/cancel import, Docker
- Stage 7: BNM pilot

## Decisions

- Local only
- A new import for a quarter deactivates the previous version
- The schema now has 15 tables
- The UI is a separate React repository
