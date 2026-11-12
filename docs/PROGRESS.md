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

## Next step

- Stage 2a: inspect a real `tr_sov` file and design `fact_sov`; no code starts
  before its column list is agreed.

## Breaking changes for the React UI

- The ingest worker job kind is now `stage` instead of `validate`; clients
  should read job kinds from `/api/meta`.
- Job responses now include `attempts`.
- The processing-module `/api/periods` and
  `/api/versions/{version_id}/datasets/{dataset}/preview` routes were removed;
  use `/api/public/periods` and `/api/public/versions/{version_id}/datasets/{dataset}/preview`.

## Backlog

- Stage 2: all EBA editions + fact_sov + item mapping across editions
- Stage 3: panel_row (Table 3.4 indicators) + time-series and report->year->quarter endpoints
- Stage 4: configurable rule engine (EU/EBA, BNM) + alert table
- Stage 5: ML + temporal CV + SHAP
- Stage 6: auth, safe public scatter, approve/cancel import, Docker
- Stage 7: BNM pilot

## Decisions

- Local only
- A new import for a quarter deactivates the previous version
- The schema stays at 13 tables
- The UI is a separate React repository
