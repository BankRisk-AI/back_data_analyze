"""The contract between the module that writes the staging tables (ingest) and the modules that read them (processing, later insert):
one table per data file, named staging.f<file_id>, every column text. Nothing else is shared between those modules."""
from psycopg2 import sql

STAGING_SCHEMA = "staging"


def staging_table_name(file_id: int) -> str:
    return f"f{file_id}"


def staging_qualified(file_id: int) -> str:
    return f"{STAGING_SCHEMA}.{staging_table_name(file_id)}"


def staging_identifier(file_id: int) -> sql.Identifier:
    return sql.Identifier(STAGING_SCHEMA, staging_table_name(file_id))
