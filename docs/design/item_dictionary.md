# Cross-edition item dictionary design

## Evidence and coverage

The SDD workbooks were read from `eba_prepared/<edition>/SDD*.xlsx`. The
available SDD editions are 2015, 2016, 2018, 2019, 2020S, 2020A, and 2021–2025;
there is no 2017 SDD. The `Item_TR_<edition>` columns form a forward mapping
from an old code to the current row. The number of rows and rows with at least
one historical mapping are:

| edition | rows | rows with historical mapping |
|---|---:|---:|
| 2015 | 239 | 0 |
| 2016 | 259 | 228 |
| 2018 | 364 | 343 |
| 2019 | 294 | 262 |
| 2020S | 328 | 294 |
| 2020A | 347 | 322 |
| 2021 | 357 | 345 |
| 2022 | 345 | 345 |
| 2023 | 345 | 345 |
| 2024 | 345 | 345 |
| 2025 | 335 | 329 |

Most mappings are clean one-to-one chains. New rows without a historical code
are additions (31 in 2016, 21 in 2018, 32 in 2019, 34 in 2020S, 25 in 2020A,
12 in 2021, and 6 in 2025); the reverse case is an item disappearing from the
next SDD and should remain in the dictionary with `last_seen_edition` set.
The significant semantic reuse is the old Tier-1 code `150130`/`1620133`
(and `993432` from 2014): each later SDD maps it both to the capital line
(`...0133`) and the leverage numerator (`...0901`). These are two master
indicators, not one interchangeable indicator, so the load must use the
dataset/template context as a disambiguator.

## Proposed master dictionary

Use the 2025 SDD as the canonical label/category source, retain every code
ever seen, and store one row per `(edition, source_item, source_dataset)` in
`indicator_code_map` with `master_indicator_id`, `source_label`, `master_label`,
`first_seen_edition`, `last_seen_edition`, `mapping_method` (`sdd_direct`,
`context_disambiguated`, `unresolved`), and a uniqueness constraint on
`(edition, source_item, source_dataset)`. `master_indicator` holds the stable
ID, canonical label, category, and optional `deprecated_at`; loading resolves
`(edition_label, file_group, item)` through this map and refuses an unresolved
ambiguous mapping rather than guessing.

## Table 3.4 chains

The chains below use the transitional-period definition where both transitional
and fully-loaded variants exist. `1720xxx` is shown as an SDD-referenced code
only; the 2017 data has no SDD.

| indicator/input | complete chain or result |
|---|---|
| CET1 ratio | `2015:150135 -> 2016:1620140 -> 2017:1720140 -> 2018:1820140 -> 2019:1920140 -> 2020S/A:2020140 -> 2021:2120140 -> 2022:2220140 -> 2023:2320140 -> 2024:2420140 -> 2025:2520140`; **yes**, with the 2017 SDD gap and a separate fully-loaded chain ending `2520146`. |
| Tier 1 ratio | `150136 -> 1620141 -> 1720141 -> 1820141 -> 1920141 -> 2020141 -> 2120141 -> 2220141 -> 2320141 -> 2420141 -> 2520141`; **yes**, same 2017 evidence gap. |
| Total capital ratio | `150137 -> 1620142 -> 1720142 -> 1820142 -> 1920142 -> 2020142 -> 2120142 -> 2220142 -> 2320142 -> 2420142 -> 2520142`; **yes**, same 2017 evidence gap. |
| Leverage ratio | Transitional chain `151003 -> 1720905 -> 1820905 -> 1920905 -> 2020905 -> 2120905 -> 2220905 -> 2320905 -> 2420905 -> 2520905`; **no direct 2016 mapping**. Fully phased-in chain starts at `1720906` and ends `2520906`. |
| ROE inputs | Profit/loss chain `150335 -> 1620335 -> 1720335 -> 1820335 -> ... -> 2520335`. Total-equity input starts only at `2020A:2021216 -> 2021:2121216 -> ... -> 2025:2521216`; **not complete for 2015–2019**, so ROE requires a documented denominator policy. |
| Gross NPE loans | No exact “gross NPE loans” item exists in the SDD chain. The nearest explicit NPE rows are collateral/forbearance measures (`150623 -> ... -> 2520623` and `150625 -> ... -> 2520625`), which are not the gross NPE numerator. **No**: derive from credit-risk status/performance dimensions or leave unresolved. |
| Total loans | `2015:150603 -> 2016:1620603 -> 2017:1720603 -> ... -> 2025:2520603` is the continuous gross carrying amount on loans and advances chain; **yes**. |
| Stage 2 loans | No SDD item labelled Stage 2 was found. Stage information is represented by credit-risk dimensions/labels in the CSVs, not a stable SDD item. **No**: resolve from the relevant `tr_cre` status/performance dimensions after column-level analysis. |

The 2018 SDD explicitly contains `Item_TR_2017` for the carried-forward rows,
so it covers the 2017 item codes despite the missing 2017 workbook; it does not
prove that every 2017-only item had a matching 2018 row.

## Load plan and open questions

Load one import per edition, oldest first, with labels
`2015, 2016, 2017, 2018, 2019, 2020S, 2020A, 2021, 2022, 2023, 2024, 2025`.
The two 2019 sovereign files belong to the same edition import. For each
edition: store immutable originals, stage all recognised CSVs, validate, review
the report, then load; never load the 2016/2025 `tr_sov` design probes used for
this document. The prepared originals occupy 2.214 GB (2.207 GB CSV plus
7.1 MB workbooks); reserve approximately 2.2 GB for raw staging and at least
1.5 GB for typed facts, indexes, and temporary tables, so a 5.5 GB working
budget is prudent.

Open questions (recommended answer):

1. Should the master dictionary split transitional and fully-loaded ratios?
   **Yes**, use separate master indicators.
2. Should unresolved SDD mappings block a load? **Yes**, fail the edition with
   an explicit mapping report rather than silently coalescing codes.
3. Should missing 2016 bank metadata be inferred from neighbouring editions?
   **No**, keep it nullable and mark inferred continuity separately.
4. Should `tr_sov` aggregate rows be retained? **Yes**, retain them and exclude
   them only from bank-level analytics.
5. Should missing labels be accepted? **Yes**, nullable source labels with SDD
   labels as a separate resolved field.
6. Should Stage 2/NPL be derived in the first `panel_row` release?
   **No**, first ship sourced facts and add derivations after the credit-risk
   dimension mapping is approved.
