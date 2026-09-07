"""``apap-migrate ensure-bucket`` body — extracted from ``cli.py``.

Module-size budget (AGENTS.md rule 21): the parent ``migration/cli.py``
crossed the 700-line cap after the M2 work. Extracting this command
brings the parent back under the limit while keeping ``from migration.cli
import run_ensure_bucket`` working (the ``__all__`` still re-exports the
name, so callers in tests + ``main`` dispatch do not need to change).

Post-#5 (LocalBackend runtime) the bucket concept is gone — there is
no bucket backend to check. This command stays as a backward-compat
shim that prints the same line format the operator's CI parses, then
exits 0 (the bucket is treated as already private by the photo-storage
path in :mod:`app.core.local_backend.storage`).
"""

from __future__ import annotations

import argparse
import sys
from typing import IO

from migration.bootstrap import check_private_bucket


def run_ensure_bucket(
    args: argparse.Namespace,
    *,
    web_client=None,
    stream: IO[str] | None = None,
) -> int:
    """Body of ``apap-migrate ensure-bucket`` (backward-compat shim)."""
    if stream is None:
        stream = sys.stdout
    # The web_client parameter is preserved for CLI signature compatibility
    # but no longer used (buckets are gone in the LocalBackend world).
    result = check_private_bucket(args.bucket_name)

    visibility = "true" if result.is_public else "false"
    stream.write(
        f"bucket={result.bucket_name} status={result.status} "
        f"isPublic={visibility}\n"
    )
    return 0


__all__ = ["run_ensure_bucket"]
