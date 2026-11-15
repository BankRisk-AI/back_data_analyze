# Stage 2e final report

## Phase 1: CET1 and capital-ratio chain

The 2015 rows were resolving directly to temporary indicator IDs
`150135`/`150136`/`150137` because the dictionary's suffix heuristic preferred
the 2015 code before following the labeled SDD chain. The SDDs explicitly link
these rows to `2520140`/`2520141`/`2520142`; the builder now prefers matching
capital labels and the newest capital target for 2015/2016 source rows. No
owner item-link decision was added. The second dictionary build is idempotent.

On TEST, the corrected full reload produced 36 points under one indicator ID
for each series: CET1 `2520140`/ID 228, Tier 1 `2520141`/ID 229, and total
capital `2520142`/ID 230. Unmapped codes are only `1720325` and `1720326`;
ambiguous mappings are zero.

## Production (`eba`)

The `eba` database was loaded twice with identical results: first through the
DEV rehearsal procedure and then through the production procedure. The
independent evidence is the TEST rehearsal and checks a–e; checks f–g compare
the same database because both historical targets resolved to `eba`.

| Edition | Periods | Banks | fact_oth | fact_cre | fact_mrk | fact_sov | Load seconds (bank/facts/post) |
|---|---:|---:|---:|---:|---:|---:|---|
| 2015 | 2 | 105 | 17,220 | 251,666 | 10,710 | 1,034,880 | 13.43 / 99.39 / 0.54 |
| 2016 | 2 | 131 | 23,318 | 313,070 | 13,362 | 27,684 | 3.82 / 28.57 / 0.47 |
| 2017 | 2 | 132 | 24,310 | 312,478 | 13,464 | 28,380 | 5.15 / 35.22 / 0.41 |
| 2018 | 2 | 130 | 24,566 | 260,178 | 13,260 | 569,390 | 9.89 / 80.22 / 0.57 |
| 2019 | 4 | 131 | 77,523 | 530,483 | 25,908 | 1,105,412 | 21.28 / 170.56 / 1.04 |
| 2020S | 2 | 127 | 50,230 | 338,773 | 12,750 | 542,036 | 11.05 / 93.80 / 1.51 |
| 2020A | 2 | 135 | 53,104 | 392,278 | 13,566 | 576,180 | 11.96 / 98.28 / 1.63 |
| 2021 | 4 | 120 | 94,448 | 793,696 | 23,664 | 376,457 | 16.08 / 129.13 / 1.92 |
| 2022 | 4 | 122 | 95,046 | 675,200 | 23,154 | 396,633 | 14.72 / 125.27 / 2.83 |
| 2023 | 4 | 123 | 99,355 | 602,185 | 24,429 | 414,093 | 15.70 / 121.90 / 6.06 |
| 2024 | 4 | 123 | 98,456 | 598,782 | 24,378 | 431,456 | 15.65 / 122.31 / 3.45 |
| 2025 | 4 | 119 | 90,453 | 640,275 | 23,613 | 439,798 | 14.44 / 116.98 / 3.51 |

Checks **a–e** all pass: 36 unique active periods; reconciliation is
accounted for by aggregate rows, exact duplicates, and four decision rows;
expected bank counts; all three capital series have 36 points and one ID;
dictionary result and two decisions/four rows; and DEV fact counts match TEST
per edition and table. The first load took 2390.60 seconds and the production
reload took 2207.61 seconds.

Known gaps remain D2, D3, D4, sovereign coverage for 2015–2018, Stage 2 /
gross NPE, and semi-annual data before 201809.

Phase 0 was empty. Migrations `core/001_baseline` through
`core/009_indicator_code_map` are applied. The verified backup is
`backups/prod_before_2e_20261115.dump` (71,661,344 bytes; 140
`pg_restore --list` entries). Reset recorded 12,625,677 pre-reset rows in
`audit_log`, preserved `audit_log` and `app_user`, and left zero resettable
rows. All 12 editions loaded successfully oldest-first.

Checks **f–g** pass for the second load: fact, bank, indicator, and mapping
counts match the first load, and the 36 values in each capital series match
because both targets are the same `eba` database. The database is
approximately 2,173 MB.

## Environments and storage cleanup

Production is `eba` via `DATABASE_URL`, with
`EBA_STORAGE=/var/projects/python/eba_analyst/prod/eba_storage`. Test is
`eba_test` via `TEST_DATABASE_URL`, using `storage_test` (or the configured
temporary test storage). `serve` and `worker` use the production
`DATABASE_URL`/`EBA_STORAGE` configuration.

All 71 production `source_file` paths were present under
`prod/eba_storage` and all 71 SHA-256 hashes matched. No row in `eba` or
`eba_test` referenced the legacy `storage/` path. The legacy `storage/`
directory, including `storage/tmp`, was removed, freeing 2,305,169,812 bytes.
Backups retained are `dev_before_2e_20261115.dump` (24,999,837 bytes, data
before the first full reload) and `prod_before_2e_20261115.dump` (71,661,344
bytes, the full load before the second reload of `eba`).

The read-only production smoke check passed: 36 active versions, 36 CET1
points under one indicator ID (master code `2520140`, current ID 134), and
`GET /api/public/periods` returned HTTP 200 with 36 periods.
