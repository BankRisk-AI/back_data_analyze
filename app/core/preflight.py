"""Diagnostic collision checks for staged imports."""
from __future__ import annotations

from collections import Counter

from psycopg2 import sql

from app.core.data_decisions import load_data_decisions
from app.shared.staging import staging_identifier
from app.shared.sql.predicates import NUMBER_REGEX, aggregate_rows_predicate


TARGETS = {
    "tr_oth": ("fact_oth", ("assets_fv", "assets_stages", "exposure", "financial_instruments", "fin_end_year", "n_quarters")),
    "tr_cre": ("fact_cre", ("portfolio", "country", "country_rank", "exposure", "status", "perf_status", "nace_codes")),
    "tr_mrk": ("fact_mrk", ("portfolio", "mkt_modprod", "mkt_risk")),
    "tr_sov": ("fact_sov", ("country", "accounting_portfolio", "maturity")),
}


def _exclusions(decisions, edition: str, file_type: str, columns: list[str]) -> tuple[sql.Composable, list[str]]:
    """SQL fragment ' AND NOT (...)' and its parameters for the owner exclusions of this edition and file type."""
    predicates_sql, params = [], []
    for decision in decisions:
        if decision.edition != edition or decision.file_type != file_type or decision.action != "exclude":
            continue
        predicates = {"lei_code": decision.lei, "period": decision.period, "item": decision.item,
                      **decision.dimensions}
        if decision.amount is not None:
            predicates["amount"] = decision.amount
        if not set(predicates).issubset(columns):
            continue
        predicates_sql.append(sql.SQL(" AND ").join(
            sql.SQL("btrim({}) = %s").format(sql.Identifier(column)) for column in predicates))
        params.extend(predicates.values())
    if not predicates_sql:
        return sql.SQL(""), params
    return (sql.SQL(" AND NOT (") + sql.SQL(" OR ").join(
        sql.SQL("(") + predicate + sql.SQL(")") for predicate in predicates_sql) + sql.SQL(")")), params


def _collisions_of_file(cur, file_id: int, file_name: str, file_type: str, edition: str, decisions) -> list[dict]:
    """Identities (lei, period, item, dimensions) staged more than once with different amounts."""
    table_name, dimensions = TARGETS[file_type]
    cur.execute(sql.SQL("SELECT * FROM {} LIMIT 0").format(staging_identifier(file_id)))
    columns = [d[0] for d in cur.description]
    key = ("lei_code", "period", "item", *(column for column in dimensions if column in columns))
    if not all(column in columns for column in key) or "amount" not in columns:
        return []
    identifiers = sql.SQL(", ").join(sql.Identifier(column) for column in key)
    exclusion_sql, exclusion_params = _exclusions(decisions, edition, file_type, columns)
    canonical = ("count(DISTINCT CASE WHEN btrim(amount) ~ %s "
                 "THEN btrim(amount)::numeric::text ELSE btrim(amount) END)")
    query = sql.SQL("SELECT {}, count(*) AS copies, " + canonical + " AS amounts FROM {} WHERE NOT {}{} "
                    "GROUP BY {} HAVING " + canonical + " > 1").format(
        identifiers, staging_identifier(file_id), sql.SQL(aggregate_rows_predicate()), exclusion_sql, identifiers)
    cur.execute(query, (NUMBER_REGEX, *exclusion_params, NUMBER_REGEX))
    collisions = []
    for row in cur.fetchall():
        values = dict(zip(key, row[:-2]))
        values.update({"file": file_name, "fact_table": table_name, "copies": row[-2], "amounts": row[-1]})
        values["class"] = "iii" if row[-1] > 1 else "iv"      # class iii: same identity, different amounts
        collisions.append(values)
    return collisions


def collision_check(cur, import_id: int) -> list[dict]:
    """Collisions of every staged data file of an import (empty list = safe to load)."""
    cur.execute("SELECT edition_label FROM import_batch WHERE import_id=%s", (import_id,))
    edition_row = cur.fetchone()
    edition = edition_row[0] if edition_row else ""
    cur.execute("SELECT file_id,file_type,file_name FROM source_file WHERE import_id=%s ORDER BY file_id", (import_id,))
    files = [f for f in cur.fetchall() if f[1] in TARGETS]
    decisions = load_data_decisions()
    collisions: list[dict] = []
    for file_id, file_type, file_name in files:
        collisions += _collisions_of_file(cur, file_id, file_name, file_type, edition, decisions)
    return collisions


def collision_summary(rows: list[dict]) -> Counter:
    return Counter(row["class"] for row in rows)
