# eba_ml

Datasets, thesis training, model registry, scoring (`score_panel`) and the `/api/ml` routes.

## Data: starts from `load_panel`, then ...

`app/core/panel_reader.py:load_panel` is the only reader of `panel_row` (one standard row per bank and
period: `bank_id, period, frequency, dataset_version, 14 indicators, flags, is_specialist`).
`application/dataset.py:build_dataset` applies **only** these ML adjustments:

1. **Specialist exclusion** — rows whose flags carry `specialist_institution` are dropped.
2. **Grid** — `semiannual` keeps June/December rows; `quarterly` keeps all.
3. **Features** — the 11 `FEATURES`; per feature a peer rank (share of same-period peers at or below),
   the 12-month change and (unless `robustness`) a missing indicator → feature matrix `X`.
4. **Panel hash** — `panel_reader.panel_hash(rows, FEATURES)` over the adjusted rows (provenance of a run).

Labels (`domain/labels.py`) and the R0-compliant sample are applied afterwards by training:
R0 levels and `compliant` come from `eba_rules.public`; labels are forward-looking (E2/E3, §3.5).
`worker_handlers._score` reads the panel through `load_panel` too; R0-breach rows are flagged, not scored.

## After a panel rebuild

`ModuleSpec.after_panel_rebuild = application/hooks.py:queue_score_jobs` queues one `score_panel` job per champion.
