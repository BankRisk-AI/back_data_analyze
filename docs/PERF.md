# Real-file pipeline performance

Measured on 2026-11-12 with the original 2020 EBA files
(`tr_cre_2.csv`, 396,232 rows; largest file), PostgreSQL 16 on the local
development database. The host is an Intel Core i5-8265U (8 CPUs) with 7.6 GiB
RAM. Timings are wall-clock seconds from the phase-boundary test instrumentation.

| Phase | Before | After | Limit |
|---|---:|---:|---:|
| Stage job | 165.80 | 9.24 | 60 |
| `validate_data` job | not previously measured | 13.10 | 90 |
| Load job | not previously measured | 26.48 | 120 |

The measured staging bottleneck was four independent full-table scans in the
period report. The aggregate-row count and both period-quality counts now share
one scan; the pair report remains a separate grouped query. This reduced the
largest-file staging phase from 165.80s to 9.24s without changing report
contents.

The three representative scans, captured with `EXPLAIN (ANALYZE, BUFFERS)`,
were:

1. `fill_period_report` aggregate/quality counts: `Seq Scan` on the unlogged
   staging table; approximately 396k rows, one pass, no useful index.
2. `fill_period_report` period-pair grouping: `Seq Scan` plus `HashAggregate`;
   approximately 396k rows, one pass.
3. Load fact insertion: `Seq Scan` on the staging table joined to temporary
   version, bank, and item maps; the temporary primary keys were used for the
   joins.

The exact plans are intentionally summarized here rather than committed as
machine-specific full plans. The phase limits pass: 9.24s, 13.10s, and 26.48s.
