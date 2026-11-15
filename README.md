# EBA Analyst

EBA Data Explorer is a Python 3.12 FastAPI application backed by PostgreSQL.
It preserves uploaded EBA files, validates them in staging, and promotes
validated data atomically into the 15-table Chapter 4 schema.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
python -m app init-db
```

Set `DATABASE_URL` and `EBA_STORAGE` in `.env`. The production application
commands are:

```bash
python -m app serve
python -m app worker
python -m app openapi --out openapi.yaml
```

The CLI targets are `prod` (from `DATABASE_URL` and `EBA_STORAGE`) and `test`
(from `TEST_DATABASE_URL` and `storage_test`). For the complete
prepared-edition load, reset the target with
`python -m app reset-data --target prod --confirm <database-name>` and run
`python -m app import-all --target prod eba_prepared`. Immutable originals use
the configured `EBA_STORAGE`; tests never write inside `eba_prepared`.

Set `EBA_REAL_DIR` to the prepared real-file root when running real-file
integration tests. It must contain edition directories such as
`eba_prepared/2020A/tr_cre.csv`, `tr_oth.csv`, `tr_mrk.csv`, `SDD.xlsx`, and
`TR_Metadata.xlsx`.

Run performance benchmarks explicitly with `pytest -m slow`.

The job flow is upload -> `stage` job (staging) -> POST validation
(`validate_data`) -> POST load (`load`). The worker processes the queued jobs.
Operational checks include `python -m app smoke` and `python -m app preflight`;
the complete production load uses `python -m app import-all --target prod
eba_prepared`.

## Tests

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database, then run:

```bash
.venv/bin/pytest -q
```

The test suite skips when `TEST_DATABASE_URL` is not configured and never uses
the application database for test data.
