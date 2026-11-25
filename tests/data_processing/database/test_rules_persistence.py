
from psycopg2.extras import Json

from app.modules.eba_rules.public import evaluate_panel


def test_persisted_alerts_are_idempotent(db, tmp_path):
    db.cur.execute("INSERT INTO import_batch(status) VALUES ('loaded') RETURNING import_id")
    import_id = db.cur.fetchone()[0]
    db.cur.execute(
        "INSERT INTO bank(lei, name, country_code) VALUES (%s,%s,%s) RETURNING bank_id",
        ("54930000000000000001", "Synthetic Bank", "XX"),
    )
    bank_id = db.cur.fetchone()[0]
    db.cur.execute(
        """INSERT INTO dataset_version(year, quarter, period_end, import_id, version_no, is_active)
           VALUES (2025, 2, '2025-06-30', %s, 1, true) RETURNING version_id""",
        (import_id,),
    )
    version_id = db.cur.fetchone()[0]
    db.cur.execute(
        """INSERT INTO panel_row(version_id, bank_id, cet1_ratio, flags)
           VALUES (%s,%s,%s,%s)""",
        (version_id, bank_id, 0.03, Json({})),
    )
    evaluate_panel(db.conn, "eu_eba")
    db.cur.execute("SELECT alert_id FROM alert")
    first_id = db.cur.fetchone()[0]
    evaluate_panel(db.conn, "eu_eba")
    db.cur.execute("SELECT count(*), count(distinct profile_sha256), min(alert_id) FROM alert")
    assert db.cur.fetchone() == (1, 1, first_id)               # upsert: the alert keeps its id
    db.cur.execute("DELETE FROM panel_row")
    evaluate_panel(db.conn, "eu_eba")
    db.cur.execute("SELECT count(*) FROM alert")
    assert db.cur.fetchone()[0] == 0                           # rows that no longer exist are deleted
