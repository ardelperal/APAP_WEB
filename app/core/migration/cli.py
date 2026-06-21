"""CLI skeleton for ``apap-migrate reconcile``.

PR 1 of ``web-only-feature-preservation``. This module wires the
``reconcile`` subcommand into the existing ``app.core.migration``
package, so the operator can already validate that the chain is
plumbed end-to-end (``--help`` lists the four documented flags,
``--check-only`` runs against a clean repo without writing).

PR 5 will replace the placeholder body of ``run_reconcile`` with the
interactive prompt loop and the actual read/write paths through
``ShadowStateRepository`` and the derivation engine.

The pattern mirrors ``app.core.migration.__main__``:

- ``build_parser()`` returns an ``argparse.ArgumentParser`` so tests
  can probe flag handling without invoking ``sys.argv``.
- ``main(argv, web_client=None)`` is the public entry point; the
  ``web_client`` parameter is injectable so tests can pass an
  ``InsForgeClient`` with ``httpx.MockTransport`` instead of touching
  the network. ``__main__.py`` calls ``main(sys.argv[1:])`` with the
  default ``web_client`` built from the env (``DYSFLOW_*`` /
  ``INSFORGE_*``).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.core.insforge import InsForgeClient


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``apap-migrate`` argument parser.

    Subcommands are added here so ``--help`` lists the full surface
    the operator can reach. Today only ``reconcile`` exists; ``apply``,
    ``status``, and ``init`` arrive in MIGRATION-01 PR 4/6.
    """
    parser = argparse.ArgumentParser(
        prog="apap-migrate",
        description=(
            "APAP — bidirectional migration tool for the legacy Access DB "
            "and the web application. See "
            "openspec/changes/web-only-feature-preservation/ for the chain "
            "overview and PR boundaries."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- reconcile --------------------------------------------------
    #
    # PR 1: skeleton only. Lists the 4 documented flags and exits
    # cleanly on ``--help`` and ``--check-only``. The interactive
    # prompt + write paths are PR 5.

    reconcile = sub.add_parser(
        "reconcile",
        help=(
            "List or resolve web-only feature shadow rows that diverged "
            "from the legacy DB after a sync."
        ),
        description=(
            "Reconciles the ``web_only_feature_shadow`` table against the "
            "latest legacy snapshot. Use ``--check-only`` to enumerate "
            "divergences without writing; ``--interactive`` to walk through "
            "each case with keep/accept/defer prompts."
        ),
    )
    reconcile.add_argument(
        "--interactive",
        action="store_true",
        help="Walk through each case with operator prompts (PR 5).",
    )
    reconcile.add_argument(
        "--check-only",
        dest="check_only",
        action="store_true",
        help="Report divergences to stdout without writing to the web DB.",
    )
    reconcile.add_argument(
        "--table",
        dest="table",
        default=None,
        help="Filter to one shadow table (e.g. 'voluntarios').",
    )
    reconcile.add_argument(
        "--since",
        dest="since",
        default=None,
        help=(
            "Filter to divergences first seen at-or-after this ISO-8601 "
            "timestamp (e.g. '2026-06-20T00:00:00+00:00')."
        ),
    )

    return parser


def run_reconcile(
    args: argparse.Namespace,
    *,
    web_client: InsForgeClient | None = None,
) -> int:
    """Skeleton body for ``apap-migrate reconcile``.

    PR 1 only guarantees that:

    - ``--help`` (handled by argparse upstream) lists all four flags.
    - ``--check-only`` runs against a clean repo without issuing any
      SQL through ``web_client``.

    The real reconciliation loop — interactive prompt, write paths,
    derivation engine invocation — lands in PR 5. When invoked with
    neither ``--check-only`` nor ``--interactive`` (today the only
    mode), the skeleton just prints a placeholder and exits 0 so the
    entry point is plumbed and ready for PR 5 to fill in.
    """
    # NOTE: the interactive prompt and the write paths are PR 5's
    # responsibility. PR 1 only wires the parser and the entry point
    # so subsequent PRs can extend ``run_reconcile`` without touching
    # the parser or ``__main__``.
    sys.stderr.write(
        "apap-migrate reconcile: skeleton listo. "
        "Interactive prompt y write paths llegan en PR 5/6 "
        "(openspec/changes/web-only-feature-preservation/tasks.md §PR 5).\n"
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    web_client: InsForgeClient | None = None,
) -> int:
    """Entry point for ``python -m app.core.migration``.

    ``argv`` defaults to ``sys.argv[1:]`` when ``None``. ``web_client``
    is injected by tests so they can assert against a mock transport;
    in production ``__main__.py`` builds it from environment settings.

    Returns the process exit code (0 on success, non-zero on usage
    errors). Matches the contract documented in design.md §7.
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "reconcile":
        return run_reconcile(args, web_client=web_client)

    # Defensive: ``required=True`` on the subparsers means argparse
    # already rejected empty invocations; this line is unreachable
    # in normal operation but keeps the return type total.
    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


__all__ = ["build_parser", "main", "run_reconcile"]
