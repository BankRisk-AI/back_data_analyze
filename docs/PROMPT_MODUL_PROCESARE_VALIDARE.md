# Prompt: module `eba_processing` (preview, analysis, validation, and later insert into PostgreSQL)

Give this prompt to an AI coding assistant (or use it as the specification for a developer) together with the repository `eba_analyst` (without `.venv`, `storage/` and `.env`), the schema `app/core/database/migrations/core/001_baseline.sql` (your `schema.sql`) and a sample of the original 2020 EBA files. Sections 3, 7 and 8 contain decisions that belong to the project owner: **implement phases A and B first; stop and ask before phases C and D** (the questions are in section 14, each with a default).

---

## 1. Role and objective

You are a senior Python engineer. Add the module **`eba_processing`** to the existing application. It reads the staging tables written by `eba_ingest` and lets a user (a) look at the data (preview, column profile, null analysis, histogram, scatter plot), (b) validate it with a catalogue of rules, (c) later prepare it with a few safe operations and (d) insert it into the final PostgreSQL tables.

The module must work almost independently: its own use cases, its own API methods, its own worker handler, its own tests, its own OpenAPI tags. It must also appear in one shared OpenAPI file that describes the whole application (the existing ingest endpoints included).

## 2. What exists (read it, follow it)

Layout: `app/core` (config, database, worker, and after step 0 api/exceptions/module), `app/shared`, `app/modules/eba_ingest` with the layers `domain`, `application`, `infrastructure`, `presentation`. Conventions to keep:
- `domain` has no database and no web imports; `application` orchestrates; `infrastructure` holds all SQL and file access; `presentation` holds FastAPI schemas and routes.
- Settings come from `app.core.config` (`DATABASE_URL` in `.env`, `EBA_SCHEMA`, `EBA_STORAGE`, `EBA_MAX_MB`). Connections come from `app.core.database.connect(schema)`.
- Long operations are jobs in the `job` table (`status`: pending, processing, completed, failed; `progress`, `message`, `heartbeat`), claimed by `app.core.worker.Worker` with `FOR UPDATE SKIP LOCKED`; each module registers handlers in the `JobHandlerRegistry`.
- Errors are `application/problem+json` (RFC 9457), with a stable `type` (`duplicate-file`, `file-too-large`, `unreadable-file`, ...).
- The database has the 13-table schema; **this module adds no table in phases A and B** (the validation report is stored in `decision_log`, step `validation_report`).
- The contract with ingest is only this: **one table per data file, `staging.f<file_id>`, every column `text`, lower-case names** (`lei_code, nsa, period, item, label, amount, footnote` plus the dimension columns of the file), empty cells are NULL or empty text; plus the lineage tables `import_batch`, `source_file`, `job`, `decision_log`. The module must not import anything from `app.modules.eba_ingest`.

## 3. Step 0: stabilise the base first (small, each with a test)

These problems were found while reading the code; the new module depends on them. Fix them in this order and keep the existing 25 tests green.

1. `main.py` contains a pasted shell command (`cat > app/core/database/schema_manager.py <<'PY' ...`), not Python. Replace it with the ASGI entry point (`from app.main import app_from_env; app = app_from_env()`).
2. `requirements.txt` lacks `python-dotenv` (imported by `settings.py` and `conftest.py`) and `pyyaml` (needed to write `docs/openapi.yaml`).
3. Rename the package `infrastructure/stanging` to `staging`.
4. `application/ingest_service.py` (313 lines) mixes upload, enqueue, content inspection, staging, period report, queries and schema initialisation, and `enqueue_import` repeats the store, duplicate-check and register code of `ingest`. Split it: `upload_service` (store, check, register, enqueue), `staging_service` (inspect, stage, report), `queries` (list, get, show, drop) and move all SQL to `infrastructure/database/repositories.py` (functions that take a cursor). The worker must not call `ingest()` with private `_existing_*` arguments and must not hash the stored files again: give it `process_import(import_id)` that reads the registered files. Keep `ingest()` as the synchronous all-or-nothing path.
5. Shared pieces move to `app/core` and `app/shared`: the problem+json handlers and a base `FastAPI` factory (`app/core/api`), a base `AppError(kind, status, title)` that module exceptions extend, a `ModuleSpec` (name, router factory, worker handlers, migrations folder, OpenAPI tags) and a registry `app/modules/__init__.py: MODULES`. Add `app/main.py` that builds one app with the routers of all modules (the `architecture.txt` target), while every module keeps its own `create_app` so it can run alone.
6. Replace the inline `ALTER TABLE` statements in `init_db` with numbered SQL migrations (`schema_migrations` table, advisory lock, adoption of a database created before migrations existed). Migration `002` must: keep the job columns, add `heartbeat_at`, drop `job_kind_check` (modules define their own kinds) and be idempotent.
7. Worker: refresh `heartbeat_at` from a background thread while a handler runs and requeue by `COALESCE(heartbeat_at, started_at)` (today a job longer than `stale_after`, 900 s, is requeued while still running); run the recovery periodically, not only at start; pass the worker's schema to handlers (`Job.schema`) because `app/worker.py` currently builds `Worker` without `get_schema()` while the handlers use it.
8. Progress: `worker_handler` reports a fixed 50. Report real stages (for example 5 + 90 * file_index / file_count).
9. `get_import` returns `recognised: false` for files not inspected yet. Return `null` (OpenAPI `bool | null`) until the worker has inspected them.
10. **Latent SQL bug** (`_period_report`, and any similar code): `period ~ '^[0-9]{6}$' AND substr(period,5,2)::int ...` does not protect the cast, because PostgreSQL may evaluate the operands in any order and fail with `invalid input syntax for type integer`. Write guarded casts as `CASE WHEN <regex> THEN <cast> ... END`, and add a test with periods `2020`, `202013`, `` (empty).

**Rule that applies to every handler (found as a real deadlock):** a handler must not `UPDATE` the `job` row inside its own transaction, and must call the progress reporter **before** any statement that locks that row. The reporter uses other connections and would wait for the lock held by the handler while the handler waits for the reporter.

## 4. Design of the module

```
app/modules/eba_processing/
  module.py                      ModuleSpec (router, handlers, tags)
  domain/                        constants (limits, roles), models (Filters, ValidationIssue ...), rules (catalogue), binning (pure)
  application/                   datasets, analytics, validation, worker_handler, session (read-only session with timeout)
  infrastructure/                datasets.py (staging table lookup, filters to safe SQL), analytics.py, validation_sql.py, jobs.py
  presentation/api/              schemas.py (pydantic), router.py (build_router), api.py (standalone create_app)
```
Rules: the module imports only `app.core` and `app.shared`; an automated test fails on any import of another module, of a higher layer from a lower one (`domain` -> nothing, `infrastructure` -> `domain` only, `application` -> `domain` and `infrastructure`) or of `app.modules` from `core` or `shared`. Put `staging_table(file_id)` and the aggregate-bucket predicate in `app/shared`, because ingest and processing both need them.

Column roles (domain): `lei_code, nsa, period, item` = key; `label` = label; `amount` = measure; `footnote` = annotation; every other column = dimension.

## 5. Phase A: read-only analysis (synchronous, fast)

All queries run in a read-only session with `SET LOCAL statement_timeout = 30s`; a timeout becomes a `504 query-too-slow` problem. Filters (`period` as `YYYYMM`, `lei`, `item`, `dim=column:value` repeatable, `exclude_aggregate`) combine with AND. **No client text is ever concatenated into SQL:** identifiers are checked against the real columns of the staging table (unknown column: `422 invalid-parameter` listing the valid ones) and values are bound parameters. The amount is read through a guarded cast: `CASE WHEN amount ~ '^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$' THEN amount::double precision END`.

| Method and path | Purpose and response |
|---|---|
| `GET /api/processing/config` | limits (page size 50/1000, bins 30/200, scatter points 2000/5000, top values 5/20, timeout), enumerations (aggregations, scales, clips, severities, column roles) and the rule catalogue |
| `GET /api/imports/{import_id}/datasets` | staged data files of an import: `file_id`, `file_name`, `file_type`, `rows`, `columns[{name, role, position}]`, `periods[{period, year, quarter, banks, rows}]` (aggregate bucket excluded from banks and rows); empty list if staging was dropped; 404 for an unknown import |
| `GET /api/datasets/{file_id}` | the same for one file; 404 `dataset-not-found` if the file or its staging table does not exist |
| `GET /api/datasets/{file_id}/preview` | `page`, `page_size`, `sort`, `order`, filters; sort by `amount` is numeric, empty values last; response `columns`, `rows` (objects, empty = null), `total`, `pages`, `elapsed_ms` |
| `GET /api/datasets/{file_id}/items` | item catalogue for the selectors: `item`, `label`, `rows`, `banks`, `null_amount`, `non_numeric_amount`, `labels` (distinct); search `q` (`%` and `_` are literal), paging |
| `GET /api/datasets/{file_id}/profile` | per column: `non_null`, `nulls` (NULL, empty or blank), `null_pct`, `distinct`, `min_length`, `max_length`, `top_values` (only for columns with at most 200 distinct values); amount summary (`numeric`, `non_numeric`, `min`, `max`, `mean`); options `distinct`, `top` |
| `GET /api/datasets/{file_id}/nulls` | `by=period`: matrix of null counts and percentages per period and column (`columns` optional); `by=item`: items with the highest share of empty or non-numeric amounts |
| `GET /api/datasets/{file_id}/histogram` | `item` (required), `period`, `bins`, `scale=linear|log`, `clip=none|p01-p99|iqr`, `dim`: `bins[{x0, x1, count}]` (log bins have equal ratios; the maximum belongs to the last bin), `stats` (min, p01, p25, median, p75, p99, max, mean, std), `n`, `nulls`, `non_numeric`, `non_positive`, `outside` (counted but not drawn), `note`; a constant sample gives one bin; no numeric value gives empty bins |
| `GET /api/datasets/{file_id}/scatter` | `x_item`, `x_period`, `y_item`, `y_period`, `agg=single|sum|mean|min|max`, `x_dim`, `y_dim`, `max_points`: one value per bank (LEI), `points[{lei, country, x, y}]`, `n_pairs` (always the full number), `sampled` (reproducible sample ordered by `md5(lei)` when n_pairs > max_points), `stats{pearson, spearman}` computed on all pairs (Spearman with average ranks for ties). `agg=single` must refuse an item with several rows per bank with `422` explaining the dimension columns |

Use cases for the interface: a histogram for one item and period; a scatter of two items in one period (relation between indicators) or of one item in two periods (change); null matrix by period; items with most nulls.

## 6. Phase B: validation (a job, because it scans the whole file)

- `POST /api/imports/{import_id}/validation` -> `202 {job_id, status, created}`; idempotent while a validation is pending or processing (`created: false`); `409 no-staging` if there are no staging tables. Job kind `validate_data` (the existing ingest kind `validate` is about staging; consider renaming it to `stage_files` with a migration).
- `GET /api/imports/{import_id}/validation` -> `{import_id, import_status, job, report}` (`job` = latest validation job or null; `report` = latest finished report or null).
- The handler runs every rule on every staged data file, reports progress per rule, stores the report JSON in `decision_log` (step `validation_report`) and, **in the same transaction**, moves the import `uploaded` -> `validated` when no rule of severity `error` failed, or `validated` -> `uploaded` when one did; it never touches any other status.
- Report: `summary{errors, warnings, infos, can_proceed}` and per file `issues[{rule, title, severity, status (passed|failed), affected_rows, detail, examples (at most 5)}]`.

| Rule | Severity | Failed when |
|---|---|---|
| V01 required values | error | `lei_code`, `period` or `item` blank |
| V02 duplicate keys | error | the same identity (every column except `label`, `amount`, `footnote`) appears more than once; report groups and rows |
| V03 amounts are numbers | error | a non-blank amount fails the guarded cast |
| V04 amounts present | warning | blank amount |
| V05 period format | error | not `YYYYMM` or month outside 01 to 12 |
| V06 quarter ends | warning | valid period whose month is not 03, 06, 09 or 12 |
| V07 LEI format | error | not 20 alphanumeric characters (aggregate bucket exempt) |
| V08 country code | warning | `nsa` not two upper-case letters |
| V09 one label per item | warning | an item with more than one distinct label (`affected_rows` = rows of those items) |
| V10 panel balance | info | the number of banks differs between periods; examples list banks, entered and left per period |
| V11 outliers | info | amount beyond 3 x IQR from the quartiles of its (item, period), only groups with at least 30 values, aggregate bucket excluded; examples ordered by distance |
| V12 aggregate bucket | info | rows of 'All other banks' (LEI of X characters, any case, or country OT) are counted: the next step removes them |
| V13 no empty columns | warning | a column with no value in the whole file (footnote columns are exempt) |

Every cast inside a rule must be guarded with `CASE` (rule 10 of step 0).

## 7. Phase C: preparation of the data [DECISIONS NEEDED, section 14]

Default if the owner does not answer: a **recipe** (ordered list of steps stored as JSON in the database, exportable as a file) applied on a working copy of the staging table, never on the original file. Steps: rename a column (only as a mapping to a standard name), drop a non-protected column, filter rows by a rule (for example "exclude the aggregate bucket", "exclude period X"), add a computed column from a short whitelist (quarter from period, decoded label from TR_Metadata). Protected columns (`lei_code`, `period`, `item`, `amount` and the dimension columns of the file) cannot be dropped or renamed freely. Each step returns the number of affected rows and a preview; the last step can be undone; after every step the validation catalogue can be re-run. A real measurement on the 2020 file `tr_cre` (396,232 rows): rename or drop a column 1 ms, delete rows by a rule 100 to 200 ms, add a computed column 1.3 s.

## 8. Phase D: insert into PostgreSQL [DECISIONS NEEDED, section 14]

One transaction per import (all or nothing), started by an approval request (`approved` -> `loading` -> `loaded`), as a job. Steps: take the prepared data, exclude the aggregate bucket, apply the LEI crosswalk of `TR_Metadata`, resolve the item codes through the SDD with exact-label fallback and label verification (unresolved items are reported, never guessed; record how each was resolved in `decision_log`, step `item_resolution`), write the typed fact rows with `COPY`, build the panel, create the `dataset_version` (first version of a quarter becomes active; the partial unique index allows one active version per quarter), store the quality report. Any error rolls back and ends in `failed`. Reuse the verified logic of the earlier `te_engine` package (see `docs/BACKEND_PROMPT.md`, sections 3 and 8) instead of rewriting it. A file already `loaded` (same sha256) must stay refused.

## 9. API conventions, OpenAPI and helpers for the React client

- Every route has `operation_id`, `summary`, a description, pydantic response models with examples, and `responses` for each problem status (404, 409, 422, 504). Tag each module (`ingest`, `processing`, `system`).
- Generate **`docs/openapi.yaml`** for the whole application with `python -m app openapi --out docs/openapi.yaml` (`make openapi`) and add a test that fails when the committed file differs from what the application generates, plus a test that validates it with `openapi-spec-validator`.
- System endpoints for the client: `GET /api/health` (database reachable, queue counts, `worker_hint` when jobs wait and nothing is processing: the worker is probably not running), `GET /api/meta` (import statuses, job statuses, job kinds, file types and the **catalogue of problem types with their HTTP status**, so the client can map errors to messages), `GET /api/jobs/{job_id}` and `GET /api/imports/{import_id}/jobs` (one polling endpoint for every job kind).
- Put in every analytic answer `elapsed_ms`; paged lists return `total`, `page`, `page_size`, `pages`; sampled results return `sampled` and the full count; every response carries `X-Request-ID`; unexpected errors return a generic problem (details only in the log).
- The staging tables disappear when the user drops them: every endpoint must answer 404 `dataset-not-found` with a clear detail, never 500.

## 10. Safety and performance rules

Identifiers from a whitelist, values as parameters, statement timeout, bounded page size, bins and points, no client text in `ORDER BY`, guarded casts with `CASE`, `NULLIF(btrim(col), '')` for blank, never `ORDER BY` an output alias inside an expression (PostgreSQL refuses it), `percentile_cont` for quantiles, `width_bucket` for bins. The staging tables have no index: a scan of 400,000 rows is acceptable (measured below); do not add indexes unless a measurement asks for it.

## 11. Real-data facts to test against (2020 edition, three data files)

`tr_oth` 53,526 rows (periods 202003: 131 banks, 26,070 rows; 202006: 135 banks, 27,034 rows; 163 items); `tr_cre` 396,232 rows (182,195 and 210,083; 94 items); `tr_mrk` 13,668 rows (6,681 and 6,885; 25 items). Aggregate bucket rows: 422, 3,954 and 102 (counted in the totals above, excluded from banks and rows per period). No blank or non-numeric amount, no duplicate identity, every LEI valid, no item with two labels. Expected validation on the three files: 0 errors, 0 warnings; infos V10 (4 banks enter in 202006), V11 (5,068, 66,856 and 488 amounts: bank sizes are heavy-tailed, so this rule stays informational), V12 (422, 3,954, 102). `tr_oth` profile: `footnote` empty in 52,432 of 53,526 rows, amount numeric in all 53,526 (min -32,278.247323, max 2,575,724.25976634). Histogram of item `2020140` (CET1 ratio), period 202006, 10 bins: n = 135, median 0.1613765071, counts [120, 10, 2, 1, 0, 1, 0, 0, 0, 1]. Scatter `2020140` against `2020141` in 202006: 135 pairs, Pearson 0.989, Spearman 0.949. Timings measured on one virtual CPU: profile of `tr_oth` 0.43 s, histogram 0.03 s, validation of the three files 5.8 s (so a job, not a request).

## 12. Tests required (pytest, real PostgreSQL, like `tests/conftest.py`)

1. Pure unit tests: bin edges (linear, log, degenerate, invalid), clip bounds, column roles, filter parsing.
2. Hand-computed expectations on generated data (40 banks, two periods, `I2 = 2 * I1 + 1`): bins checked against an **independent** reference implementation, quantiles, Pearson and Spearman equal to 1 and -1, null counts including blank and whitespace cells.
3. Planted problems: one test that plants every rule's violation and asserts the exact count and the first example of each; the status flow `uploaded` -> `validated` -> `uploaded`; a later status (`loaded`) is never changed.
4. Safety: injection attempts in `sort`, `dim` names, `dim` values, `item`, `lei`, `q` with `%` and `_`; the database objects are still there afterwards.
5. Edge cases: constant values, no numeric values, log scale with zero and negative values, scatter with duplicates per bank, sampling that is reproducible, periods `2020`, `202013`, empty.
6. Worker: enqueue idempotency, progress, `completed`, a handler that fails because the staging was dropped ends in `failed` with the error; no deadlock (the test must finish).
7. API tests (TestClient) for every route and every problem status, the health, meta and job endpoints, the statement timeout (patch a query to `pg_sleep`), and that dropping the staging gives 404, not 500.
8. Architecture test (AST): no import between modules, no upward layer imports, `core` and `shared` do not import `modules`.
9. Migration tests: apply twice, adoption of a database created without `schema_migrations`.
10. OpenAPI: file in sync, valid.
11. A test on the real 2020 files (skipped when absent) asserting the numbers of section 11.

## 13. Order of work and definition of done

Order: step 0 (with tests) -> module skeleton and registry -> phase A -> phase B -> OpenAPI file and tests -> README (how to run API and worker, endpoint table). Then stop and ask the section 14 questions before phases C and D.
Done when: all old and new tests pass, `make dev` and `make worker` start, a staged real import can be previewed, profiled, charted and validated through the API, `docs/openapi.yaml` lists every route, and the module can be started alone.
Out of scope: authentication, the React interface (the existing UI must be updated for the asynchronous import: it must poll `GET /api/imports/{id}` until `job_status` is `completed` or `failed`), model training.

## 14. Decisions for the project owner (default in brackets)

1. One module `eba_processing` for processing, validation and analysis, or three modules as in `architecture.txt` (`eba_processing`, `eba_validation`, `eba_analysis`)? [one module now, split later along the existing `application` files]
2. Preparation steps: protected columns or free editing? [protected]
3. Where is the recipe stored: JSON column of `import_batch` (13 tables stay 13) or a file next to the import? [JSON column, export to file on request]
4. May a validation with errors still be inserted, after an explicit confirmation by an administrator? [no]
5. Are the outlier counts (V11) acceptable as information, or should the rule be limited to ratio items? [information, ratio-only later]
6. Insert target: only the typed fact tables and the panel, or also the quality report per version? [both]
7. Several versions of the same quarter (activate, delete) in the first version of the insert? [first version only]
8. File of the SDD/TR_Metadata per edition: required in the same import as the data files, or may it come from an earlier import? [required in the same import]
9. Must the preview show values as loaded (text) or already typed? [as loaded, plus numeric amount in the profile]
10. Interface language of messages returned by the API (`detail`): English as now, or Romanian too? [English]
