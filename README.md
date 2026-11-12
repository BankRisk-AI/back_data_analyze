# EBA Analyst

EBA Data Explorer is a Python 3.12 FastAPI application backed by PostgreSQL.
It preserves uploaded EBA files, validates them in staging, and promotes
validated data atomically into the 13-table Chapter 4 schema.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
python -m app init-db
```

Set `DATABASE_URL` in `.env`. The application commands are:

```bash
python -m app serve
python -m app worker
python -m app openapi --out openapi.yaml
```

The job flow is upload -> `validate` job (staging) -> POST validation
(`validate_data`) -> POST load (`load`). The worker processes the queued jobs.

## Tests

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database, then run:

```bash
.venv/bin/pytest -q
```

The test suite skips when `TEST_DATABASE_URL` is not configured and never uses
the application database for test data.
