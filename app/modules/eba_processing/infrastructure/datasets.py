"""Finding the staging table of a file and turning filters into safe SQL. Identifiers are checked against the table's real columns
and values are always bound parameters: nothing the client sends is ever concatenated into SQL."""
from __future__ import annotations

from dataclasses import dataclass

from psycopg2 import sql

from app.core.exceptions import InvalidParameter, NotFoundError
from app.modules.eba_processing.domain import Filters
from app.shared.sql.predicates import aggregate_rows_predicate
from app.shared.staging import STAGING_SCHEMA, staging_identifier, staging_table_name


class DatasetNotFound(NotFoundError):
    kind = "dataset-not-found"
    title = "Dataset not found"


class ImportNotFound(NotFoundError):
    kind = "not-found"
    title = "Import not found"


@dataclass(frozen=True)
class Dataset:
    file_id: int
    import_id: int
    file_name: str
    file_type: str
    table: sql.Identifier
    columns: list[str]

    def col(self, name: str) -> sql.Identifier:
        if name not in self.columns:
            raise InvalidParameter(f"unknown column '{name}' for dataset {self.file_id}; available: {', '.join(self.columns)}")
        return sql.Identifier(name)


def import_exists(cur, import_id: int) -> bool:
    cur.execute("SELECT 1 FROM import_batch WHERE import_id = %s", (import_id,))
    return cur.fetchone() is not None


def _columns(cur, file_id: int) -> list[str]:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", (STAGING_SCHEMA, staging_table_name(file_id)))
    return [r[0] for r in cur.fetchall()]


def get_dataset(cur, file_id: int) -> Dataset:
    cur.execute("SELECT import_id, file_name, file_type FROM source_file WHERE file_id = %s", (file_id,))
    row = cur.fetchone()
    if row is None:
        raise DatasetNotFound(f"no file with id {file_id}")
    cols = _columns(cur, file_id)
    if not cols:
        raise DatasetNotFound(f"file {file_id} ({row[1]}) has no staging table: it was dropped, never loaded or is not a data file")
    return Dataset(file_id, row[0], row[1], row[2], staging_identifier(file_id), cols)


def list_datasets(cur, import_id: int) -> list[Dataset]:
    if not import_exists(cur, import_id):
        raise ImportNotFound(f"import {import_id} does not exist")
    cur.execute("SELECT file_id FROM source_file WHERE import_id = %s ORDER BY file_id", (import_id,))
    out = []
    for (fid,) in cur.fetchall():
        try:
            out.append(get_dataset(cur, fid))
        except DatasetNotFound:
            continue
    return out


def conditions(ds: Dataset, f: Filters) -> tuple[list[sql.Composable], list]:
    """The filters as SQL conditions (identifiers checked against the table) and their bound parameters."""
    conds: list[sql.Composable] = []
    params: list = []
    for name, value in (("period", f.period), ("lei_code", f.lei), ("item", f.item)):
        if value is not None:
            conds.append(sql.SQL("{} = %s").format(ds.col(name)))
            params.append(value)
    for name, value in f.dims.items():
        conds.append(sql.SQL("{} = %s").format(ds.col(name)))
        params.append(value)
    if f.exclude_aggregate:
        conds.append(sql.SQL("NOT " + aggregate_rows_predicate()))
    return conds, params


def clause(conds: list[sql.Composable], *extra: str) -> sql.Composable:
    """` WHERE a AND b ...`; `extra` are fragments written by us (never by the client), appended with AND. Empty when there is nothing."""
    parts = list(conds) + [sql.SQL(e) for e in extra]
    if not parts:
        return sql.SQL("")
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(parts)


def where(ds: Dataset, f: Filters) -> tuple[sql.Composable, list]:
    conds, params = conditions(ds, f)
    return clause(conds), params
