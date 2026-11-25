# eba_rules

Independent rule-engine module: alert profiles (frozen EU/EBA v1.1, BNM skeleton), the R0/R1
benchmark rules, alert evaluation for a panel version, and the alert API (`/api/public/alerts*`).
All configuration lives in `config/`; other modules and scripts import **only** `public.py`.

```
domain/          levels (R0/R1), profile_schema (strict), rule_evaluation, alert_level  - pure functions
application/     profiles (registry + sha256 check), evaluate (panel -> alerts), alert_queries (API), handler (worker job)
infrastructure/  alert_repository (alert table), db (read session)
presentation/    router + schemas (paths and responses unchanged)
public.py        load_profile, evaluate_panel, evaluate_rows, regulatory_levels, r1_margin_grid_pp,
                 r0_alert, r1_alert, compliant, choose_r1_margin
```

## Data: starts from `load_panel`, then ...

`app/core/panel_reader.py:load_panel` is the only reader of `panel_row` (standard row: `bank_id, period,
frequency, dataset_version, 14 indicators, flags, is_specialist`). `application/evaluate.py:evaluate_panel` applies **only**:

1. **Profile** — the active profile (`config/module.yaml`), loaded and sha256-verified when frozen.
2. **Thresholds / bands / percentiles** per rule (`domain/rule_evaluation.py`); trend rules compare with the
   prior period (index shift before 2018-09, calendar year after) and are not evaluated across the NPL break;
   persistence compares with the previous half-year.
3. **Family severity and alert level** (`domain/alert_level.py`): maximum per family, `REQUIRED_INPUTS` missing → `not_evaluated`.
4. **Persistence** in the alert table: upsert on (profile sha, dataset version, bank), alert_ids are kept.

Rules need no ML-style derived features; specialists are excluded through their flag.
After a panel rebuild the hook `application/hooks.py:evaluate_active_profile` recomputes the active profile.

## Parameters

| Parameter | File | Effect | Frozen? |
|---|---|---|---|
| `active_profile` | `config/module.yaml` | profile evaluated by the worker job and used for default R0 levels | no |
| `profiles[].file / version / frozen / sha256` | `config/module.yaml` | registry of profiles; frozen ones are verified by sha256 on every load | the sha of a frozen profile never changes |
| rules, thresholds, bands, weights, `defaults` | `config/profiles/eu_eba_v1.1.yaml` | what raises an alert (sha 28a28fa0...) | **yes** (v1.1) |
| rules (thresholds still to be supplied) | `config/profiles/bnm.yaml` | BNM skeleton | no |
| `r0_levels.<profile>` (cet1, tier1, total_capital) | `config/regulatory_levels.yaml` | R0 non-compliance and ML sample (`compliant`), R1 base | no (regulatory change) |
| `r1.margin_grid_pp` | `config/regulatory_levels.yaml` | margins tried when choosing R1 (F2 on training rows) | no |

## Create an adjustable copy

1. Copy the profile to `config/profiles/<name>_v<next>.yaml`, set `version` to the new version and
   remove `frozen` (or set it to false).
2. Add an entry to `config/module.yaml` with the new `file`, `version`, `frozen: false` (same `name`
   if it replaces the profile; names are unique).
3. Set `active_profile` if the worker should use it; run `python -m scripts.data.build_reference rules --profile <name> --target test`.
4. Freeze it when final: set `frozen: true` and `sha256` (from `sha256sum`) in both the file and `module.yaml`.

A frozen profile whose file differs from the recorded sha256 raises `ProfileIntegrityError` at load.
Unknown keys anywhere in a profile are errors.

## Not in this module

Thesis-only evaluation (event windows, Sarlin usefulness, baselines B1-B7) stays in
`scripts/ml/event_evaluation.py` and calls `eba_rules.public`.
