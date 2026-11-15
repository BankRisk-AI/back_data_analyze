CREATE TABLE IF NOT EXISTS fact_sov (
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
CREATE INDEX IF NOT EXISTS fact_sov_version_indicator_bank
  ON fact_sov (version_id, indicator_id, bank_id);

DO $$
DECLARE
  duplicate_groups bigint;
BEGIN
  SELECT count(*) INTO duplicate_groups
  FROM (
    SELECT version_id, bank_id, indicator_id, country, accounting_portfolio, maturity
    FROM fact_sov
    GROUP BY version_id, bank_id, indicator_id, country, accounting_portfolio, maturity
    HAVING count(*) > 1
  ) duplicates;
  IF duplicate_groups > 0 THEN
    RAISE EXCEPTION 'fact_sov contains % duplicate groups; unique index not created', duplicate_groups;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS fact_sov_identity
  ON fact_sov (version_id, bank_id, indicator_id, country, accounting_portfolio, maturity)
  NULLS NOT DISTINCT;

CREATE OR REPLACE VIEW v_tr_sov AS
SELECT f.version_id, b.lei AS lei_code, f.nsa,
       to_char(v.period_end, 'YYYYMM') AS period, i.std_code AS item, i.label,
       f.country, f.accounting_portfolio, f.maturity, f.amount, f.footnote,
       f.source_row AS row, f.source_column AS column, f.source_sheet AS sheet
FROM fact_sov f
JOIN dataset_version v USING (version_id)
JOIN bank b USING (bank_id)
JOIN indicator i USING (indicator_id)
WHERE v.is_active;
