# Tests

All tests use the `eba_test` database only: `tests/conftest.py` aborts the session unless
`TEST_DATABASE_URL` names `eba_test` and redirects `DATABASE_URL` to it.
Test data are synthetic (`tests/ml_synthetic.py`, `tests/csv_support.py`, `tests/processing_helpers.py`);
helper modules have unique names so `tests/` and every subfolder collect as one directory.

## How to run

```
.venv/bin/python -m pytest -q                      # default: fast suite (unit + integration), ~1 min
.venv/bin/python -m pytest -q tests/unit           # no database needed beyond the session guard
.venv/bin/python -m pytest -q tests/integration    # database + worker + API
.venv/bin/python -m pytest -q -m slow              # slow tests (ML end-to-end on a seeded panel)
.venv/bin/python -m pytest -q -m data_processing   # needs the real eba_prepared files
```

`pytest.ini` deselects `slow` and `data_processing` by default.

## Behaviour -> test

| Behaviour | Test |
|---|---|
| Duplicate file refused on import | `integration/test_ingest.py::test_file_already_loaded_is_refused_but_unloaded_is_accepted`, `::test_same_file_twice_in_one_upload_is_refused` |
| New import for the same period deactivates the old version | `integration/test_load.py::test_a_new_import_for_the_same_period_deactivates_the_old_version` |
| Crosswalk (previous LEI) merge | `integration/test_set_based_load.py::test_previous_lei_resolves_without_creating_a_bank_and_blank_values_are_null`; item crosswalk `unit/test_dictionary.py` |
| Dimension decoding of one edition | `unit/test_dimensions.py::test_build_dimensions_decodes_country_and_nace` |
| Tests cannot connect to prod | `unit/test_storage_hygiene.py::test_the_test_session_is_locked_to_the_test_database` (+ `conftest.pytest_configure` guard) |
| App never imports scripts; no CLI in app | `unit/architecture/test_scripts_dependency.py` |
| No test reads DATABASE_URL directly | `unit/test_storage_hygiene.py::test_no_test_module_reads_database_url_directly` |
| Labels are forward-looking (timing) | `unit/test_ml_labels.py::test_forward_four_q_change_requires_future`, `::test_label_not_changed_by_past_value` |
| Runtime leakage guard | `unit/test_ml_synthetic_e2e.py::test_leakage_guard_rejects_a_feature_that_is_the_label` |
| Training is deterministic | `unit/test_ml_synthetic_e2e.py::test_training_is_deterministic_and_complete` |
| Empty splits fail clearly | `unit/test_ml_synthetic_e2e.py::test_training_fails_clearly_when_no_row_can_be_labelled`, `unit/test_ml_empty_fold.py` |
| Protected model cannot be deleted/archived | `integration/test_ml_registry_scoring.py::test_protected_and_champion_models_cannot_be_archived_or_deleted`, `unit/test_ml_module.py` |
| One champion per (label, grid) | `integration/test_ml_registry_scoring.py::test_one_champion_per_label_and_grid_is_enforced_by_the_database` |
| Protected champion replaced -> validated | `integration/test_ml_registry_scoring.py::test_promoting_replaces_the_champion_protected_goes_back_to_validated` |
| Artefact hash verified on load | `unit/test_ml_module.py::test_artifact_store_verifies_sha`, `integration/test_ml_registry_scoring.py::test_a_tampered_artefact_is_refused_on_load` |
| score_panel writes both modes + r0_breach; SHAP reproducible, named by feature | `integration/test_ml_registry_scoring.py::test_score_panel_writes_all_modes_and_r0_breach_rows_with_reproducible_named_shap` |
| Global SHAP model card deterministic | `unit/test_ml_score_shap.py` |
| /api/ml 422, 409, pagination, problem+json | `integration/test_ml_registry_scoring.py::test_api_ml_contract_422_409_pagination_and_problem_json`; `unit/test_openapi.py`; `unit/core/test_errors.py` |
| Hypotheses main end to end (quick, synthetic) | `unit/test_ml_synthetic_e2e.py::test_hypotheses_synthetic_quick`; slow: `integration/test_ml_e2e.py` |
| Bootstrap / Wilcoxon / Holm | `unit/test_hypotheses_stats.py` |
| Migrations (incl. 013, 014) | `integration/core/test_migrations.py` |
| Worker claims, heartbeat, requeue | `integration/core/test_worker_core.py` |
| Rules engine / alerts | `integration/test_rules.py`, `unit/test_alert_profiles.py` |
| Panel indicators | `unit/test_panel.py` |
| Layering (domain free of frameworks, modules independent) | `unit/architecture/test_layering.py` |
| OpenAPI file up to date and valid | `unit/test_openapi.py` |
