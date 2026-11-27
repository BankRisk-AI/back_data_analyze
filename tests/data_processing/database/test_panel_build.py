"""build_panel end to end on a tiny synthetic fact set: ratios, NPL, RoCET1, specialist flag, rebuild."""
from datetime import date

import pytest
import yaml

from app.core.panel import build_panel

ITEMS = {  # std_code -> (file_group, aggregation_rule)
    "2520140": ("oth", "ratio"), "2520141": ("oth", "ratio"), "2520142": ("oth", "ratio"),
    "2520905": ("oth", "ratio"), "2520335": ("oth", "flow"), "2520102": ("oth", "stock"),
    "2520901": ("oth", "ratio"), "2520903": ("oth", "ratio"), "2521017": ("oth", "stock"),
    "2521019": ("oth", "stock"), "2520603": ("cre", "stock"), "2521301": ("cre", "stock"),
    "1820802": ("sov", "stock"), "1820810": ("sov", "stock"), "2520810": ("sov", "stock"),
}
LEIS = {"normal": "SYNTHETICPANEL000001", "special": "SYNTHETICPANEL000002"}


def _seed(cur) -> dict:
    cur.execute("INSERT INTO import_batch(status, edition_label) VALUES ('loaded','T1') RETURNING import_id")
    import_id = cur.fetchone()[0]
    banks = {}
    for key, lei in LEIS.items():
        cur.execute("INSERT INTO bank(lei, name) VALUES (%s,%s) RETURNING bank_id", (lei, key))
        banks[key] = cur.fetchone()[0]
    ids = {}
    for code, (group, rule) in ITEMS.items():
        cur.execute("""INSERT INTO indicator(std_code,label,report_type,file_group,aggregation_rule)
                       VALUES (%s,%s,'T',%s,%s) ON CONFLICT (std_code) DO UPDATE SET label=EXCLUDED.label
                       RETURNING indicator_id""", (code, code, group, rule))
        ids[code] = cur.fetchone()[0]
    versions = {}
    for quarter, period in ((4, date(2019, 12, 31)), (2, date(2020, 6, 30))):
        cur.execute("""INSERT INTO dataset_version(year,quarter,period_end,import_id,version_no,is_active)
                       VALUES (%s,%s,%s,%s,1,true) RETURNING version_id""",
                    (period.year, quarter, period, import_id))
        versions[period] = cur.fetchone()[0]
    return {"banks": banks, "ids": ids, "versions": versions}


def _facts(cur, s: dict) -> None:
    for period, version in s["versions"].items():
        n_quarters = 4 if period.month == 12 else 2
        for bank in s["banks"].values():
            for code, value in (("2520140", 0.14), ("2520141", 0.16), ("2520142", 0.19),
                                ("2520905", 0.05), ("2520335", 100.0), ("2520102", 1000.0)):
                cur.execute("""INSERT INTO fact_oth(version_id,bank_id,indicator_id,amount,n_quarters,fin_end_year)
                               VALUES (%s,%s,%s,%s,%s,'0')""",
                            (version, bank, s["ids"][code], value, n_quarters))
            for perf, amount in (("0", 200.0), ("2", 20.0)):
                cur.execute("""INSERT INTO fact_cre(version_id,bank_id,indicator_id,portfolio,country,country_rank,
                               exposure,status,perf_status,amount) VALUES (%s,%s,%s,'0','0','0','0','0',%s,%s)""",
                            (version, bank, s["ids"]["2520603"], perf, amount))


def test_build_panel_end_to_end(db, tmp_path):
    seeded = _seed(db.cur)
    _facts(db.cur, seeded)
    dimensions, config = tmp_path / "dimensions", tmp_path / "config"
    dimensions.mkdir(); config.mkdir()
    (config / "ml.yaml").write_text("loan_series_break: \"2020-06-30\"\n")
    (dimensions / "T1.yaml").write_text(yaml.safe_dump({"status": "decoded", "dimensions": {"Perf_status": {
        "0": {"label": "No breakdown by Perf_status"}, "2": {"label": "Non Performing"}}}}))
    (config / "specialist_institutions.yaml").write_text(yaml.safe_dump([{"lei": LEIS["special"], "name": "s"}]))
    try:
        assert build_panel(db.conn, dimensions, config, run_hooks=False) == 4
        db.cur.execute("""SELECT b.name, v.period_end, p.cet1_ratio, p.npl_ratio, p.roe_annualised, p.flags
                          FROM panel_row p JOIN bank b USING(bank_id) JOIN dataset_version v USING(version_id)
                          ORDER BY 2, 1""")
        rows = {(name, period): rest for name, period, *rest in db.cur.fetchall()}
        cet1, npl, roe, flags = rows[("normal", date(2020, 6, 30))]
        assert (cet1, npl) == (0.14, 0.1)
        assert roe == 100.0 * 4 / 2 / 1000.0                       # n_quarters=2 -> annualised x2
        assert rows[("normal", date(2019, 12, 31))][2] == 0.1      # n_quarters=4
        assert "specialist_institution" in rows[("special", date(2020, 6, 30))][3]["cet1_ratio"]
        assert "specialist_institution" not in rows[("normal", date(2020, 6, 30))][3].get("cet1_ratio", [])
        assert build_panel(db.conn, dimensions, config, run_hooks=False) == 4       # rebuild replaces, does not duplicate
    finally:
        db.cur.execute("TRUNCATE panel_row")
        db.cur.execute("TRUNCATE import_batch CASCADE")
        db.cur.execute("DELETE FROM bank WHERE lei LIKE 'SYNTHETICPANEL%'")


def _setup_hook_environment(db, tmp_path, monkeypatch):
    """Seed facts + a champion model, register the module hooks in a clean registry."""
    from app.core import hooks
    from app.modules import MODULES
    seeded = _seed(db.cur)
    _facts(db.cur, seeded)
    dimensions, config = tmp_path / "dimensions", tmp_path / "config"
    dimensions.mkdir(); config.mkdir()
    (config / "ml.yaml").write_text("loan_series_break: \"2020-06-30\"\n")
    (dimensions / "T1.yaml").write_text(yaml.safe_dump({"status": "decoded", "dimensions": {"Perf_status": {
        "0": {"label": "No breakdown by Perf_status"}, "2": {"label": "Non Performing"}}}}))
    db.cur.execute("""INSERT INTO ml_dataset(target,grid,feature_set,panel_hash,content_hash,manifest,row_count,status)
                      VALUES ('E2_or_E3','semiannual','robustness_v1',%s,%s,'{}',1,'ready') RETURNING dataset_id""",
                   ("0" * 64, "1" * 64))
    dataset_id = db.cur.fetchone()[0]
    db.cur.execute("""INSERT INTO ml_experiment(dataset_id,config,seed,folds,budget,status)
                      VALUES (%s,'{}',1,'[]',1,'completed') RETURNING experiment_id""", (dataset_id,))
    db.cur.execute("""INSERT INTO ml_model(experiment_id,name,target,grid,algorithm,hyperparameters,artifact_sha256,
                      model_card,status) VALUES (%s,'hook-champion','E2_or_E3','semiannual','LR','{}',%s,'{}','champion')
                      RETURNING model_id""", (db.cur.fetchone()[0], "2" * 64))
    seeded["model_id"] = db.cur.fetchone()[0]
    monkeypatch.setattr(hooks, "_HOOKS", {})
    hooks.register_module_hooks(MODULES)
    return dimensions, config, seeded


def _cleanup(db):
    db.cur.execute("TRUNCATE ml_prediction, ml_model, ml_experiment, ml_dataset CASCADE")
    db.cur.execute("TRUNCATE panel_row")
    db.cur.execute("TRUNCATE import_batch CASCADE")
    db.cur.execute("DELETE FROM bank WHERE lei LIKE 'SYNTHETICPANEL%'")


def test_a_panel_rebuild_runs_the_hooks_fresh_alerts_and_a_queued_score_job(db, tmp_path, monkeypatch):
    from app.core import hooks
    from app.modules.eba_rules.public import load_profile
    dimensions, config, seeded = _setup_hook_environment(db, tmp_path, monkeypatch)
    try:
        assert hooks.registered_hooks() == ["eba_rules", "eba_ml"] or set(hooks.registered_hooks()) == {"eba_rules", "eba_ml"}
        assert build_panel(db.conn, dimensions, config) == 4
        sha = load_profile("eu_eba")[1]
        db.cur.execute("SELECT count(*) FROM alert WHERE profile_sha256=%s", (sha,))
        assert db.cur.fetchone()[0] == 4                       # fresh alerts for the active profile
        db.cur.execute("SELECT kind, status, message FROM job WHERE kind='score_panel'")
        assert db.cur.fetchall() == [("score_panel", "pending", f"score_panel model={seeded['model_id']}")]
        db.cur.execute("SELECT alert_id FROM alert WHERE profile_sha256=%s ORDER BY alert_id", (sha,))
        first_ids = db.cur.fetchall()
        build_panel(db.conn, dimensions, config)                # rebuild: same inputs -> same alert_ids
        db.cur.execute("SELECT alert_id FROM alert WHERE profile_sha256=%s ORDER BY alert_id", (sha,))
        assert db.cur.fetchall() == first_ids
    finally:
        _cleanup(db)


def test_a_failing_hook_does_not_stop_the_others_and_is_reported(db, tmp_path, monkeypatch):
    from app.core import hooks
    dimensions, config, _ = _setup_hook_environment(db, tmp_path, monkeypatch)
    calls = []
    hooks.register_after_panel_rebuild("a-broken", lambda conn, event: (_ for _ in ()).throw(RuntimeError("boom")))
    hooks.register_after_panel_rebuild("z-last", lambda conn, event: calls.append(event.rows))
    try:
        with pytest.raises(hooks.PanelHookError, match="a-broken: boom"):
            build_panel(db.conn, dimensions, config)
        assert calls == [4]                                     # later hook still ran
        db.cur.execute("SELECT count(*) FROM panel_row")
        assert db.cur.fetchone()[0] == 4                        # the panel itself is committed
    finally:
        _cleanup(db)
