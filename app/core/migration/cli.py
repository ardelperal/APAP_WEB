"""CLI for ``apap-migrate reconcile``.

PR 1 of ``web-only-feature-preservation`` wired the parser and the
``--help`` entry point. PR 5 fills in the body across three work
units:

- T5.1 (committed) ``--check-only`` (design.md §7): list
  ``needs_review`` rows from the shadow state in a pipe-friendly
  ``key=value`` format on stdout. No writes are issued. Exit 0
  even when pending rows exist (the operator must resolve them —
  non-zero would block unattended monitoring).
- T5.2-T5.4 (this file) ``--interactive``: walk each case with
  prompts ``(a) keep web / (b) accept derived / (c) defer /
  (q) quit``.
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
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
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


def _format_row_for_interactive(row: dict[str, Any]) -> str:
    """Multi-line block per shadow row for the interactive prompt.

    Mirrors the ``--check-only`` field set but indented so the
    prompt header reads naturally. Optional fields are only shown
    when populated (skip the noise for ``null`` rows).
    """
    lines: list[str] = [
        f"  table:                   {row.get('table_name') or 'null'}",
        f"  legacy_pk:               {row.get('legacy_pk') or 'null'}",
        f"  web_pk:                  {row.get('web_pk') or 'null'}",
        f"  web_column:              {row.get('web_column') or 'null'}",
        f"  strategy:                {row.get('strategy') or 'null'}",
        f"  web_value:               {row.get('preserved_value') or 'null'}",
        f"  status:                  {row.get('reconciliation_status') or 'null'}",
    ]
    if row.get("last_legacy_snapshot_at"):
        lines.append(f"  last_legacy_snapshot_at: {row['last_legacy_snapshot_at']}")
    if row.get("last_reconciled_at"):
        lines.append(f"  last_reconciled_at:      {row['last_reconciled_at']}")
    if row.get("review_reasons"):
        lines.append(f"  review_reasons:          {row['review_reasons']}")
    return "\n".join(lines)


# --- Write paths ---------------------------------------------------------
#
# PR 5's two write paths (T5.3 keep web, T5.4 accept derived) are
# factored into dedicated functions so the test harness can target
# each one in isolation and the ``run_reconcile`` loop stays linear.
# The shape of the SQL UPDATE in ``accept derived`` is fixed by the
# spec REQ-CLI: ``UPDATE {web_table} SET {web_column} = %s WHERE
# id = %s``. The shadow row's ``web_pk`` identifies the row; the
# column name is interpolated (NOT a parameter) because the schema
# of the web table is fixed at migration-time and ``ShadowStateRepository``
# is the trusted source for the column name.

# Constrain ``table_name`` and ``web_column`` interpolation to
# SQL-safe identifiers. The shadow state is our own table so the
# values are trusted, but the constraint guards against a future
# bug that lets a tainted value slip into the column (e.g. a shadow
# row created by a malformed applier pass).
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _apply_keep_web(
    *,
    shadow_state: ShadowStateRepository,
    row: dict[str, Any],
    now: datetime,
) -> None:
    """T5.3 option (a) keep web: flip the shadow row to ``matched``.

    The web value is preserved verbatim — the shadow state
    already mirrors it, and the applier will continue to write
    the same value on the next apply. We only stamp the
    reconciliation status + ``last_reconciled_at`` so the row
    leaves the ``needs_review`` list on the next ``--check-only``.
    """
    shadow_state.update_reconciliation_status(
        table_name=row["table_name"],
        legacy_pk=row["legacy_pk"],
        web_column=row["web_column"],
        status="matched",
        review_reasons=[],
        last_reconciled_at=now,
    )


def _apply_accept_derived(
    *,
    shadow_state: ShadowStateRepository,
    web_client: InsForgeClient,
    row: dict[str, Any],
    new_value: Any,
    now: datetime,
) -> None:
    """T5.4 option (b) accept derived: UPDATE the web row + flip the
    shadow row to ``matched``.

    The operator types the new value at the prompt; the CLI runs
    ``UPDATE {table} SET {column} = %s WHERE id = %s`` against
    the web DB and stamps the shadow row.

    PR 5 limitation: the derivation engine result is not stored
    in the shadow row by PR 4 (the schema only tracks
    ``preserved_value``, which is NULL for ``derived``), so the
    CLI cannot autofill the value. The operator types it. PR 6
    is expected to add a ``derived_value`` column to
    ``web_only_feature_shadow`` so the CLI can autofill; for
    PR 5 the prompt is open.
    """
    table_name = row["table_name"]
    web_column = row["web_column"]
    web_pk = row.get("web_pk")
    if not web_pk:
        raise ValueError(f"accept derived: shadow row has no web_pk ({row!r}); cannot UPDATE")
    if not _SAFE_IDENTIFIER.match(table_name):
        raise ValueError(f"accept derived: unsafe table_name {table_name!r}")
    if not _SAFE_IDENTIFIER.match(web_column):
        raise ValueError(f"accept derived: unsafe web_column {web_column!r}")
    web_client.execute_sql(
        f"UPDATE {table_name} SET {web_column} = %s WHERE id = %s",
        [new_value, web_pk],
    )
    shadow_state.update_reconciliation_status(
        table_name=table_name,
        legacy_pk=row["legacy_pk"],
        web_column=web_column,
        status="matched",
        review_reasons=[],
        last_reconciled_at=now,
    )


# --- --since validation --------------------------------------------------


def _parse_since(value: str) -> str:
    """Validate ``--since`` is a parseable ISO-8601 timestamp.

    The SQL filter (``last_legacy_snapshot_at >= %s``) compares a
    ``TIMESTAMPTZ`` column against the parameter, so the value is
    forwarded as-is to the driver. We still validate it
    client-side so a typo surfaces early as a clean argparse-style
    error instead of silently returning an empty list.
    """
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"--since: invalid ISO-8601 timestamp {value!r}: {exc}"
        ) from exc
    return value


# --- Public entry point --------------------------------------------------


def run_reconcile(
    args: argparse.Namespace,
    *,
    web_client: InsForgeClient | None = None,
    shadow_state: ShadowStateRepository | None = None,
    prompt: _PromptReader | None = None,
    stream: IO[str] | None = None,
) -> int:
    """The body of ``apap-migrate reconcile`` (PR 5/6).

    Implements T5.1-T5.5. The default mode (no ``--interactive``)
    behaves like ``--check-only``: list rows, no writes (design.md
    §7 mandates exit 0 with pending rows). ``--interactive``
    walks each case with keep/accept/defer/quit prompts.

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
        stream: the text stream for non-interactive output
            (``--check-only`` listing, ``--interactive`` case
            headers). Defaults to ``sys.stdout``; tests inject
            ``io.StringIO``.

    Returns:
        Process exit code (0 on success, non-zero on usage errors
        and I/O failures). Matches design.md §7.
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

    # T5.5 --since validation: argparse doesn't validate the ISO
    # format, so we do it here to surface typos as a clean exit-2
    # error (design.md §7) BEFORE any I/O.
    if args.since is not None:
        try:
            _parse_since(args.since)
        except argparse.ArgumentTypeError as exc:
            sys.stderr.write(f"apap-migrate reconcile: {exc}\n")
            return 2

    # T5.5 --table and --since: forwarded to the repository. The
    # repository handles the WHERE clause composition (filter on
    # ``table_name`` and ``since``) and the
    # ``reconciliation_status = 'needs_review'`` predicate. The
    # CLI never recomputes the filter — it just forwards the kwargs.
    rows = shadow_state.list_needs_review(table_name=args.table, since=args.since)

    if not args.interactive:
        for row in rows:
            stream.write(_format_row_for_check_only(row) + "\n")
        return 0

    # T5.2 --interactive: walk each case with a/b/c/q prompts.
    now = datetime.now(UTC)
    for row in rows:
        stream.write("===\n")
        stream.write(_format_row_for_interactive(row) + "\n")
        choice = prompt("Choice (a/b/c/q): ").strip().lower()
        if choice == "a":
            _apply_keep_web(shadow_state=shadow_state, row=row, now=now)
        elif choice == "b":
            if web_client is None:
                sys.stderr.write(
                    "apap-migrate reconcile: --interactive option (b) requires "
                    "a web_client (cannot UPDATE the web table without one)\n"
                )
                return 5
            new_value = prompt(f"Enter value for {row['web_column']}: ").strip()
            _apply_accept_derived(
                shadow_state=shadow_state,
                web_client=web_client,
                row=row,
                new_value=new_value,
                now=now,
            )
        elif choice == "c":
            # T5.2 defer: no-op. The case stays ``needs_review``
            # until the next ``--check-only``/``--interactive`` run.
            pass
        elif choice == "q":
            # T5.2 quit: exit early; remaining rows stay untouched.
            return 0
        else:
            # Unknown choice: skip with a warning so the operator
            # can recover on the next case.
            sys.stderr.write(f"apap-migrate reconcile: unknown choice {choice!r}; skipping\n")

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
