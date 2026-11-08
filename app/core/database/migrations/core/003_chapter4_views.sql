-- Chapter 4 file-shaped views.  They do not add or alter application tables.
CREATE OR REPLACE VIEW v_tr_oth AS
SELECT f.version_id, b.lei AS lei_code, b.country_code AS nsa,
       to_char(v.period_end, 'YYYYMM') AS period, i.std_code AS item, i.label,
       f.assets_fv, f.assets_stages, f.exposure, f.financial_instruments,
       f.amount, f.fin_end_year, f.n_quarters, f.footnote
FROM fact_oth f
JOIN dataset_version v USING (version_id)
JOIN bank b USING (bank_id)
JOIN indicator i USING (indicator_id)
WHERE v.is_active;

CREATE OR REPLACE VIEW v_tr_cre AS
SELECT f.version_id, b.lei AS lei_code, b.country_code AS nsa,
       to_char(v.period_end, 'YYYYMM') AS period, i.std_code AS item, i.label,
       f.portfolio, f.country, f.country_rank, f.exposure, f.status,
       f.perf_status, f.nace_codes, f.amount, f.footnote
FROM fact_cre f
JOIN dataset_version v USING (version_id)
JOIN bank b USING (bank_id)
JOIN indicator i USING (indicator_id)
WHERE v.is_active;

CREATE OR REPLACE VIEW v_tr_mrk AS
SELECT f.version_id, b.lei AS lei_code, b.country_code AS nsa,
       to_char(v.period_end, 'YYYYMM') AS period, i.std_code AS item, i.label,
       f.portfolio, f.mkt_modprod, f.mkt_risk, f.amount, f.footnote
FROM fact_mrk f
JOIN dataset_version v USING (version_id)
JOIN bank b USING (bank_id)
JOIN indicator i USING (indicator_id)
WHERE v.is_active;
