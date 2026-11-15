# CSV column drift

## Decision

Keep `row`, `column`, and `sheet` as nullable `text` audit columns in every
staging/fact path. They occur in 2023–2025 only and identify the source
spreadsheet location; they are not analytical dimensions. Keep optional
business dimensions as nullable text as well, because the staging contract is
all-text and the loader already projects only known target columns.

## Observed drift

| CSV type | 2015/2016 | 2025 | optional columns observed |
|---|---|---|---|
| `tr_oth` | only 2015 lacks `Label`; 2016 has `Label` and `n_quarters` | no `Footnote` | `assets_fv`, `assets_stages`, `exposure`, `financial_instruments`, `fin_end_year`, `row`, `column`, `sheet` |
| `tr_cre` | only 2015 lacks `Label`; 2016 has `Label` | no `Footnote` | `nace_codes`, `row`, `column`, `sheet` |
| `tr_mrk` | only 2015 lacks `Label`; 2016 has `Label` | no `Footnote` | `row`, `column`, `sheet` |
| `tr_sov` | only 2015 lacks `Label`; 2016 has `Label`; `maturity` absent in 2016 | no `Footnote` | `accounting_portfolio`, `maturity`, `row`, `column`, `sheet` |

The inventory shows `Label` absent only in 2015, while 2016 has both `Label` and
`n_quarters`; `Footnote` is absent in 2015/2016/2025 (the exact header spelling varies between
`footnote` and `Footnote`). The current reader normalises headers to lowercase
underscore names, and `missing_required()` requires only
`lei_code,nsa,period,item,label,amount`; therefore current loading does **not**
tolerate files without `Label`: they are rejected before staging. It does
tolerate absent optional columns such as `n_quarters`, `footnote`, and the
source-location columns. The 2015 files in the prepared directory are named
with the standard aliases, so filename classification is not the blocker.

The proposed fix for the next implementation stage is to make `label` optional
at ingestion (populate it as null), preserve all optional headers, and make
promotion use nullable target columns. Do not silently invent labels from the
SDD; retain source labels when present and resolve dictionary labels separately.
