# Stage 2c real-edition results

`tr_sov` was included in one import for each edition, validated, and loaded
into `fact_sov`. Aggregate rows were excluded during promotion.

| Edition | Staged non-aggregate rows | `fact_sov` rows | Distinct banks | Load time |
|---|---:|---:|---:|---:|
| 2016 | 27,684 | 27,684 | 131 | 26.29 s |
| 2019 | 1,105,412 | 1,105,412 | 131 | 151.21 s |
| 2025 | 439,798 | 439,798 | 119 | 102.80 s |

All three validations completed with zero errors.
