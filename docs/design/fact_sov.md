# `fact_sov` design

## Stage and validation evidence

`tr_sov.csv` for 2016 and 2025 was staged into the configured test database
with the existing ingest path and validated with `run_validation`; neither
import was loaded into public facts. Both reports had zero errors and zero
warnings and `can_proceed=true`; the two informational findings were the
expected outlier and aggregate-bucket reports.

| edition | rows | non-aggregate rows | validation |
|---|---:|---:|---|
| 2016 | 27,984 | 27,684 | 0 errors, 0 warnings, 2 infos |
| 2025 | 448,334 | 439,798 | 0 errors, 0 warnings, 2 infos |

## Column roles and profiles

Null percentages are zero for every observed column in both files. Distinct
counts are non-blank values; “top” lists the ten most frequent values for
dimensions with at most 50 distinct values (LEIs are shown only as the top
ten despite having more than 50 values).

| edition | column | role | distinct | top values (value=count) |
|---|---|---|---:|---|
| both | `lei_code` | bank identity | 132 / 120 | 2016: ten LEIs at 300 each; 2025: `XXXXXXXXXXXXXXXXXXXX`=8,536, `7LTWFZYICNSX8D621K86`=8,342, `FR9695005MSX1OYEMGDF`=8,148 |
| both | `nsa` | reporting-country dimension | 25 / 26 | 2016: DE=4,644, FR=2,544, AT=2,136; 2025: DE=91,568, FR=56,842, IT=53,738 |
| both | `period` | time identity | 2 / 2 | 2016: 201512=13,992, 201606=13,992; 2025: 202412=224,167, 202506=224,167 |
| both | `item` | indicator identity | 9 / 13 | 2016: 1620802/1620804/1620806=7,744 each; 2025: 2520810–2520819=36,976 each |
| both | `label` | source audit label | 9 / 13 | one label per item; 2016 carrying-amount labels dominate at 7,744; 2025 each listed item label is 36,976 |
| both | `country` | sovereign-country dimension | 45 / 44 | 2016: 0=4,752, 1=528, 10=528; 2025: 244=22,116, 10=20,176, 9=19,982 |
| 2016 | `accounting_portfolio` | portfolio dimension | 6 | 0=24,024; 1–5=792 each |
| 2025 | `accounting_portfolio` | portfolio dimension | 1 | 0=448,334 |
| 2025 | `maturity` | maturity dimension | 8 | 8=60,086; 1–7=55,464 each |
| both | `amount` | measure | 7,587 / 63,133 | numeric; no nulls |
| 2025 | `row` | source-location audit | 352 | no nulls |
| 2025 | `column` | source-location audit | 26 | no nulls |
| 2025 | `sheet` | source-location audit | 1 | no nulls |

## Proposed schema

Add numbered migration `fact_sov` with:

```sql
CREATE TABLE fact_sov (
  version_id integer NOT NULL REFERENCES dataset_version(version_id) ON DELETE CASCADE,
  bank_id integer NOT NULL REFERENCES bank(bank_id),
  indicator_id integer NOT NULL REFERENCES indicator(indicator_id),
  nsa text,
  country text,
  accounting_portfolio text,
  maturity text,
  amount double precision,
  footnote text,
  source_row text,
  source_column text,
  source_sheet text
);
```

Keep all dimensions text because 2016 and 2025 use different code spaces and
the existing staging contract is text. Add a partial unique index over the
smallest observed non-aggregate identity:

```sql
CREATE UNIQUE INDEX fact_sov_identity
ON fact_sov(version_id, bank_id, indicator_id, country, accounting_portfolio, maturity)
NULLS NOT DISTINCT;
```

The smallest unique sets found in the staged data were
2016 `(lei_code, period, item, country, accounting_portfolio)` and 2025
`(lei_code, period, item, country, maturity)`. Since `accounting_portfolio`
is constant in 2025 and `maturity` is absent in 2016, the physical key must
be the nullable union shown above; `nsa` is retained for audit/querying but is
not needed for uniqueness in either sample.

Create `v_tr_sov` with file-shaped columns:
`lei_code,nsa,period,item,label,country,accounting_portfolio,maturity,amount,
footnote,row,column,sheet`, joining `fact_sov` to bank, indicator, and
dataset_version. Exclude aggregate rows only in analytical queries, not in the
view.
