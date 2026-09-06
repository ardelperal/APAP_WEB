"""``apap-migrate ensure-bucket`` body — extracted from ``cli.py``.

Module-size budget (AGENTS.md rule 21): the parent ``migration/cli.py``
crossed the 700-line cap after the M2 work. Extracting this command
brings the parent back under the limit while keeping ``from migration.cli
import run_ensure_bucket`` working (the ``__all__`` still re-exports the
name, so callers in tests + ``main`` dispatch do not need to change).

Hard rules (web-tdd-philosophy):
- Rule 4 (no humo): the function reads bucket visibility and writes
  ``status=...`` lines; tests assert against the captured stream.
- Rule 8 (no production mutation): runs only against the injected
  ``InsForgeClient`` (test) or the operator's real client (production).
"""

from __future__ import annotations

import argparse
import sys
from typing import IO

from app.core.insforge import InsForgeClient, InsForgeError
from migration.bootstrap import check_private_bucket, ensure_private_bucket


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


__all__ = ["run_ensure_bucket"]
