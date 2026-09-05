"""Read-only migration status helpers (split from cli.py for AGENTS.md rule 21).

Extracted on 2026-09-05 to keep ``migration/cli.py`` under the 700-line
budget. The functions here are pure read operations on the InsForge
web client (status count, bucket ensure); they share no state with the
apply orchestrator.

Importing this module is safe; it has no side effects.
"""
from __future__ import annotations

import argparse
import sys
from typing import IO

from app.core.insforge import InsForgeClient, InsForgeError
from migration.apply import _safe_table
from migration.bootstrap import check_private_bucket, ensure_private_bucket
from migration.mappings import list_available_tables, load_mapping


def run_status(
    args: argparse.Namespace,
    *,
    web_client: InsForgeClient | None = None,
    stream: IO[str] | None = None,
) -> int:
    """Body of ``apap-migrate status`` (read-only web counts)."""
    if stream is None:
        stream = sys.stdout
    if web_client is None:
        sys.stderr.write("apap-migrate status: requires a web_client in this runtime\n")
        return 2

    tables = [args.table] if args.table else list_available_tables()
    for table in tables:
        mapping = load_mapping(table)
        # Defensa en profundidad (#387): el mismo patrón en apply.py ya
        # validaba el identificador; aquí faltaba.
        safe_web_table = _safe_table(mapping.web_table)
        rows = web_client.execute_sql(f"SELECT COUNT(*) FROM {safe_web_table}")  # noqa: S608
        count = rows[0].get("count", 0) if rows else 0
        stream.write(f"table={table} web_table={mapping.web_table} web_count={count}\n")
    return 0


def run_ensure_bucket(
    args: argparse.Namespace,
    *,
    web_client: InsForgeClient | None = None,
    stream: IO[str] | None = None,
) -> int:
    """Body of ``apap-migrate ensure-bucket``."""
    if stream is None:
        stream = sys.stdout
    if web_client is None:
        sys.stderr.write("apap-migrate ensure-bucket: requires a web_client in this runtime\n")
        return 2

    try:
        if args.check_only:
            result = check_private_bucket(web_client, args.bucket_name)
        else:
            result = ensure_private_bucket(web_client, args.bucket_name)
    except InsForgeError as exc:
        body = exc.body if isinstance(exc.body, dict) else {"error": str(exc.body)}
        reason = body.get("error", "insforge_error")
        stream.write(
            f"bucket={args.bucket_name} status=error reason={reason} "
            f"exit=5 message={body.get('message', exc)}\n"
        )
        return 5
    except ValueError as exc:
        stream.write(f"bucket={args.bucket_name} status=error exit=2 message={exc}\n")
        return 2

    visibility = "true" if result.is_public else "false"
    stream.write(
        f"bucket={result.bucket_name} status={result.status} "
        f"isPublic={visibility}\n"
    )
    return 0
