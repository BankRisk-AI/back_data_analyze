# Scripts

Everything run from the terminal. `app/` holds the API, worker, services and domain logic only;
the one entry point left there is the server/worker startup:

```
python -m app serve [--reload]      # HTTP API (make dev / make start)
python -m app worker                # job worker (make worker)
```

Dependency direction: `scripts` may import `app`; `app` never imports `scripts`
(enforced by `tests/unit/architecture/test_scripts_dependency.py`).
Run every script from the repository root as a module (`python -m scripts....`).
`--target test|prod` selects `TEST_DATABASE_URL` or `DATABASE_URL`.

## scripts/data - loading and checking the data

| Command | Purpose / when | Example |
|---|---|---|
| `scripts.data.init_db` | Create or upgrade tables (migrations). After a new migration or on a new database. | `python -m scripts.data.init_db --target test` |
| `scripts.data.export_openapi` | Regenerate `docs/openapi.yaml` after an API change (a test fails when stale). | `python -m scripts.data.export_openapi --out docs/openapi.yaml` |
| `scripts.data.import_data` | Stage -> validate -> load prepared editions through the normal pipeline. | `python -m scripts.data.import_data all eba_prepared --target prod` |
| `scripts.data.reset_data` | DESTRUCTIVE: empty application tables, keep schema. Before a full reload. | `python -m scripts.data.reset_data --target test --confirm eba_test` |
| `scripts.data.build_reference` | Build dictionary / dimensions / panel, or evaluate a rule profile. After a load. | `python -m scripts.data.build_reference panel --target prod` |
| `scripts.data.smoke` | Stage 2 rehearsal on a sample, TEST only (wipes it). | `python -m scripts.data.smoke --target test` |
| `scripts.data.preflight` | Report fact collisions of editions without loading. Before a first load. | `python -m scripts.data.preflight all eba_prepared --target test` |
| `scripts.data.audit_files` | Inventory of downloaded EBA files (+ optional prepared copy). | `python -m scripts.data.audit_files eba_data --deep` |
| `scripts.data.count_events` | Read-only event counts per label definition. | `python -m scripts.data.count_events` |
| `scripts.data.download_eba` | Download the EBA transparency databases. | `python -m scripts.data.download_eba --years 2024 --dry-run` |
| `scripts.data.ingest_cli` | Standalone ingest module CLI (load, show, serve, drop-staging). | `python -m scripts.data.ingest_cli show 12` |
| `scripts.data.processing_cli` | Standalone processing CLI (validate an import, print config). | `python -m scripts.data.processing_cli validate 12` |

## scripts/ml - thesis training and diagnostics

| Command | Purpose / when | Example |
|---|---|---|
| `scripts.ml.train_thesis` | Primary thesis run (§3.5): search, OOF, final test, SMOTE comparison. Hours; run with nohup. | `python -m scripts.ml.train_thesis --out data/ml/T3_primary` |
| `scripts.ml.sensitivity` | Sensitivity runs: label E3, or tail quantile 0.975. | `python -m scripts.ml.sensitivity --which q975 --out data/ml/T3_q975` |
| `scripts.ml.compare_runs` | Golden check: two run directories identical (results + hypotheses), exit 1 otherwise. | `python -m scripts.ml.compare_runs data/ml/T3_primary data/ml/R1_golden` |
| `scripts.ml.r1_margin_grid` | R1 margin diagnostic grid on the final test of a run. | `python -m scripts.ml.r1_margin_grid --run data/ml/T3_primary` |
| `scripts.ml.update_model_cards` | One-off, WRITES to the DB: register T3_primary and add SHAP model cards. | `python -m scripts.ml.update_model_cards --target test --register` |
| `scripts.ml.evaluate_rules` | Evaluate a rule profile against the event catalogue. | `python -m scripts.ml.evaluate_rules --profile eu_eba --events config/events.yaml --target prod` |

## scripts/hypotheses - thesis hypotheses (§3.6)

`main.py` is the recipe: load run -> `h1a` -> `h1b` -> `h2` -> `h3` -> `h5` -> `report`;
`stats.py` holds the bank-cluster bootstrap, exact Wilcoxon and Holm; settings are in the
`hypotheses:` section of `config/ml.yaml`. Read-only on the database.

```
python -m scripts.hypotheses.main --run data/ml/T3_primary [--out DIR] [--quick]
```

Writes `hypotheses.json` and `hypotheses.md` (`hypotheses_quick.*` with `--quick`) into `--out`
(default: the run directory).

## scripts/analyse - look at the data

| Command | Purpose | Example |
|---|---|---|
| `scripts.analyse.main --hist …` | Histograms (`draw_graph.py`): `--hist indicator --indicator cet1_ratio` = one indicator over all banks; `--hist bank --bank 68` = every indicator of one bank; `--bins`, `--graph-out file.png`. | `python -m scripts.analyse.main --hist indicator --indicator cet1_ratio --graph-out /tmp/cet1.png` |
| `scripts.analyse.main` | Panel rows from `load_panel` (read-only), counts + first rows, optional CSV. Function `get_panel(bank_id, period, date_from, date_to)` in `panel_data.py`. | `python -m scripts.analyse.main --bank 68 --from 2016-01-01 --to 2017-12-31 --out /tmp/mps.csv` |

## scripts/figures

| Command | Purpose | Example |
|---|---|---|
| `scripts.figures.generate` | Figures F1-F12 for the thesis. | `python -m scripts.figures.generate --target prod --out docs/figures --only F1,F3` |

## Docs tooling

`python scripts/validate_memory.py` checks `docs/memory/` (run by a unit test).
