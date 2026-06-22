"""CLI for ``apap-migrate reconcile``.

PR 1 of ``web-only-feature-preservation`` wired the parser and the
``--help`` entry point. PR 5 fills in the body across three work
units:

- T5.1 (this file) ``--check-only`` (design.md §7): list
  ``needs_review`` rows from the shadow state in a pipe-friendly
  ``key=value`` format on stdout. No writes are issued. Exit 0
  even when pending rows exist (the operator must resolve them —
  non-zero would block unattended monitoring).
- T5.2-T5.4 ``--interactive``: walk each case with prompts
  ``(a) keep web / (b) accept derived / (c) defer / (q) quit``.
- T5.5 ``--table <name>`` and ``--since <ISO8601>``: forward to
  ``ShadowStateRepository.list_needs_review``.

Two testability seams are injected through ``main`` /
``run_reconcile``:

- ``prompt``: a ``Callable[[str], str]`` that the CLI uses to read
  the operator's choice. Production binds it to ``input``; tests
  bind it to a list-driven fake so the suite never touches stdin.
- ``stream``: a text stream the CLI writes its non-interactive
  output to. Production binds it to ``sys.stdout``; tests bind
  it to an ``io.StringIO`` and assert against ``.getvalue()``.

The pattern mirrors ``app.core.migration.__main__``: the
``ShadowStateRepository`` is built from the injected
``InsForgeClient`` when no explicit ``shadow_state`` is provided
(production path) so the test surface stays a single object.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import IO, Any

from app.core.insforge import InsForgeClient
from app.core.migration.shadow_state import ShadowStateRepository

# Type alias for the prompt reader injected into ``run_reconcile``.
# Production: ``input`` (read from stdin). Tests: a list-driven
# fake that returns the next canned response.
_PromptReader = Callable[[str], str]


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
    # PR 5 fills in the body (--check-only + --interactive +
    # --table + --since). The four flags were declared in PR 1 so
    # ``--help`` has been listing them since the skeleton landed.

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


# --- Formatters ----------------------------------------------------------
#
# One ``key=value`` line per case for ``--check-only`` (T5.1). The
# shadow row is the single source of truth: the CLI never recomputes
# values, only projects the fields the operator needs to make a
# decision. The output is grep / ``jq``-friendly: a single line
# per case with all relevant fields. ``None`` values are rendered
# as the literal string ``"null"`` so the output is grep-safe
# (a missing field is distinguishable from an empty string).
# ``preserved_value`` and ``review_reasons`` are JSON strings
# coming from the JSONB columns; the test harness compares them
# verbatim against the value the fake server returned.


def _format_row_for_check_only(row: dict[str, Any]) -> str:
    """One ``key=value`` line per shadow row (T5.1 / design.md §7)."""
    parts: list[str] = [
        f"table={row.get('table_name') or 'null'}",
        f"legacy_pk={row.get('legacy_pk') or 'null'}",
        f"web_pk={row.get('web_pk') or 'null'}",
        f"web_column={row.get('web_column') or 'null'}",
        f"status={row.get('reconciliation_status') or 'null'}",
        f"strategy={row.get('strategy') or 'null'}",
        f"web_value={row.get('preserved_value') or 'null'}",
        f"last_legacy_snapshot_at={row.get('last_legacy_snapshot_at') or 'null'}",
        f"last_reconciled_at={row.get('last_reconciled_at') or 'null'}",
        f"review_reasons={row.get('review_reasons') or '[]'}",
    ]
    return " ".join(parts)


# --- Public entry point --------------------------------------------------


def run_reconcile(
    args: argparse.Namespace,
    *,
    web_client: InsForgeClient | None = None,
    shadow_state: ShadowStateRepository | None = None,
    prompt: _PromptReader | None = None,
    stream: IO[str] | None = None,
) -> int:
    """The body of ``apap-migrate reconcile`` (PR 5/6, T5.1 slice).

    Slice 1 of 3 (this commit): ``--check-only`` lists pending
    ``needs_review`` rows without writing. The interactive / write
    paths and the ``--table`` / ``--since`` filters land in
    subsequent PR 5 commits (T5.2-T5.5).

    Args:
        args: the parsed argparse namespace (carries ``--interactive``,
            ``--check-only``, ``--table``, ``--since``).
        web_client: the InsForge REST client. Used to build the
            ``shadow_state`` when not injected, and to run the
            ``UPDATE {table}`` in option (b). Tests inject a
            ``httpx.MockTransport``-backed client.
        shadow_state: the CRUD wrapper around
            ``web_only_feature_shadow``. When ``None``, built from
            ``web_client`` (production path).
        prompt: ``_PromptReader`` (callable returning a string).
            Defaults to ``input``; tests inject a list-driven fake.
            Unused in this slice; parameter is wired in advance so
            the interactive slice (T5.2) does not have to touch
            the public signature.
        stream: the text stream for non-interactive output.
            Defaults to ``sys.stdout``; tests inject
            ``io.StringIO``.

    Returns:
        Process exit code (0 on success). Matches design.md §7.
    """
    if stream is None:
        stream = sys.stdout
    if prompt is None:
        prompt = input
    if shadow_state is None:
        if web_client is None:
            sys.stderr.write(
                "apap-migrate reconcile: requires either a web_client or a "
                "shadow_state (got both as None)\n"
            )
            return 2
        shadow_state = ShadowStateRepository(web_client)

    # T5.1 --check-only: read pending rows, list to stdout, no
    # writes. Exit 0 even with pending rows (design.md §7 — exit
    # non-zero would block unattended monitoring). The ``--table``
    # and ``--since`` filters are declared on the parser (PR 1)
    # but not wired yet; they arrive in the T5.5 slice.
    rows = shadow_state.list_needs_review(table_name=args.table, since=args.since)

    for row in rows:
        stream.write(_format_row_for_check_only(row) + "\n")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    web_client: InsForgeClient | None = None,
    shadow_state: ShadowStateRepository | None = None,
    prompt: _PromptReader | None = None,
    stream: IO[str] | None = None,
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
        return run_reconcile(
            args,
            web_client=web_client,
            shadow_state=shadow_state,
            prompt=prompt,
            stream=stream,
        )

    # Defensive: ``required=True`` on the subparsers means argparse
    # already rejected empty invocations; this line is unreachable
    # in normal operation but keeps the return type total.
    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


__all__ = [
    "build_parser",
    "main",
    "run_reconcile",
]
