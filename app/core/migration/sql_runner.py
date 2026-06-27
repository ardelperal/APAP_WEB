"""SQL migration runner for the APAP_WEB web database (schema plane).

Distinct from ``app.core.migration.*`` (which handles the bidireccional
web ↔ Access data sync per issue #93). Here we deal with DDL: dropping
a redundant CHECK, adding a column, creating an index. Files live in
``app/core/migration/sql/`` named ``NNN_description.sql``.

Algorithm: bootstrap ``web_sql_migrations`` bookkeeping, then for each
file not yet recorded, execute it via ``client.execute_sql`` and
record the filename. Each migration file is also written to be
idempotent (``DROP CONSTRAINT IF EXISTS``, ``CREATE TABLE IF NOT
EXISTS``) so manual replays are safe.
"""

from __future__ import annotations

from pathlib import Path

from app.core.insforge import InsForgeClient

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "sql"
_BOOTSTRAP_SQL = (
    "CREATE TABLE IF NOT EXISTS web_sql_migrations ("
    "filename TEXT PRIMARY KEY,"
    "applied_at TIMESTAMP NOT NULL DEFAULT now()"
    ")"
)
_LIST_APPLIED_SQL = "SELECT filename FROM web_sql_migrations"
_RECORD_SQL = (
    "INSERT INTO web_sql_migrations (filename) VALUES ($1) "
    "ON CONFLICT (filename) DO NOTHING"
)


def apply_sql_migrations(client: InsForgeClient) -> list[str]:
    """Apply any pending SQL migrations in alphabetical order.

    Returns the filenames applied in this run (empty when the database
    is already up to date).
    """
    client.execute_sql(_BOOTSTRAP_SQL)
    already_applied = {
        row["filename"]
        for row in client.execute_sql(_LIST_APPLIED_SQL)
    }
    applied: list[str] = []
    for sql_path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        filename = sql_path.name
        if filename in already_applied:
            continue
        client.execute_sql(sql_path.read_text(encoding="utf-8"))
        client.execute_sql(_RECORD_SQL, [filename])
        applied.append(filename)
    return applied
