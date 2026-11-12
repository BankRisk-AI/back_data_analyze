# Progress

## Done

- Stage 0: make the project installable and testable (2026-11-12)
- Stage 1a: set-based staging-to-fact promotion (2026-11-12); measured
  benchmark improved from about 34.1s to about 4.8s for 100,000 rows on the local
  PostgreSQL setup (promotion-only measurement)
- Stage 1b: fact uniqueness and data-safety guards (2026-11-12)

## Next step

- Stage 1c: job attempt limit; remove duplicate endpoints `/api/periods` and
  `/api/versions/...` from `eba_processing`; rename job kind `validate` ->
  `stage` with a migration updating existing job rows.

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
