# Stage 4: configurable rule engine

Stage 4a design decisions and the fixed family calibration are implemented by
the panel-independent evaluator of the independent module `app/modules/eba_rules` (since Stage R-3; see its README; profiles in `app/modules/eba_rules/config/profiles/`, frozen profiles verified by sha256). The evaluator loads version-controlled YAML,
validates it, evaluates the panel, and writes one atomic alert result per
bank-period. The same service runs EBA and BNM profiles.

## Schema and persistence

Production had 15 logical application tables before this step. Migration
`core/011_alert.sql` adds exactly one `alert` table, making 16. Profiles are
not copied into the database: `profile_name` and the SHA-256 of the committed
YAML identify the configuration. `alert.rule_results` stores each rule's input, threshold, trigger state,
severity, not-evaluated state, and input flags, plus family scores, the
winning rule per family, and the final level reason.
`(profile_sha256, version_id, bank_id)` is unique and `(profile_name,
version_id)` is indexed. Re-evaluation deletes only the selected profile's
old rows and inserts the complete replacement in one transaction.

## Frozen profile history

Profile v0 (`1296bd8e...4c8bfad`) is the original weighted-sum 4b run.
Profile v0.9 (`794ea5ad...17ad5c`) introduced family maximum scoring to remove
correlated-rule summation. Profile v1.0
(`5a1ec1f4...5bcc4d5c`) moves persistence into the feature family, reduces
relative rules to informational severity 1, and expands the specialist
screen. Profile v1.1 (`28a28fa0...e0089f7e40`) changes persistence to an
exact calendar `t-6 months` comparison. Versions 1.0 and 1.1 are frozen and
were fixed before any event data existed; future behavioral changes require a
version bump.

## Rule model and semantics

Each rule has `id`, `type`, `feature`, `condition`, `severity`, `weight`,
`source`, and `status`. Supported types are level, trend, persistence,
relative, and composite score. Level rules support thresholds and configured
green/amber/red bands. Trend rules use calendar alignment: four quarters, or two semi-annual
observations before 201809. Persistence requires the current observation and
the exact calendar `t-6 months` observation; a missing or NULL observation is
not evaluated. Comparisons crossing the 202006 NPL definition break are also
not evaluated. Relative rules rank each period cross-section. The composite uses family
maxima: severity 0/1/2/3 is assigned per rule, each family contributes its
maximum evaluated severity, and the final level uses the fixed
regulatory-breach, two-families, and family-sum decisions.

NULL is `not_evaluated`, never passed. A `series_break` flag alone does not
make a rule unevaluated; only a comparison that crosses the 202006 definition
break does. The evaluator preserves flags in `rule_results`. Specialist
institutions remain available to level rules but are excluded from relative
rules and the composite by default. No panel or fact rows are written.

## Profiles

`app/modules/eba_rules/config/profiles/eu_eba_v1.1.yaml` contains 18 rules: 11 level, 2 trend, 2
persistence, 2 relative, and 1 composite. Verified regulatory minima are CET1
4.5%, Tier 1 6%, total capital 8%, leverage 3%, plus the urgent CET1 7%
buffer rule. Verified EBA Risk Dashboard Q3 2025 bands are included for Tier
1 (>15% green, 12--15% amber, <12% red), CET1 (>14%, 11--14%, <11%),
leverage (>8%, 5--8%, <5%), NPL (<3%, 3--8%, >8%), and ROE (>10%, 6--10%,
<6%). `npl_high` retains the separate 5% level. Per-rule weights are retained only
for profile compatibility and marked unused; family logic replaces summation.

RoCET1 thresholds use multiplication, as decided: accounting ROE thresholds
of 6% and 10% become **7.20% and 12.00%** using the production
equity/CET1 factor **1.2001447434**, IQR **1.1151567110--1.3135999112**, and
N=2,382 observations from 2020A--2025S. `app/modules/eba_rules/config/profiles/bnm.yaml` mirrors the
same rule structure with empty thresholds/bands/weights and `to_verify`
status.

## Data-quality policy

Pre-202006 NPL results are evaluated with the `series_break` flag and no
threshold scaling. A trend or persistence comparison crossing 202006 is
not-evaluated because the definitions differ. This is transparent but does
not manufacture a correction from facts that do not expose the old
denominator component.

## Production result

`python -m scripts.data.build_reference rules --profile eu_eba --target prod` wrote 4,367
alerts. `docs/design/rule_results.md` contains the complete per-period
evaluated-bank shares, rule trigger/not-evaluated counts, before/after
not-evaluated comparison, dominant rules, and sanity check.

## CLI and worker

The CLI command is:

```text
python -m scripts.data.build_reference rules --profile eu_eba --target test|prod
```

The generic worker exposes the `evaluate_rules` job kind. It reads
`EBA_RULE_PROFILE` (default `eu_eba`) and uses the same atomic service.

## Stage 4d event evaluation

`config/events.yaml` defines the owner-curated event format with LEI, date,
type, source, cause, set, and notes. `python -m scripts.ml.evaluate_rules` applies
the exact 12-to-3-month pre-event window, resolves approved crosswalk groups,
and reports hit rate, Wilson confidence intervals, lead time, false alarms,
precision, and per-event observations. The reusable window and metric code is
in `scripts/ml/event_evaluation.py`; ML evaluation will use the same windows without
future leakage. Results are in `rule_evaluation.md`.

## Next decisions

1. Confirm BNM thresholds and sources.
2. Implement alert endpoints and the React UI, including compatibility for
   historical list-shaped and calibrated object-shaped `rule_results`.
