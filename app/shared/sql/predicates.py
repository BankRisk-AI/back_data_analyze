"""PostgreSQL predicates shared by the modules that read the staging tables (columns are lower-case text)."""

NUMBER_REGEX = r"^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$"


def aggregate_rows_predicate(lei_column: str = "lei_code", nsa_column: str = "nsa") -> str:
    """SQL condition identifying the aggregate bucket 'All other banks': LEI of X characters (any case) or country OT."""
    return f"(upper({lei_column}) ~ '^X+$' OR {nsa_column} = 'OT')"


def blank_text(column: str) -> str:
    """SQL expression that is NULL for NULL, empty or blank text (the staging tables keep empty cells as NULL or '')."""
    return f"NULLIF(btrim({column}), '')"


def numeric_amount(column: str = "amount") -> str:
    """SQL expression: the amount as double precision, NULL when empty or not a number (never raises)."""
    return f"CASE WHEN {column} ~ '{NUMBER_REGEX}' THEN {column}::double precision END"
