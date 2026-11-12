# Progress

## Done

- Stage 0: make the project installable and testable (2026-11-12)

## Next step

- Stage 1: set-based load via INSERT...SELECT from staging without fetchall;
  unique key on fact_* via migration 004; load only from validated/approved;
  block DELETE staging while a job is active; job attempt limit; remove
  duplicate endpoints `/api/periods` and `/api/versions/...` from
  `eba_processing`; rename job kind `validate` -> `stage` with migration.

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
