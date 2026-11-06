-- EBA Data Explorer: logical schema, 13 tables (PostgreSQL 16).
-- Reduced from the first design (20 tables): reporting_period, bank_lei_history, report_type, indicator_code_map,
-- quality_check and outlier_flag were folded into other tables; fact_sov is created after tr_sov is inspected.

-- Users and audit ------------------------------------------------------------------------
CREATE TABLE app_user (
  user_id       serial PRIMARY KEY,
  username      text UNIQUE NOT NULL,
  password_hash text NOT NULL,
  role          text NOT NULL CHECK (role IN ('analyst', 'administrator')),
  created_at    timestamptz NOT NULL DEFAULT now());

CREATE TABLE audit_log (
  audit_id  bigserial PRIMARY KEY,
  user_id   integer REFERENCES app_user (user_id),
  action    text NOT NULL,
  entity    text,
  entity_id text,
  detail    jsonb,
  at        timestamptz NOT NULL DEFAULT now());

-- Reference data ---------------------------------------------------------------------------
CREATE TABLE bank (
  bank_id         serial PRIMARY KEY,
  lei             char(20) UNIQUE NOT NULL,            -- current LEI
  name            text,
  country_code    char(2),
  finrep_reported boolean,
  previous_leis   char(20)[] NOT NULL DEFAULT '{}');   -- LEI history (crosswalk of TR_Metadata)
CREATE INDEX bank_previous_leis_gin ON bank USING gin (previous_leis);

CREATE TABLE indicator (
  indicator_id     serial PRIMARY KEY,
  std_code         text UNIQUE NOT NULL,               -- item code of the 2020 edition
  label            text NOT NULL,
  report_type      text NOT NULL,                      -- category of the SDD, e.g. CAPITAL, NPE, NACE
  file_group       text NOT NULL CHECK (file_group IN ('oth', 'cre', 'mrk', 'sov')),
  aggregation_rule text NOT NULL CHECK (aggregation_rule IN ('stock', 'flow', 'ratio', 'count')),
  unit             text);
CREATE INDEX indicator_report_type ON indicator (report_type);

-- Lineage ------------------------------------------------------------------------------------
CREATE TABLE import_batch (
  import_id     serial PRIMARY KEY,
  status        text NOT NULL CHECK (status IN ('uploaded','validating','validated','approved','loading','loaded','rejected','cancelled','failed')),
  edition_label text,
  created_by    integer REFERENCES app_user (user_id),
  created_at    timestamptz NOT NULL DEFAULT now());

CREATE TABLE source_file (
  file_id     serial PRIMARY KEY,
  import_id   integer NOT NULL REFERENCES import_batch (import_id),
  file_name   text NOT NULL,
  size_bytes  bigint NOT NULL,
  sha256      char(64) NOT NULL,
  file_type   text,
  encoding    text,
  stored_path text,
  UNIQUE (import_id, sha256));
CREATE INDEX source_file_sha256 ON source_file (sha256);

CREATE TABLE job (
  job_id      serial PRIMARY KEY,
  import_id   integer NOT NULL REFERENCES import_batch (import_id),
  kind        text NOT NULL CHECK (kind IN ('validate', 'load')),
  status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
  progress   integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  message    text,
  error       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  started_at  timestamptz,
  finished_at timestamptz);
CREATE INDEX job_pending ON job (created_at) WHERE status = 'pending';

CREATE TABLE decision_log (            -- also records how every item was resolved (SDD or label), step = 'item_resolution'
  log_id     bigserial PRIMARY KEY,
  import_id  integer NOT NULL REFERENCES import_batch (import_id),
  step       text NOT NULL,
  detail     jsonb,
  created_at timestamptz NOT NULL DEFAULT now());

-- Data ----------------------------------------------------------------------------------------
CREATE TABLE dataset_version (
  version_id serial PRIMARY KEY,
  year       smallint NOT NULL,
  quarter    smallint NOT NULL CHECK (quarter BETWEEN 1 AND 4),
  period_end date NOT NULL,
  import_id  integer NOT NULL REFERENCES import_batch (import_id),
  version_no integer NOT NULL,
  is_active  boolean NOT NULL DEFAULT false,
  quality    jsonb,                      -- quality report: checks, missing values
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (year, quarter, version_no));
CREATE UNIQUE INDEX one_active_version_per_quarter ON dataset_version (year, quarter) WHERE is_active;

CREATE TABLE fact_oth (
  version_id integer NOT NULL REFERENCES dataset_version (version_id) ON DELETE CASCADE,
  bank_id integer NOT NULL REFERENCES bank (bank_id),
  indicator_id integer NOT NULL REFERENCES indicator (indicator_id),
  assets_fv text, assets_stages text, exposure text, financial_instruments text, fin_end_year text,
  n_quarters smallint, amount double precision, footnote text);
CREATE INDEX ON fact_oth (version_id, indicator_id, bank_id);

CREATE TABLE fact_cre (
  version_id integer NOT NULL REFERENCES dataset_version (version_id) ON DELETE CASCADE,
  bank_id integer NOT NULL REFERENCES bank (bank_id),
  indicator_id integer NOT NULL REFERENCES indicator (indicator_id),
  portfolio text, country text, country_rank text, exposure text, status text, perf_status text, nace_codes text,
  amount double precision, footnote text);
CREATE INDEX ON fact_cre (version_id, indicator_id, bank_id);

CREATE TABLE fact_mrk (
  version_id integer NOT NULL REFERENCES dataset_version (version_id) ON DELETE CASCADE,
  bank_id integer NOT NULL REFERENCES bank (bank_id),
  indicator_id integer NOT NULL REFERENCES indicator (indicator_id),
  portfolio text, mkt_modprod text, mkt_risk text, amount double precision, footnote text);
CREATE INDEX ON fact_mrk (version_id, indicator_id, bank_id);

CREATE TABLE panel_row (
  version_id integer NOT NULL REFERENCES dataset_version (version_id) ON DELETE CASCADE,
  bank_id    integer NOT NULL REFERENCES bank (bank_id),
  cet1_ratio double precision, tier1_ratio double precision, total_capital_ratio double precision, leverage_ratio double precision,
  npl_ratio double precision, stage2_share double precision, roe_annualised double precision, nace_hhi double precision, sovereign_hhi double precision,
  npl_delta_qoq double precision, loan_growth_qoq double precision, loan_growth_yoy double precision, cet1_delta_qoq double precision,
  min_headroom double precision,
  indicators jsonb,                      -- remaining indicators of the dictionary
  flags jsonb,                           -- filled values and outliers: {"outliers": [{"indicator": ..., "value": ...}]}
  PRIMARY KEY (version_id, bank_id));

-- fact_sov: add after tr_sov is inspected (dimension columns unknown). Phase 2: model_*, alert.
