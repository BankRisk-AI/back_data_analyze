UPDATE job SET kind = 'stage' WHERE kind = 'validate';
ALTER TABLE job DROP CONSTRAINT IF EXISTS job_kind_check;
