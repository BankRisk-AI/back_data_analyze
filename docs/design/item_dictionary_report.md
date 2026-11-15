# Item dictionary build report

## Counts

- SDD files: 11
- Master indicators: 364
- Mappings: 3126
- Ambiguous: 0
- Unmapped: 2

## Per-edition coverage

| Edition | Source codes | Mappings | oth | cre | mrk | sov | Items in data |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2015 | 199 | 199 | 86 | 74 | 25 | 14 | 199 |
| 2016 | 200 | 200 | 90 | 76 | 25 | 9 | 200 |
| 2017 | 0 | 206 | 96 | 76 | 25 | 9 | 206 |
| 2018 | 225 | 225 | 102 | 76 | 25 | 22 | 225 |
| 2019 | 244 | 244 | 130 | 76 | 25 | 13 | 244 |
| 2020S | 278 | 278 | 161 | 79 | 25 | 13 | 278 |
| 2020A | 297 | 297 | 165 | 94 | 25 | 13 | 295 |
| 2021 | 307 | 307 | 168 | 101 | 25 | 13 | 307 |
| 2022 | 295 | 295 | 168 | 89 | 25 | 13 | 295 |
| 2023 | 295 | 295 | 168 | 89 | 25 | 13 | 295 |
| 2024 | 295 | 295 | 168 | 89 | 25 | 13 | 295 |
| 2025 | 285 | 285 | 158 | 89 | 25 | 13 | 285 |

## Master span distribution

| Editions spanned | Master indicators |
|---:|---:|
| 1 | 41 |
| 2 | 9 |
| 3 | 9 |
| 4 | 4 |
| 5 | 9 |
| 6 | 36 |
| 7 | 18 |
| 8 | 45 |
| 9 | 8 |
| 10 | 4 |
| 11 | 9 |
| 12 | 172 |

## Table 3.4 chain check

| Indicator | Chain |
|---|---|
| CET1 ratio | yes |
| Tier 1 ratio | yes |
| Total capital ratio | yes |
| Leverage ratio | yes |
| Total loans | yes |
| Profit/loss | yes |
| Stage 2 / gross NPE | no |

## Unmapped data codes

| Edition | Dataset | Source item | Label | Rows | Reason |
|---|---|---|---|---:|---|
| 2017 | oth | 1720325 | (Impairment or (-) reversal of impairment on financial assets not measured at fair value through profit or loss) - (Loans and receivables) | 242 | not present in any SDD chain |
| 2017 | oth | 1720326 | (Impairment or (-) reversal of impairment on financial assets not measured at fair value through profit or loss) - (Held to maturity investments_ AFS assets and financial assets measured at cost) | 242 | not present in any SDD chain |

## Unmapped non-aggregate row totals

| Edition | Rows |
|---|---:|
| 2017 | 484 |
## Real-data proof

Reload proof for 2016, 2019, and 2025 is maintained in the TEST database run.
The Stage 2e full twelve-edition reload remains pending.

## Known gaps

- D2: no leverage ratio exists in 2016; no link is applied.
- D3: the ROE denominator is decided in Stage 3; no link is applied here.
- D4: 2017 source items `1720325` and `1720326` remain unmapped; their labels and row counts are listed above.
- Stage 2 / gross NPE remains deferred to Stage 3 because it requires credit-risk dimension derivation.

## Applied decisions

- D1: 2015 `oth` item `150130` maps to canonical indicator `2520133` through `config/data_decisions.yaml`.
