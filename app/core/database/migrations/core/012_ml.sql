-- Stage 5e-1: eba_ml registry. Four tables; audit uses the existing audit_log.
CREATE TABLE IF NOT EXISTS ml_dataset (
  dataset_id serial PRIMARY KEY,
  target text NOT NULL,
  grid text NOT NULL,
  feature_set text NOT NULL,
  panel_hash char(64) NOT NULL,
  content_hash char(64) NOT NULL UNIQUE,
  manifest jsonb NOT NULL,
  row_count integer NOT NULL CHECK (row_count >= 0),
  status text NOT NULL CHECK (status IN ('building','ready','failed')),
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ml_dataset_target_grid ON ml_dataset (target, grid);

CREATE TABLE IF NOT EXISTS ml_experiment (
  experiment_id serial PRIMARY KEY,
  dataset_id integer NOT NULL REFERENCES ml_dataset(dataset_id) ON DELETE RESTRICT,
  config jsonb NOT NULL,
  seed bigint NOT NULL,
  folds jsonb NOT NULL,
  budget integer NOT NULL CHECK (budget > 0),
  status text NOT NULL CHECK (status IN ('queued','running','completed','cancelled','failed')),
  progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  metrics jsonb,
  artifact_refs jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ml_experiment_dataset ON ml_experiment (dataset_id, created_at);

CREATE TABLE IF NOT EXISTS ml_model (
  model_id serial PRIMARY KEY,
  experiment_id integer NOT NULL REFERENCES ml_experiment(experiment_id) ON DELETE RESTRICT,
  name text NOT NULL,
  target text NOT NULL,
  grid text NOT NULL,
  algorithm text NOT NULL,
  hyperparameters jsonb NOT NULL,
  artifact_sha256 char(64) NOT NULL,
  model_card jsonb NOT NULL,
  status text NOT NULL CHECK (status IN ('training','trained','validated','champion','archived','failed')),
  protected boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name));
CREATE UNIQUE INDEX IF NOT EXISTS one_ml_champion_per_target_grid
  ON ml_model (target, grid) WHERE status = 'champion';
CREATE INDEX IF NOT EXISTS ml_model_experiment ON ml_model (experiment_id);
CREATE INDEX IF NOT EXISTS ml_model_artifact ON ml_model (artifact_sha256);

CREATE TABLE IF NOT EXISTS ml_prediction (
  prediction_id bigserial PRIMARY KEY,
  model_id integer NOT NULL REFERENCES ml_model(model_id) ON DELETE CASCADE,
  version_id integer NOT NULL REFERENCES dataset_version(version_id) ON DELETE RESTRICT,
  bank_id integer NOT NULL REFERENCES bank(bank_id) ON DELETE RESTRICT,
  period_end date NOT NULL,
  threshold_setting text NOT NULL CHECK (threshold_setting IN ('matched_far','max_ur_0_9')),
  probability double precision NOT NULL CHECK (probability BETWEEN 0 AND 1),
  alert boolean NOT NULL,
  shap jsonb,
  UNIQUE (model_id, bank_id, period_end, threshold_setting));
CREATE INDEX IF NOT EXISTS ml_prediction_period ON ml_prediction (period_end, bank_id);
CREATE INDEX IF NOT EXISTS ml_prediction_model ON ml_prediction (model_id);

ALTER TABLE job ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false;
ALTER TABLE ml_dataset ADD COLUMN IF NOT EXISTS protected boolean NOT NULL DEFAULT false;
ALTER TABLE ml_experiment ADD COLUMN IF NOT EXISTS protected boolean NOT NULL DEFAULT false;
