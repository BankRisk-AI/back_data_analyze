# Stage 2 preflight

The full-data preflight staged and validated every edition on TEST without
loading facts. Exact duplicate rows are normalized out and the configured
owner exclusions are applied before classification.

| Edition | Fact table | Class i | Class ii | Class iii | Class iv | Total |
|---|---|---:|---:|---:|---:|---:|
| 2015 | — | 0 | 0 | 0 | 0 | 0 |
| 2016 | — | 0 | 0 | 0 | 0 | 0 |
| 2017 | — | 0 | 0 | 0 | 0 | 0 |
| 2018 | — | 0 | 0 | 0 | 0 | 0 |
| 2019 | — | 0 | 0 | 0 | 0 | 0 |
| 2020S | fact_cre | 0 | 0 | 2 | 0 | 2 |
| 2020A | — | 0 | 0 | 0 | 0 | 0 |
| 2021 | — | 0 | 0 | 0 | 0 | 0 |
| 2022 | — | 0 | 0 | 0 | 0 | 0 |
| 2023 | — | 0 | 0 | 0 | 0 | 0 |
| 2024 | — | 0 | 0 | 0 | 0 | 0 |
| 2025 | — | 0 | 0 | 0 | 0 | 0 |

## Samples

- `2020S` `fact_cre` class `iii`: LEI
  `529900GGYMNGRQTDOO93`, period `201912`, item `2020501`, exposure `0`;
  two rows remain with different amounts before the configured exclusion.
- `2020S` `fact_cre` class `iii`: LEI
  `529900GGYMNGRQTDOO93`, period `201912`, item `2020502`, exposure `303`;
  two rows remain with different amounts before the configured exclusion.

## Diagnosis

The two remaining groups are in `2020S/tr_cre.csv` and are class (iii):
their loader identity is the same while source rows carry different amounts.
Both are covered by the configured BNG owner exclusions. No loading fix is
applied by this diagnostic.
