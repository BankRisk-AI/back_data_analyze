"""Staging tables: one UNLOGGED table per data file, all columns as text (typing happens in the preparation module)."""
import csv, io
from psycopg2 import sql
from app.modules.eba_ingest.domain import UnreadableFile
from app.shared.staging import staging_identifier

class CsvStream:
    """File-like object that feeds COPY from a row generator in batches; memory stays flat."""
    def __init__(self, rows, ncols: int, label: str):
        self.rows, self.ncols, self.label, self.buf, self.done, self.n, self.error = iter(rows), ncols, label, "", False, 0, None
    def read(self, size: int = 1 << 16) -> str:
        while len(self.buf) < size and not self.done:
            chunk = io.StringIO(); w = csv.writer(chunk, lineterminator="\n")
            for _ in range(2000):
                try: row = next(self.rows)
                except StopIteration: self.done = True; break
                if not any(c != "" for c in row): continue                       # blank line
                if len(row) > self.ncols:
                    self.error = UnreadableFile(f"{self.label}: row {self.n + 2} has {len(row)} values, the header has {self.ncols}"); raise self.error
                w.writerow(list(row) + [""] * (self.ncols - len(row))); self.n += 1
            self.buf += chunk.getvalue()
        out, self.buf = self.buf[:size], self.buf[size:]
        return out

def create_and_copy(cur, file_id: int, columns, rows, label: str) -> int:
    table = staging_identifier(file_id)
    cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
    cur.execute(sql.SQL("CREATE UNLOGGED TABLE {} ({})").format(table, sql.SQL(", ").join(sql.SQL("{} text").format(sql.Identifier(c)) for c in columns)))
    stream = CsvStream(rows, len(columns), label)
    try: cur.copy_expert(sql.SQL("COPY {} FROM STDIN WITH (FORMAT csv)").format(table).as_string(cur), stream)
    except Exception as e:
        if stream.error: raise stream.error from e        # psycopg2 wraps errors raised while reading the source
        raise
    return stream.n
