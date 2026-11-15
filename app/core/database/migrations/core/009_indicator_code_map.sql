ALTER TABLE indicator ADD COLUMN IF NOT EXISTS first_seen_edition text;
ALTER TABLE indicator ADD COLUMN IF NOT EXISTS last_seen_edition text;

CREATE TABLE IF NOT EXISTS indicator_code_map (
  edition_label text NOT NULL,
  dataset text NOT NULL CHECK (dataset IN ('oth', 'cre', 'mrk', 'sov')),
  source_item text NOT NULL,
  source_label text,
  indicator_id integer REFERENCES indicator(indicator_id),
  method text NOT NULL CHECK (method IN ('sdd_chain', 'sdd_direct', 'unmapped')),
  sdd_file_sha256 char(64),
  PRIMARY KEY (edition_label, dataset, source_item)
);

DO $$
DECLARE duplicate_groups bigint;
BEGIN
  SELECT count(*) INTO duplicate_groups
  FROM (
    SELECT edition_label, dataset, source_item
    FROM indicator_code_map
    GROUP BY edition_label, dataset, source_item
    HAVING count(*) > 1
  ) duplicates;
  IF duplicate_groups > 0 THEN
    RAISE EXCEPTION 'indicator_code_map contains % duplicate groups', duplicate_groups;
  END IF;
END $$;
