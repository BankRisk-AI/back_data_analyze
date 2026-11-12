DO $$
DECLARE
  duplicate_groups bigint;
BEGIN
  SELECT count(*) INTO duplicate_groups
  FROM (
    SELECT version_id, bank_id, indicator_id, assets_fv, assets_stages, exposure,
           financial_instruments, fin_end_year, n_quarters
    FROM fact_oth
    GROUP BY version_id, bank_id, indicator_id, assets_fv, assets_stages, exposure,
             financial_instruments, fin_end_year, n_quarters
    HAVING count(*) > 1
  ) duplicates;
  IF duplicate_groups > 0 THEN
    RAISE EXCEPTION 'fact_oth contains % duplicate groups; unique index not created', duplicate_groups;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS fact_oth_unique
  ON fact_oth (version_id, bank_id, indicator_id, assets_fv, assets_stages, exposure,
               financial_instruments, fin_end_year, n_quarters) NULLS NOT DISTINCT;

DO $$
DECLARE
  duplicate_groups bigint;
BEGIN
  SELECT count(*) INTO duplicate_groups
  FROM (
    SELECT version_id, bank_id, indicator_id, portfolio, country, country_rank,
           exposure, status, perf_status, nace_codes
    FROM fact_cre
    GROUP BY version_id, bank_id, indicator_id, portfolio, country, country_rank,
             exposure, status, perf_status, nace_codes
    HAVING count(*) > 1
  ) duplicates;
  IF duplicate_groups > 0 THEN
    RAISE EXCEPTION 'fact_cre contains % duplicate groups; unique index not created', duplicate_groups;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS fact_cre_unique
  ON fact_cre (version_id, bank_id, indicator_id, portfolio, country, country_rank,
               exposure, status, perf_status, nace_codes) NULLS NOT DISTINCT;

DO $$
DECLARE
  duplicate_groups bigint;
BEGIN
  SELECT count(*) INTO duplicate_groups
  FROM (
    SELECT version_id, bank_id, indicator_id, portfolio, mkt_modprod, mkt_risk
    FROM fact_mrk
    GROUP BY version_id, bank_id, indicator_id, portfolio, mkt_modprod, mkt_risk
    HAVING count(*) > 1
  ) duplicates;
  IF duplicate_groups > 0 THEN
    RAISE EXCEPTION 'fact_mrk contains % duplicate groups; unique index not created', duplicate_groups;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS fact_mrk_unique
  ON fact_mrk (version_id, bank_id, indicator_id, portfolio, mkt_modprod, mkt_risk)
  NULLS NOT DISTINCT;
