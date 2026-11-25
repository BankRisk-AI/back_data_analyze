"""Alert table: read the active panel, replace the alerts of a profile, query for the API."""
from __future__ import annotations

from typing import Any

from psycopg2.extras import Json

PANEL_QUERY = """SELECT p.version_id, p.bank_id, v.period_end AS period,
    p.cet1_ratio, p.tier1_ratio, p.total_capital_ratio, p.leverage_ratio,
    p.npl_ratio, p.stage2_share, p.roe_annualised, p.nace_hhi,
    p.sovereign_hhi, p.loan_growth_qoq, p.loan_growth_yoy, p.flags
    FROM panel_row p JOIN dataset_version v USING (version_id)
    WHERE v.is_active ORDER BY v.period_end, p.bank_id"""


def fetch_active_panel(cur) -> list[dict[str, Any]]:
    """Panel rows of every active dataset version as dicts (period = period_end)."""
    cur.execute(PANEL_QUERY)
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, values)) for values in cur.fetchall()]


def replace_alerts(cur, profile_name: str, profile_sha256: str, results: list[dict[str, Any]]) -> None:
    """Delete the alerts of this profile sha and insert the new results."""
    cur.execute("DELETE FROM alert WHERE profile_sha256=%s", (profile_sha256,))
    for result in results:
        cur.execute("""INSERT INTO alert
            (bank_id, version_id, profile_name, profile_sha256, score, level, rule_results)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""", (
            result["bank_id"], result["version_id"], profile_name, profile_sha256,
            result["score"], result["level"], Json(result["rule_results"])))


def stored_alerts(cur, profile_sha256: str) -> dict[tuple, tuple]:
    """{(bank_id, version_id): (level, score, rule_results)} stored for a profile sha."""
    cur.execute("SELECT bank_id, version_id, level, score, rule_results FROM alert WHERE profile_sha256=%s",
                (profile_sha256,))
    return {(b, v): (level, score, payload) for b, v, level, score, payload in cur.fetchall()}
