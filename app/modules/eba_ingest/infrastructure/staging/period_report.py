"""SQL that summarises a staging table right after it is loaded: aggregate rows, (year, quarter) pairs, period warnings."""
from psycopg2 import sql

from app.modules.eba_ingest.domain.models import FileReport, PairReport
from app.shared.sql.predicates import aggregate_rows_predicate


def fill_period_report(cur, table: sql.Identifier, rep: FileReport) -> None:
    agg = aggregate_rows_predicate()
    # the cast sits inside CASE: `period ~ regex AND substr(...)::int` may be evaluated in any order and fail on a value like '2020'
    month = "(CASE WHEN period ~ '^[0-9]{{6}}$' THEN substr(period, 5, 2)::int END)"
    cur.execute(sql.SQL(
        """SELECT count(*) FILTER (WHERE {agg}),
                  count(*) FILTER (WHERE NOT period ~ '^[0-9]{{6}}$' OR period IS NULL),
                  count(*) FILTER (WHERE period ~ '^[0-9]{{6}}$'
                                    AND substr(period, 5, 2)::int NOT IN (3,6,9,12))
           FROM {table}"""
    ).format(table=table, agg=sql.SQL(agg), month=sql.SQL(month)))
    rep.aggregate_rows, bad, not_quarter_end = cur.fetchone()
    cur.execute(
        sql.SQL(
            """SELECT left(period,4)::int, ((substr(period,5,2)::int - 1) / 3 + 1), count(DISTINCT lei_code), count(*)
               FROM {} WHERE NOT """ + agg + """ AND """ + month + """ BETWEEN 1 AND 12
               GROUP BY 1, 2 ORDER BY 1, 2"""
        ).format(table)
    )
    rep.pairs = [PairReport(*r) for r in cur.fetchall()]
    if bad:
        rep.warnings.append(f"{bad} rows have a Period that is not YYYYMM")
    if not_quarter_end:
        rep.warnings.append(f"{not_quarter_end} rows have a Period that is not a quarter end (the EBA files only have 03, 06, 09, 12)")
