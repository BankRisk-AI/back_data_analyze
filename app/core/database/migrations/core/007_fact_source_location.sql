ALTER TABLE fact_oth ADD COLUMN IF NOT EXISTS source_row text;
ALTER TABLE fact_oth ADD COLUMN IF NOT EXISTS source_column text;
ALTER TABLE fact_oth ADD COLUMN IF NOT EXISTS source_sheet text;

ALTER TABLE fact_cre ADD COLUMN IF NOT EXISTS source_row text;
ALTER TABLE fact_cre ADD COLUMN IF NOT EXISTS source_column text;
ALTER TABLE fact_cre ADD COLUMN IF NOT EXISTS source_sheet text;

ALTER TABLE fact_mrk ADD COLUMN IF NOT EXISTS source_row text;
ALTER TABLE fact_mrk ADD COLUMN IF NOT EXISTS source_column text;
ALTER TABLE fact_mrk ADD COLUMN IF NOT EXISTS source_sheet text;

CREATE OR REPLACE VIEW v_tr_oth AS
SELECT f.version_id, b.lei AS lei_code, b.country_code AS nsa,
       to_char(v.period_end, 'YYYYMM') AS period, i.std_code AS item, i.label,
       f.assets_fv, f.assets_stages, f.exposure, f.financial_instruments,
       f.amount, f.fin_end_year, f.n_quarters, f.footnote,
       f.source_row AS row, f.source_column AS column, f.source_sheet AS sheet
FROM fact_oth f
JOIN dataset_version v USING (version_id)
JOIN bank b USING (bank_id)
JOIN indicator i USING (indicator_id)
WHERE v.is_active;

CREATE OR REPLACE VIEW v_tr_cre AS
SELECT f.version_id, b.lei AS lei_code, b.country_code AS nsa,
       to_char(v.period_end, 'YYYYMM') AS period, i.std_code AS item, i.label,
       f.portfolio, f.country, f.country_rank, f.exposure, f.status,
       f.perf_status, f.nace_codes, f.amount, f.footnote,
       f.source_row AS row, f.source_column AS column, f.source_sheet AS sheet
FROM fact_cre f
JOIN dataset_version v USING (version_id)
JOIN bank b USING (bank_id)
JOIN indicator i USING (indicator_id)
WHERE v.is_active;

CREATE OR REPLACE VIEW v_tr_mrk AS
SELECT f.version_id, b.lei AS lei_code, b.country_code AS nsa,
       to_char(v.period_end, 'YYYYMM') AS period, i.std_code AS item, i.label,
       f.portfolio, f.mkt_modprod, f.mkt_risk, f.amount, f.footnote,
       f.source_row AS row, f.source_column AS column, f.source_sheet AS sheet
FROM fact_mrk f
JOIN dataset_version v USING (version_id)
JOIN bank b USING (bank_id)
JOIN indicator i USING (indicator_id)
WHERE v.is_active;
