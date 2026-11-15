# Bank metadata reader

## Reader behavior required

The reader must inspect every worksheet, not assume a sheet title. For each
sheet, scan rows until a normalised header contains `lei_code`; this handles
title rows and the observed names `Bank list`, `Banks list`, `List of
Institutions`, and `List of Financial Institutions`. The first matching row is
the header; subsequent rows are records, skipping rows with a blank LEI.
Normalise headers to lowercase underscores, but preserve the raw workbook path
and source sheet for audit.

`lei_code` is the current LEI. `name`, `country`/`country_code`, and `finrep`
are the current attributes. Previous LEIs are every non-empty column whose
normalised name is `lei_code_*`, including variants such as
`lei_code_tr16`, `lei_code_te20s`, `lei_code_17`, and the 2015
`lei_code_used_for_2014_stress_test`. Store the source edition for each
previous-LEI edge rather than flattening it without provenance.

## Observed workbook details

2015 uses `List of Financial Institutions` with the header on row 3 and only
`lei_code_used_for_2014_stress_test`. 2017 uses `Bank list` on row 2;
2018–2021 use `Bank list`/`Banks list`; 2022–2025 use `List of Institutions`.
2024/2025 also have title rows in the `Other banks` sheet, but the
`lei_code`-header scan selects the institution sheet.

The current implementation in `load_service._metadata()` hard-codes
`"Bank list"`, so it fails for 2015, 2020S, 2021, and 2022–2025 despite those
workbooks containing usable institution lists. The staging recogniser has the
same hard-coded sheet-name assumption and should be changed in the same
implementation step.

## 2016 limitation

`eba_prepared/2016/TR_Metadata.xlsx` is missing. Consequently 2016 cannot
provide names, country/FinRep metadata, or previous-LEI relationships from
the workbook. Keep the 2016 bank rows sourced from the data itself, leave
metadata nullable, and use LEI continuity from adjacent editions only as a
separately marked inference; do not fabricate 2016 metadata.
