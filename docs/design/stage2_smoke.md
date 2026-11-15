# Stage 2 smoke rehearsal

Runtime: 400.61s

## Sample

Selected LEIs: 0SK1ILSPWNVBNQWU0W18, 0W2PZJM8XOY22M4GG883, 2138004FIUXU3B2MR537, 213800TC9PZRBHMJW403, 213800X3Q9LSAKRUWY91, 529900GGYMNGRQTDOO93; aggregate X/X rows retained.

## Run

| Edition | Last phase | Outcome | Error | Seconds |
|---|---|---|---|---:|
| 2015 | load | passed |  | 9.52 |
| 2016 | load | passed |  | 4.64 |
| 2017 | load | passed |  | 6.82 |
| 2018 | load | passed |  | 11.26 |
| 2019 | load | passed |  | 18.45 |
| 2020S | load | passed |  | 9.52 |
| 2020A | load | passed |  | 9.79 |
| 2021 | load | passed |  | 12.07 |
| 2022 | load | passed |  | 11.95 |
| 2023 | load | passed |  | 11.79 |
| 2024 | load | passed |  | 11.74 |
| 2025 | load | passed |  | 11.32 |

## Post-run

The smoke command records active periods, bank counts, CET1 rows, and decision evidence in the TEST database; the run table above preserves every failure instead of stopping at the first one.

## Where it fails

- No pipeline failures in the sample.
