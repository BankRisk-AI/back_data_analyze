-- Job columns used by the worker, the heartbeat that protects long jobs from being requeued, and module-defined job kinds.
-- Idempotent: it also upgrades databases created with the earlier job states (running/done).
ALTER TABLE job ADD COLUMN IF NOT EXISTS progress integer NOT NULL DEFAULT 0;
ALTER TABLE job ADD COLUMN IF NOT EXISTS message text;
ALTER TABLE job ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE job ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz;
ALTER TABLE job DROP CONSTRAINT IF EXISTS job_status_check;
UPDATE job SET status = 'processing' WHERE status = 'running';
UPDATE job SET status = 'completed' WHERE status = 'done';
ALTER TABLE job ADD CONSTRAINT job_status_check CHECK (status IN ('pending', 'processing', 'completed', 'failed'));
ALTER TABLE job DROP CONSTRAINT IF EXISTS job_kind_check;
CREATE INDEX IF NOT EXISTS job_import_kind ON job (import_id, kind, job_id DESC);
