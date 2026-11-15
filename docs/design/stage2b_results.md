# Stage 2b real-edition results

Every edition was staged and validated in the TEST database as one import with
`tr_sov` excluded. No edition was loaded during the 2b-fix rerun.

| Edition | Rows staged | Errors before | Errors after | Warnings after | Result |
|---|---:|---:|---:|---:|---|
| 2015 | 279,596 | 0 | 0 | 3 | pass |
| 2016 | 353,580 | 0 | 0 | 0 | pass |
| 2017 | 354,094 | 0 | 0 | 1 | pass |
| 2018 | 301,851 | 39,133 | 0 | 0 | fixed |
| 2019 | 641,828 | 84,633 | 0 | 0 | fixed |
| 2020S | 406,427 | 836 | 1 | 0 | decision required |
| 2020A | 463,426 | 0 | 0 | 0 | pass |
| 2021 | 922,019 | 0 | 0 | 0 | pass |
| 2022 | 802,612 | 0 | 0 | 0 | pass |
| 2023 | 735,181 | 0 | 0 | 0 | pass |
| 2024 | 730,828 | 0 | 0 | 0 | pass |
| 2025 | 764,045 | 0 | 0 | 2 | pass |

## Diagnosed failures

### 2018 — `tr_cre` V03 (33,404), `tr_mrk` V03 (309), `tr_oth` V03 (5,420)

Classification: **(b) rule assumption wrong for this edition**. Amounts use
quoted thousands separators such as `74,672.4857`; CSV parsing is correct, but
the numeric predicate accepted only ungrouped numbers. Representative rows
were `0SK1ILSPWNVBNQWU0W18/DE/201712/1820501/74,672.4857`,
`0SK1ILSPWNVBNQWU0W18/DE/201712/1820502/6,025.5154`,
`0SK1ILSPWNVBNQWU0W18/DE/201712/1820502/15,670.7984`,
`0SK1ILSPWNVBNQWU0W18/DE/201712/1820502/6,289.7039`, and
`0SK1ILSPWNVBNQWU0W18/DE/201712/1820502/1,179.8548`.
Staging now removes grouping commas from amount values. The ingest reports
recorded 33,404 normalised values in `tr_cre`, 309 in `tr_mrk`, and 5,420 in
`tr_oth` for 2018; for 2019 the corresponding counts were 66,009, 601, and
18,023.

### 2019 — `tr_cre` V03 (66,009), `tr_mrk` V03 (601), `tr_oth` V03 (18,023)

Classification: **(b) rule assumption wrong for this edition**. The same
quoted thousands-separated amount format occurs, for example
`0W2PZJM8XOY22M4GG883/DE/201809/1920502/21,893.9301`,
`0W2PZJM8XOY22M4GG883/DE/201809/1920502/28,318.6905`,
`0W2PZJM8XOY22M4GG883/DE/201809/1920502/6,175.0138`,
`0W2PZJM8XOY22M4GG883/DE/201809/1920502/7,333.1908`, and
`0W2PZJM8XOY22M4GG883/DE/201809/1920502/7,111.6814`. The same staging
normalisation fixes all three files.

### 2020S — `tr_cre` V02 (836 before; 4 conflicting rows after)

Classification: **(c) real data issue in the EBA file**. There are 416 exact
duplicate identities (832 rows), which are now informational and are
deduplicated at load time. Two identities contain conflicting amounts and
remain errors:

| LEI | Period | Item | Dimensions | Amounts |
|---|---|---|---|---|
| 529900GGYMNGRQTDOO93 | 201912 | 2020501 | portfolio=1, country=0, country_rank=0, exposure=0, status=0, perf_status=0, nace_codes=0 | 137689.4292133; 139242.57839904 |
| 529900GGYMNGRQTDOO93 | 201912 | 2020502 | portfolio=1, country=0, country_rank=0, exposure=303, status=0, perf_status=0, nace_codes=0 | 64358.9284689; 65912.07765464 |

These four rows were excluded by the owner decisions below, allowing 2020S to
load successfully:

| Decision | Item | Rows excluded |
|---|---|---:|
| `2020s-2020501-bng-exclude` | 2020501 | 2 |
| `2020s-2020502-bng-exclude` | 2020502 | 2 |

The loaded 2020S facts contain 127 distinct banks.

2017, 2020A, and 2021 pass the relevant error rules for the right reason:
their amounts do not use the 2018/2019 grouped format and they contain no
conflicting duplicate identities.

## Bank counts

The selected-load results and staged-file cross-check are:

| Edition | (i) distinct staged LEIs | (ii) distinct fact `bank_id` | (iii) TR_Metadata rows | (iv) total `bank` rows |
|---|---:|---:|---:|---:|
| 2015 | 105 | 105 | 105 | 105 |
| 2023 | 123 | 123 | 124 | 124 |
| 2025 | 119 | 119 | 120 | 130 |

The extra metadata row in 2023 and 2025 is the aggregate `XXXXXXXXXXXXXXXXXXXX`
entry; it creates a metadata bank but no fact rows. Fact identity resolution
still matches the required staged counts exactly.
