import psycopg2
import pytest
from psycopg2 import sql

from app.core.database import connect, migrate
from app.core.database.migrator import CORE_DIR, discover


@pytest.fixture()
def schema(db):
    name = "mig_test"
    db.cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
    db.cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    yield name
    db.cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def query(schema, text, params=()):
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(text, params)
            return cur.fetchall() if cur.description else None
    finally:
        conn.close()


def test_a_new_database_gets_every_migration_once(schema):
    assert migrate(schema) == ["core/001_baseline", "core/002_job_heartbeat"]
    assert migrate(schema) == []                                                              # idempotent
    assert [r[0] for r in query(schema, "SELECT version FROM schema_migrations ORDER BY version")] == ["core/001_baseline", "core/002_job_heartbeat"]
    cols = {r[0] for r in query(schema, "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'job'", (schema,))}
    assert {"progress", "message", "started_at", "heartbeat_at", "error"} <= cols


def test_modules_may_define_their_own_job_kinds_after_migration(schema):
    migrate(schema)
    query(schema, "INSERT INTO import_batch(status) VALUES ('uploaded')")
    query(schema, "INSERT INTO job(import_id, kind) VALUES (1, 'a_kind_a_module_invented')")           # the old CHECK would refuse this
    assert query(schema, "SELECT kind FROM job") == [("a_kind_a_module_invented",)]


def test_a_database_created_before_migrations_existed_is_adopted_not_recreated(schema):
    conn = connect(schema)
    with conn, conn.cursor() as cur:
        cur.execute((CORE_DIR / "001_baseline.sql").read_text(encoding="utf-8"))                      # as the old init_db did
        cur.execute("INSERT INTO import_batch(status) VALUES ('uploaded')")
    conn.close()
    assert migrate(schema) == ["core/002_job_heartbeat"]                                              # 001 is recorded, not run again (it would fail)
    assert query(schema, "SELECT count(*) FROM import_batch") == [(1,)]                               # data kept


def test_old_job_states_are_converted(schema):
    conn = connect(schema)
    with conn, conn.cursor() as cur:
        cur.execute((CORE_DIR / "001_baseline.sql").read_text(encoding="utf-8"))
        cur.execute("ALTER TABLE job DROP CONSTRAINT job_status_check")                               # a database made with the earlier job states
        cur.execute("INSERT INTO import_batch(status) VALUES ('uploaded')")
        cur.execute("INSERT INTO job(import_id, kind, status) VALUES (1, 'validate', 'done'), (1, 'validate', 'running')")
    conn.close()
    migrate(schema)
    assert sorted(r[0] for r in query(schema, "SELECT status FROM job")) == ["completed", "processing"]
    with pytest.raises(psycopg2.errors.CheckViolation):
        query(schema, "INSERT INTO job(import_id, kind, status) VALUES (1, 'validate', 'running')")


def test_module_migration_folders_are_applied_after_the_core_in_order(schema, tmp_path):
    (tmp_path / "001_extra.sql").write_text("CREATE TABLE extra_one (id int);")
    (tmp_path / "002_more.sql").write_text("ALTER TABLE extra_one ADD COLUMN note text;")
    assert [m.version for m in discover({"mymodule": tmp_path})][-2:] == ["mymodule/001_extra", "mymodule/002_more"]
    assert migrate(schema, {"mymodule": tmp_path})[-2:] == ["mymodule/001_extra", "mymodule/002_more"]
    assert query(schema, "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'extra_one' ORDER BY 1", (schema,)) == [("id",), ("note",)]


def test_a_failing_migration_leaves_nothing_half_applied(schema, tmp_path):
    migrate(schema)
    (tmp_path / "001_bad.sql").write_text("CREATE TABLE half (id int); SELECT 1 / 0;")
    with pytest.raises(psycopg2.errors.DivisionByZero):
        migrate(schema, {"bad": tmp_path})
    assert query(schema, "SELECT to_regclass(%s) IS NULL", (f"{schema}.half",)) == [(True,)]
    assert "bad/001_bad" not in {r[0] for r in query(schema, "SELECT version FROM schema_migrations")}
