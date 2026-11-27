# Current Project State

## Status
Stage R-1 complete (2026-11-25): structural refactor. `app/` = API, worker, services, domain; all terminal commands in `scripts/` (see `scripts/README.md`); thesis hypotheses in `scripts/hypotheses/` (`python -m scripts.hypotheses.main --run <dir> [--quick]`). `python -m app` only has `serve` and `worker`. Behaviour unchanged: golden (a) hypotheses on T3_primary identical; golden (b) retrain in `data/ml/R1_golden` is verified with `python -m scripts.ml.compare_runs data/ml/T3_primary data/ml/R1_golden` (log: R1 background run).
Previous: T-4c (test suite cannot touch prod; DATABASE_URL locked to eba_test). 110 unit tests pass.

## AUD-4
Missing-value audit (read-only): leverage 2015-12/2016-06 absent from the 2016 edition files; yoy 2020-06…2021-03 NULL by the series-break guard in `core/panel.py:403` (median −9 % across the break); 2016-12 and 2025-03 gaps are source gaps. See `docs/audit/AUD-4_missing_gaps.md`. AUD-4b done: `loan_series_break` key in `config/ml.yaml` (read by `core/panel.py:loan_series_break`, required; panel build roots need `ml.yaml`); ROE sets `numerator_missing` / `denominator_missing`. Values identical (eba_test check). Prod panel not rebuilt (flags change on next rebuild).

## AUD-2
Hooks (`core/hooks.py`) run after `build_panel`: eba_rules re-evaluates, eba_ml queues score jobs. One panel reader `core/panel_reader.py:load_panel` (ML, rules, public analysis). Alerts upserted (ids kept). Open defect (preserved): `load_executor._load` applies the exclusions of the last data file to all files, so owner decisions of earlier files (BNG, 2020S tr_cre) are logged but not applied. See `docs/audit/data_flow.md`, `AUD-1b_call_flow.md`.

## AUD-1-fix
Alert API default = active profile (module.yaml), labels by sha; F5/F6 in eba_rules; v1.1 alerts rewritten in prod 2026-11-25. Open: no job/hook triggers `evaluate_rules` after a panel rebuild (run `build_reference rules`). Details: `docs/audit/AUD-1-fix.md`, `AUD-1b_call_flow.md`.

## R-3 (rule engine module)
`app/modules/eba_rules/` owns profiles, R0/R1, alert evaluation and the alert API; import only `eba_rules.public`. Config in its `config/` (module.yaml, profiles/, regulatory_levels.yaml); R0 levels and R1 margin grid no longer in `config/ml.yaml`. Frozen profile verified by sha256 at load. Boundary tests: `tests/unit/architecture/test_rules_module_boundary.py`.

## R-1 layout
- `scripts/hypotheses/` main, h1a, h1b, h2, h3, h5, stats, report, context; settings in `config/ml.yaml: hypotheses`.
- `scripts/ml/` train_thesis, sensitivity, compare_runs, r1_margin_grid, update_model_cards, smote_comparison (hook `fold_diagnostic` of `train()`), event_evaluation, evaluate_rules.
- `scripts/data/` init_db, export_openapi, import_data, reset_data, build_reference, smoke(+smoke_sample), preflight, audit_files, count_events, download_eba, ingest_cli, processing_cli. `scripts/figures/` generate, figures. `scripts/common.py` shared helpers.
- Rule: scripts import app, app never imports scripts (`tests/unit/architecture/test_scripts_dependency.py`).
- Known unrelated: `tests/integration` cannot be collected as one directory (conftest name clash, `helpers` path); `test_migrations.py` has 2 stale migration-list assertions (013/014).

## Verified environment
- Branch: `fix/bugs`
- Python: 3.12
- Backend: FastAPI + PostgreSQL
- Registered modules: `eba_ingest`, `eba_processing`,
  `eba_public_analysis`, `eba_ml`

## Current work
- T-4 complete: thesis-T3-primary experiment (id=3) registered, 3 models (LR=champion, RF/XGB=validated), all protected.
- Old stage5c models (T5): all validated with superseded note.
- score_panel last run: 2502 rows scored at operating_point_f2 (threshold=0.4916), 14 R0-breach rows.
- DB migration 013 applied: threshold constraint updated to operating_point_f2 / r0_breach.

## Active files (T-4c additions)
- `tests/conftest.py` — pytest_configure: sets DATABASE_URL=TEST_DATABASE_URL unconditionally; aborts if TEST_DATABASE_URL missing/not eba_test
- `tests/unit/test_storage_hygiene.py` — added test_no_test_module_reads_database_url_directly; fails on direct os.environ["DATABASE_URL"] in any test file

## Active files (T-4b additions)
- `tests/integration/conftest.py` — pytest_configure guard: aborts session if TEST_DATABASE_URL DB != eba_test (defense-in-depth)
- `tests/integration/test_ml_shap.py` — both tests now use DATABASE_URL (locked to eba_test); model card test skips if thesis models not seeded in test DB
- `app/core/database/migrations/core/014_ml_top10pct_threshold.sql` — adds top_10pct_per_period to CHECK; backfills migration_013_delete audit
- `app/modules/eba_ml/domain/constants.py` — THRESHOLDS now includes top_10pct_per_period
- `config/ml.yaml` — top_alert_share: 0.10
- `app/modules/eba_ml/application/worker_handlers.py` — _score: second pass inserts top_10pct_per_period rows per period
- `app/modules/eba_ml/application/service.py` — options() exposes top_alert_share; list_predictions accepts threshold_setting param
- `app/modules/eba_ml/presentation/api.py` — response_model on all 7 ML GET endpoints; threshold_setting param on /predictions
- `docs/openapi.yaml` — regenerated; all ML GET responses now have typed schemas (POST/DELETE remain {})

## Active files in eba_ml (T-4/T-7 additions)
- `app/modules/eba_ml/domain/constants.py` — THRESHOLDS=("operating_point_f2",), LABEL_OPTIONS, TAIL_QUANTILES
- `app/modules/eba_ml/application/registry.py` — import_t3_primary_experiment(); update_t3_shap_model_cards(); _global_oof_shap()
- `app/modules/eba_ml/application/worker_handlers.py` — _score: R0 filter, LinearExplainer with stored background, {"feature","value","shap"} payload
- `app/core/database/migrations/core/013_ml_operating_point.sql` — clears stale predictions, updates CHECK constraint
- `docs/openapi.yaml` — regenerated with label/tail_quantile fields in ExperimentRequest
- `tests/unit/test_ml_score_shap.py` — 2 unit tests: _global_oof_shap structure + LR determinism
- `tests/integration/test_ml_shap.py` — 2 integration tests: model card families match H5; reproducible SHAP

## Active files in eba_ml (T-2 additions)
- `app/modules/eba_ml/domain/labels.py` — E1/E2/E3/E2_or_E3 label construction, tail thresholds
- `app/modules/eba_ml/domain/rules.py` — R0/R1 alert, choose_r1_margin
- `app/modules/eba_ml/domain/operating_point.py` — F2-maximising threshold, frozen on OOF
- `config/ml.yaml` — r0_levels, label, tail_quantile, margins grid, operating_point
- `app/modules/eba_ml/application/training/train.py` — full orchestrator with build_labels
- `app/modules/eba_ml/application/training/assembly.py` — extended result dict
- `app/modules/eba_ml/application/training/final_test.py` — returns test_predictions
- `app/modules/eba_ml/application/worker_handlers.py` — _train re-enabled
- `docs/design/thesis_alignment.md` — key design decisions
- `tests/unit/test_ml_labels.py` — 12 new tests including T-0 reproduction

## Deleted in T-1
- `app/modules/eba_ml/domain/thresholds.py`
- `app/modules/eba_ml/domain/lead_time.py`
- `app/modules/eba_ml/application/pipeline.py` (deprecated shim)
- `app/modules/eba_ml/application/training/comparators.py`

## Test structure
- `tests/unit/` — 95 tests, no DB; runs in CI.
- `tests/integration/` — test_ml_e2e.py skips if eba_test is empty.
- `tests/conftest.py` — shared fixtures (`db`, `database_url`, `write_csv`).

## Important constraints
- Keep `.github/prompts/prompt.txt` as the single task prompt.
- Never expose `.env` secrets.
- `TEST_DATABASE_URL` must point only to a disposable test database.
- Test setup drops and recreates `public` and `staging`.
- Do not commit or push unless explicitly requested.

## Verification
- 111 unit tests pass: `pytest tests/unit/`
- GitHub Actions runs `pytest tests/unit/ tests/integration/ -v`.

## Bugs fixed (T-2c → T-2e)
- `io.py:write_json`: `os.chmod(tmp, 0o644)` before rename — mkstemp created 600 files
- `smote.py:34`: guard `if n_pos < 6: return None` was already in place (prior fix)
- `h5.py` (T-2e): `get_feature_names_out()` per fold replaces `[:, :n_base]` slicing — `SimpleImputer` drops all-NaN columns from output entirely (confirmed by unit test); positional slicing misaligned SHAP for LR. Indicator columns dropped from family sums.

## Key T-2e/T-2f findings
- LR folds 1–3: 0/1/1 non-zero coefs → near-constant predictions → ROC-AUC ≈ 0.50 explained
- Final LR: 3 coefs (cet1_ratio +0.349, total_capital_ratio +0.049, npl_ratio +0.208)
- H5 after fix: Asset_quality #1 > Capital #2 > Earnings #3 (unchanged ranking)
- R1 alert share at 20pp margin: 98.2% → degenerate; 5 missed positives all have headroom > 20pp
- Fixed-share sensitivity: ML recall 0.282 vs R1 0.026 at 10% share, CI [+0.056, +0.487]
- E2_rel (forward CET1 rel ≤ −12.80%): 105 rows, 61 banks, mean CET1 21.3%
- Reproducibility: `random_state=SEED` added to LR in model_factory; hypotheses.json now byte-identical

## T-7 summary (SHAP in the app)
- `update_t3_shap_model_cards()` computes OOF SHAP fold-by-fold (matches H5 primary exactly, bit-identical).
- LR background (all training rows, imputer+scaler transformed) stored in ArtifactStore; sha in model_card as `shap_background_sha256`.
- _score uses LinearExplainer with stored background for LR; TreeExplainer for RF/XGB.
- Payload format: `[{"feature": base_name, "value": raw_float_or_null, "shap": signed_float}]` (positive = raises risk).
- Model card `shap_note` explains E2_or_E3 vs E3-only sign difference (thesis §3.4).
- Global SHAP families verified bit-identical to T3_primary/hypotheses.json H5.primary.

## Next step
T-4b complete. All 5 items done.
