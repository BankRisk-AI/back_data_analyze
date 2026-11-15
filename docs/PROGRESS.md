# Progress

## Done

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

## Breaking changes for the React UI

- The ingest worker job kind is now `stage` instead of `validate`; clients
  should read job kinds from `/api/meta`.
- Job responses now include `attempts`.
- The processing-module `/api/periods` and
  `/api/versions/{version_id}/datasets/{dataset}/preview` routes were removed;
  use `/api/public/periods` and `/api/public/versions/{version_id}/datasets/{dataset}/preview`.
- Public analysis now also exposes the additive `sov` and `tr_sov` datasets.

## Next step

- Stage 2 closed (2026-11-15): corrected the 2015 capital-ratio dictionary
  chain, completed the TEST/DEV rehearsal, backed up and reloaded production
  through all 12 editions, and passed checks a–g. See
  [the final report](design/stage2_final_report.md).
- Next = Stage 3a: panel_row design only.
- Environments: `eba` is production via `DATABASE_URL`, `eba_test` is test via
  `TEST_DATABASE_URL`, and production storage is
  `/var/projects/python/eba_analyst/prod/eba_storage`.

## Backlog

- Stage 3a: panel_row design — Table 3.4 indicator definitions from the master
  dictionary, NPL via Perf_Status, Stage 2 via ASSETS_Stages, ROE denominator
  options, and sovereign_hhi across the 2019 template change (design only).

- Stage 2: all EBA editions + fact_sov + item mapping across editions
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
