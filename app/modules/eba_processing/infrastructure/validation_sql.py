"""SQL of the validation rules (see domain/rules.py for what each rule means). Every rule reads one staging table and returns one issue."""
from __future__ import annotations

from collections.abc import Callable

from psycopg2 import sql

from app.modules.eba_processing.domain import ANNOTATION_COLUMNS, LABEL_COLUMN, MAX_EXAMPLES, MEASURE_COLUMN, RULES_BY_ID, ValidationIssue
from app.modules.eba_processing.infrastructure.datasets import Dataset
from app.core.data_decisions import decision_matches_row, load_data_decisions
from app.shared.sql.predicates import NUMBER_REGEX, aggregate_rows_predicate, blank_text, numeric_amount

AGG = aggregate_rows_predicate()
# SQL does not guarantee the order in which AND operands are evaluated, so a cast must never rely on a regex placed before it:
# the cast lives inside a CASE branch that only a matching value can reach.
MONTH = "(CASE WHEN period ~ '^[0-9]{6}$' THEN substr(period, 5, 2)::int END)"
VALID_PERIOD = f"COALESCE({MONTH} BETWEEN 1 AND 12, false)"
NUM = numeric_amount("amount")


def _issue(rule_id: str, affected: int, detail: str = "", examples: list[dict] | None = None,
           severity: str | None = None, passed: bool | None = None) -> ValidationIssue:
    r = RULES_BY_ID[rule_id]
    return ValidationIssue(rule=r.id, title=r.title, severity=severity or r.severity,
                           passed=affected == 0 if passed is None else passed,
                           affected_rows=affected, detail=detail,
                           examples=(examples or [])[:MAX_EXAMPLES])


def _count_and_examples(cur, ds: Dataset, condition: str, cols: list[str], params: tuple = ()) -> tuple[int, list[dict]]:
    cond = sql.SQL(condition)
    cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE ").format(ds.table) + cond, params)
    n = cur.fetchone()[0]
    if n == 0:
        return 0, []
    cur.execute(sql.SQL("SELECT {} FROM {} WHERE ").format(sql.SQL(", ").join(sql.Identifier(c) for c in cols), ds.table) + cond + sql.SQL(" ORDER BY ctid LIMIT %s"), params + (MAX_EXAMPLES,))
    names = [d[0] for d in cur.description]
    return n, [dict(zip(names, r)) for r in cur.fetchall()]


def _key_cols(ds: Dataset) -> list[str]:
    return [c for c in ("lei_code", "nsa", "period", "item", "amount") if c in ds.columns]


def v01(cur, ds):
    n, ex = _count_and_examples(cur, ds, f"{blank_text('lei_code')} IS NULL OR {blank_text('period')} IS NULL OR {blank_text('item')} IS NULL", _key_cols(ds))
    return _issue("V01", n, f"{n} rows miss lei_code, period or item" if n else "", ex)


def v02(cur, ds):
    ident = [c for c in ds.columns if c not in (LABEL_COLUMN, MEASURE_COLUMN, *ANNOTATION_COLUMNS)]
    cols = sql.SQL(", ").join(sql.Identifier(c) for c in ident)
    canonical_amount = f"CASE WHEN amount ~ '{NUMBER_REGEX}' THEN amount::numeric::text ELSE amount END"
    duplicate_query = (
        sql.SQL("SELECT count(*) FILTER (WHERE amounts = 1), "
                "COALESCE(sum(c) FILTER (WHERE amounts = 1), 0), "
                "count(*) FILTER (WHERE amounts > 1), "
                "COALESCE(sum(c) FILTER (WHERE amounts > 1), 0) "
                "FROM (SELECT count(*) AS c, count(DISTINCT ")
        + sql.SQL(canonical_amount)
        + sql.SQL(") AS amounts FROM {} GROUP BY ").format(ds.table)
        + cols
        + sql.SQL(" HAVING count(*) > 1) d")
    )
    cur.execute(sql.SQL("SELECT ") + cols + sql.SQL(", count(*) AS copies, count(DISTINCT ")
                + sql.SQL(canonical_amount) + sql.SQL(") AS amounts FROM {} GROUP BY ").format(ds.table)
                + cols + sql.SQL(" HAVING count(*) > 1 ORDER BY copies DESC"))
    names = [d[0] for d in cur.description]
    groups = [dict(zip(names, r)) for r in cur.fetchall()]
    exact = [g for g in groups if g["amounts"] == 1]
    conflicts = [g for g in groups if g["amounts"] > 1]
    decisions = [d for d in load_data_decisions() if d.edition == _edition(cur, ds.import_id) and d.file_type == ds.file_type]
    resolved = []
    unresolved = []
    for group in conflicts:
        decision = next((d for d in decisions if decision_matches_row(d, group)), None)
        (resolved if decision else unresolved).append((group, decision))
    exact_rows = sum(g["copies"] for g in exact)
    resolved_rows = sum(g["copies"] for g, _ in resolved)
    conflict_rows = sum(g["copies"] for g, _ in unresolved)
    if unresolved:
        examples = [g for g, _ in unresolved[:MAX_EXAMPLES]]
    elif exact:
        examples = exact[:MAX_EXAMPLES]
    else:
        examples = [g for g, _ in resolved[:MAX_EXAMPLES]]
    if unresolved:
        detail = f"{len(unresolved)} identities have conflicting amounts, in {conflict_rows} rows"
        if resolved:
            detail += f"; {len(resolved)} identities ({resolved_rows} rows) resolved by decision " + ", ".join(d.id for _, d in resolved)
        if exact:
            detail += f"; {len(exact)} exact-duplicate identities ({exact_rows} rows) are retained as info"
        return _issue("V02", int(conflict_rows), detail, examples, severity="error")
    if conflicts:
        ids = ", ".join(d.id for _, d in resolved)
        return _issue("V02", int(resolved_rows),
                      f"{len(conflicts)} conflicting identities ({resolved_rows} rows) resolved by decision {ids}; excluded at load",
                      examples, severity="info")
    if exact:
        return _issue("V02", int(exact_rows),
                      f"{len(exact)} identities have exact duplicate amounts, in {exact_rows} rows; one copy is retained as info",
                      examples, severity="info")
    return _issue("V02", 0)


def _edition(cur, import_id: int) -> str:
    cur.execute("SELECT edition_label FROM import_batch WHERE import_id=%s", (import_id,))
    return cur.fetchone()[0] or ""


def v03(cur, ds):
    n, ex = _count_and_examples(cur, ds, f"{blank_text('amount')} IS NOT NULL AND amount !~ '{NUMBER_REGEX}'", _key_cols(ds))
    return _issue("V03", n, f"{n} amounts are not numbers" if n else "", ex)


def v04(cur, ds):
    n, ex = _count_and_examples(cur, ds, f"{blank_text('amount')} IS NULL", _key_cols(ds))
    return _issue("V04", n, f"{n} rows have an empty amount" if n else "", ex)


def v05(cur, ds):
    n, ex = _count_and_examples(cur, ds, f"NOT {VALID_PERIOD}", _key_cols(ds))
    return _issue("V05", n, f"{n} rows have a period that is not YYYYMM with a month from 01 to 12" if n else "", ex)


def v06(cur, ds):
    n, ex = _count_and_examples(cur, ds, f"{MONTH} BETWEEN 1 AND 12 AND {MONTH} NOT IN (3, 6, 9, 12)", _key_cols(ds))
    return _issue("V06", n, f"{n} rows have a period that is not a quarter end" if n else "", ex)


def v07(cur, ds):
    n, ex = _count_and_examples(cur, ds, f"NOT {AGG} AND (lei_code IS NULL OR lei_code !~ '^[A-Za-z0-9]{{20}}$')", _key_cols(ds))
    return _issue("V07", n, f"{n} rows have a LEI that is not 20 alphanumeric characters" if n else "", ex)


def v08(cur, ds):
    n, ex = _count_and_examples(cur, ds, "nsa IS NULL OR nsa !~ '^[A-Z]{2}$'", _key_cols(ds))
    return _issue("V08", n, f"{n} rows have a country code that is not two upper-case letters" if n else "", ex)


def v09(cur, ds):
    cur.execute(sql.SQL("SELECT count(*), COALESCE(sum(c), 0) FROM (SELECT count(*) AS c FROM {} GROUP BY item HAVING count(DISTINCT label) > 1) d").format(ds.table))
    items, rows = cur.fetchone()
    examples = []
    if items:
        cur.execute(sql.SQL("SELECT item, array_agg(DISTINCT label) AS labels FROM {} GROUP BY item HAVING count(DISTINCT label) > 1 ORDER BY item LIMIT %s").format(ds.table), (MAX_EXAMPLES,))
        examples = [{"item": r[0], "labels": r[1]} for r in cur.fetchall()]
    return _issue("V09", int(rows), f"{items} items have more than one label" if items else "", examples)


def v10(cur, ds):
    cur.execute(sql.SQL("SELECT period, array_agg(DISTINCT lei_code) FROM {} WHERE NOT " + AGG + " AND period ~ '^[0-9]{{6}}$' GROUP BY period ORDER BY period").format(ds.table))
    per = [(p, set(leis)) for p, leis in cur.fetchall()]
    if len({len(s) for _, s in per}) <= 1:
        return _issue("V10", 0)
    ex = []
    for i, (p, s) in enumerate(per):
        prev = per[i - 1][1] if i else None
        ex.append({"period": p, "banks": len(s), "entered": len(s - prev) if prev is not None else None, "left": len(prev - s) if prev is not None else None})
    detail = "; ".join(f"{e['period']}: {e['banks']} banks" for e in ex)
    return _issue("V10", sum(abs(e["entered"] or 0) + abs(e["left"] or 0) for e in ex), f"the number of banks changes between periods ({detail})", ex)


def v11(cur, ds):
    base = sql.SQL(
        f"""WITH v AS (SELECT item, period, lei_code, {NUM} AS v FROM {{}} WHERE NOT {AGG} AND {NUM} IS NOT NULL),
                 q AS (SELECT item, period, percentile_cont(0.25) WITHIN GROUP (ORDER BY v) AS q1, percentile_cont(0.75) WITHIN GROUP (ORDER BY v) AS q3
                       FROM v GROUP BY item, period HAVING count(*) >= 30),
                 o AS (SELECT v.item, v.period, v.lei_code, v.v, q.q1, q.q3,
                              GREATEST(q.q1 - v.v, v.v - q.q3) / (q.q3 - q.q1) AS iqrs
                       FROM v JOIN q USING (item, period)
                       WHERE q.q3 > q.q1 AND (v.v < q.q1 - 3 * (q.q3 - q.q1) OR v.v > q.q3 + 3 * (q.q3 - q.q1)))
            """).format(ds.table)
    cur.execute(base + sql.SQL("SELECT count(*) FROM o"))
    n = cur.fetchone()[0]
    ex = []
    if n:
        cur.execute(base + sql.SQL("SELECT item, period, lei_code, v, round(iqrs::numeric, 1) FROM o ORDER BY iqrs DESC LIMIT %s"), (MAX_EXAMPLES,))
        ex = [{"item": r[0], "period": r[1], "lei_code": r[2], "amount": r[3], "iqrs_from_quartile": float(r[4])} for r in cur.fetchall()]
    return _issue("V11", n, f"{n} amounts lie more than 3 IQR outside the quartiles of their item and period" if n else "", ex)


def v12(cur, ds):
    n, ex = _count_and_examples(cur, ds, AGG, _key_cols(ds))
    return _issue("V12", n, f"{n} rows belong to the aggregate bucket 'All other banks'" if n else "", ex)


def v13(cur, ds):
    cur.execute(sql.SQL("SELECT count(*) FROM {}").format(ds.table))
    total = cur.fetchone()[0]
    if total == 0:
        return _issue("V13", 0)
    cols = [c for c in ds.columns if c not in ANNOTATION_COLUMNS]            # footnotes are legitimately empty in most files
    exprs = [sql.SQL("count(*) FILTER (WHERE NULLIF(btrim({c}), '') IS NOT NULL)").format(c=sql.Identifier(c)) for c in cols]
    cur.execute(sql.SQL("SELECT ") + sql.SQL(", ").join(exprs) + sql.SQL(" FROM {}").format(ds.table))
    empty = [c for c, k in zip(cols, cur.fetchone()) if k == 0]
    return _issue("V13", len(empty), "columns with no value: " + ", ".join(empty) if empty else "", [{"column": c} for c in empty])


RULE_FUNCTIONS: list[tuple[str, Callable]] = [("V01", v01), ("V02", v02), ("V03", v03), ("V04", v04), ("V05", v05), ("V06", v06), ("V07", v07),
                                              ("V08", v08), ("V09", v09), ("V10", v10), ("V11", v11), ("V12", v12), ("V13", v13)]
