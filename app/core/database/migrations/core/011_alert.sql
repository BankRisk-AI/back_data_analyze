CREATE TABLE alert (
  alert_id       bigserial PRIMARY KEY,
  bank_id        integer NOT NULL REFERENCES bank (bank_id),
  version_id     integer NOT NULL REFERENCES dataset_version (version_id) ON DELETE CASCADE,
  profile_name   text NOT NULL,
  profile_sha256 char(64) NOT NULL,
  score          double precision,
  level          text NOT NULL CHECK (level IN ('green', 'amber', 'red', 'not_evaluated')),
  rule_results   jsonb NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (profile_sha256, version_id, bank_id));

CREATE INDEX alert_profile_period ON alert (profile_name, version_id);
