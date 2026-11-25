"""Alert table: upsert the alerts of a profile, delete the vanished ones, read what is stored."""
from __future__ import annotations

from typing import Any

from psycopg2.extras import Json

UPSERT = """INSERT INTO alert (bank_id, version_id, profile_name, profile_sha256, score, level, rule_results)
    VALUES (%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (profile_sha256, version_id, bank_id) DO UPDATE
    SET profile_name=EXCLUDED.profile_name, score=EXCLUDED.score, level=EXCLUDED.level,
        rule_results=EXCLUDED.rule_results, created_at=now()"""


def replace_alerts(cur, profile_name: str, profile_sha256: str, results: list[dict[str, Any]]) -> None:
    """Upsert on (profile sha, dataset version, bank): alert_ids of existing rows are kept.

    Rows of this profile sha that are no longer produced (bank or version gone) are deleted.
    """
    for result in results:
        cur.execute(UPSERT, (result["bank_id"], result["dataset_version"], profile_name, profile_sha256,
                             result["score"], result["level"], Json(result["rule_results"])))
    keep_versions = [r["dataset_version"] for r in results]
    keep_banks = [r["bank_id"] for r in results]
    cur.execute("""DELETE FROM alert WHERE profile_sha256=%s AND (version_id, bank_id) NOT IN
                   (SELECT * FROM unnest(%s::int[], %s::int[]))""",
                (profile_sha256, keep_versions, keep_banks))


def stored_alerts(cur, profile_sha256: str) -> dict[tuple, tuple]:
    """{(bank_id, version_id): (level, score, rule_results)} stored for a profile sha."""
    cur.execute("SELECT bank_id, version_id, level, score, rule_results FROM alert WHERE profile_sha256=%s",
                (profile_sha256,))
    return {(b, v): (level, score, payload) for b, v, level, score, payload in cur.fetchall()}
