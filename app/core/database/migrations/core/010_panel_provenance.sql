ALTER TABLE panel_row
  ADD COLUMN IF NOT EXISTS build_provenance jsonb;
