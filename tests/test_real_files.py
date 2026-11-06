"""Integration test on the ORIGINAL 2020 EBA files. Skipped when the folder is not available (set EBA_REAL_DIR)."""
import os, pytest
from app.modules.eba_ingest import ingest
REAL = os.environ.get("EBA_REAL_DIR", "/mnt/user-data/uploads")
FILES = ["tr_oth_2.csv", "tr_cre_2.csv", "tr_mrk_2.csv", "SDD_2.xlsx", "TR_Metadata_2.xlsx"]
pytestmark = pytest.mark.skipif(not all(os.path.exists(os.path.join(REAL, f)) for f in FILES), reason="original EBA files not found")

def test_original_2020_files(db):
    r = ingest([os.path.join(REAL, f) for f in FILES], db.storage, user_id=1, edition_label="2020", schema=db.schema)
    assert r.status == "uploaded" and all(f.recognised for f in r.files)
    by = {f.file_type: f for f in r.files}
    assert {k: by[k].encoding for k in ("tr_oth", "tr_cre", "tr_mrk")} == {"tr_oth": "cp1252", "tr_cre": "cp1252", "tr_mrk": "cp1252"}   # the files are not UTF-8
    assert by["tr_cre"].rows == 396232 and by["tr_cre"].aggregate_rows == 3954 and by["tr_oth"].aggregate_rows == 422 and by["tr_mrk"].aggregate_rows == 102
    assert by["tr_oth"].rows - by["tr_oth"].aggregate_rows == 53104 and by["tr_mrk"].rows - by["tr_mrk"].aggregate_rows == 13566 and by["tr_cre"].rows - by["tr_cre"].aggregate_rows == 392278
    assert [(p.year, p.quarter, p.banks) for p in by["tr_oth"].pairs] == [(2020, 1, 131), (2020, 2, 135)]
    assert [(p.rows) for p in by["tr_cre"].pairs] == [182195, 210083]
    db.cur.execute("SELECT count(*) FROM source_file WHERE length(sha256) = 64 AND stored_path IS NOT NULL"); assert db.cur.fetchone()[0] == 5
    assert r.seconds < 60
