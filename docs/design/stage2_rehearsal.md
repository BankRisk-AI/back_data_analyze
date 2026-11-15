# Stage 2e full rehearsal

The full rehearsal ran on TEST only on 2026-11-15. The 2020S gate passed
first: `import-edition` completed with status `loaded`, 127 distinct banks,
and two data decisions affecting four rows. The subsequent `import-all`
completed all 12 editions in 2359.97 seconds.

| Edition | Periods | Banks | fact_oth | fact_cre | fact_mrk | fact_sov | Load timings bank/facts/post (s) | Outcome |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 2015 | 2 | 105 | 17,220 | 251,666 | 10,710 | 1,034,880 | 13.47 / 108.82 / 0.50 | loaded |
| 2016 | 2 | 131 | 23,318 | 313,070 | 13,362 | 27,684 | 3.81 / 31.17 / 0.37 | loaded |
| 2017 | 2 | 132 | 24,310 | 312,478 | 13,464 | 28,380 | 5.08 / 36.30 / 0.40 | loaded |
| 2018 | 2 | 130 | 24,566 | 260,178 | 13,260 | 569,390 | 11.34 / 82.49 / 0.58 | loaded |
| 2019 | 4 | 131 | 77,523 | 530,483 | 25,908 | 1,105,412 | 21.28 / 170.48 / 1.01 | loaded |
| 2020S | 2 | 127 | 50,230 | 338,773 | 12,750 | 542,036 | 11.74 / 88.27 / 1.51 | loaded |
| 2020A | 2 | 135 | 53,104 | 392,278 | 13,566 | 576,180 | 11.90 / 104.99 / 1.63 | loaded |
| 2021 | 4 | 120 | 94,448 | 793,696 | 23,664 | 376,457 | 16.34 / 120.43 / 1.86 | loaded |
| 2022 | 4 | 122 | 95,046 | 675,200 | 23,154 | 396,633 | 18.19 / 119.58 / 2.04 | loaded |
| 2023 | 4 | 123 | 99,355 | 602,185 | 24,429 | 414,093 | 15.45 / 121.18 / 3.74 | loaded |
| 2024 | 4 | 123 | 98,456 | 598,782 | 24,378 | 431,456 | 14.07 / 122.74 / 4.08 | loaded |
| 2025 | 4 | 119 | 90,453 | 640,275 | 23,613 | 439,798 | 15.61 / 118.94 / 4.03 | loaded |

Expected bank counts were met exactly. Exact duplicates are removed by the
set-based fact load; the only non-duplicate exclusions are the two configured
2020S BNG decisions, each matching two rows. Successful loads drop staging.

## Checks

- **a — active versions:** pass; 36 active versions, 36 distinct
  `(year, quarter)` pairs, and no active period has more than one version.
- **b — row reconciliation:** pass; promoted rows are accounted for by source
  rows, aggregate exclusions, exact duplicates, or the four decision rows.
- **c — banks:** pass; `105, 131, 132, 130, 131, 127, 135, 120, 122, 123,
  123, 119`.
- **d — CET1 transitional indicator:** pass; every returned period uses
  `indicator_id=223` (`2520140`) for
  `2015Q4:0.1350741698`, `2016Q2:0.1352919117`,
  `2016Q4:0.1770650766`, `2017Q2:0.1844090023`, `2017Q4:0.1703`,
  `2018Q2:0.1797`, `2018Q3:0.1657`, `2018Q4:0.1537`, `2019Q1:0.1487`,
  `2019Q2:0.1515`, `2019Q3:0.1366675071`, `2019Q4:0.1420888139`,
  `2020Q1:0.1363751358`, `2020Q2:0.1281527942`, `2020Q3:0.1462774155`,
  `2020Q4:0.1503947025`, `2021Q1:0.1545129168`, `2021Q2:0.1528215136`,
  `2021Q3:0.1502248209`, `2021Q4:0.1523972841`, `2022Q1:0.1658611367`,
  `2022Q2:0.1577439186`, `2022Q3:0.1625064266`, `2022Q4:0.174180632`,
  `2023Q1:0.1817020823`, `2023Q2:0.1875473425`, `2023Q3:0.1826282877382`,
  `2023Q4:0.19181648423134`, `2024Q1:0.18278072121469`,
  `2024Q2:0.18282221844874`, `2024Q3:0.18418734934683`,
  `2024Q4:0.19807397897669`, `2025Q1:0.2149349925017`,
  `2025Q2:0.21067831860662`.
- **e — dictionary and decisions:** pass; unmapped codes are only `1720325`
  and `1720326`, ambiguous mappings are 0, and 2020S applied 2 decisions /
  4 rows.

## Environment and storage

DEV was accessed read-only and no command selected the DEV target; final counts
were bank 194, indicator 1160, dataset_version 14, fact_oth 244398,
fact_cre 1876106, fact_mrk 62883, and fact_sov 1572894. TEST was about
2,179 MB and `storage/` about 2.2 GB after rehearsal.
