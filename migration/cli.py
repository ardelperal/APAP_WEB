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

The pattern mirrors ``migration.__main__``: the
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
from pathlib import Path
from typing import IO, Any

from app.core.insforge import InsForgeClient, InsForgeError
from migration import MsAccessPreflightUnavailableError
from migration.apply import (
    ApplyResult,
    MsAccessRunningError,
    PartialApplyInterruptedError,
    SourceDriftError,
    apply_legacy_to_web,
)
from migration.bootstrap import APAP_PHOTOS_BUCKET, check_private_bucket, ensure_private_bucket
from migration.legacy_reader import LegacyReaderError
from migration.mappings import list_available_tables, load_mapping
from migration.shadow_state import ShadowStateRepository

# Stable runbook reference for apply-time errors.
#
# The file ``docs/runbooks/live-migration-apply.md`` is the canonical
# operator runbook for the PR3/M1 apply pipeline (MSACCESS
# pre-flight, lock-snapshot ordering, drift detection, partial-apply
# evidence). It is authored in a follow-up PR alongside the per-table
# apply runbook; the path is the contract that the CLI surfaces today
# so the operator gets a deterministic reference even before the
# runbook body is finalized. Updating this constant before the file
# exists is a contract change.
MIGRATION_RUNBOOK_REF: str = "docs/runbooks/live-migration-apply.md"


def _format_apply_error(reason: str, *, exit_code: int) -> str:
    """Render the canonical ``apap-migrate apply`` error line.

    Format is deterministic so log scrapers and operator tooling can
    parse it without regex on free-form text. The line carries ONLY
    a categorical reason + exit code + stable runbook reference —
    no raw exception payloads, no PII, no filesystem paths.

    Args:
        reason: a stable categorical reason (e.g. ``msaccess_running``,
            ``source_drift``). MUST come from a closed vocabulary —
            see ``run_apply`` for the full table.
        exit_code: the deterministic process exit code.

    Returns:
        The single canonical line, terminated with ``\\n``.
    """
    return (
        f"apap-migrate apply: status=error "
        f"reason={reason} exit={exit_code} runbook={MIGRATION_RUNBOOK_REF}\n"
    )

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
    reconcile.add_argument(
        "--filter-direction",
        dest="filter_direction",
        choices=("legacy-to-web", "web-to-legacy", "both"),
        default="both",
        help=(
            "Narrow the listing to one migration direction. Defaults to "
            "'both' so PR4 and earlier callers see the same combined "
            "listing. PR5 ships the flag with forward (legacy-to-web) "
            "filtering live; the reverse (web-to-legacy) filter is wired "
            "but the underlying shadow rows are populated by the PR6 "
            "reverse applier — until then '--filter-direction "
            "web-to-legacy' returns an empty list."
        ),
    )

    available_tables = list_available_tables()

    apply_cmd = sub.add_parser(
        "apply",
        help="Apply legacy Access rows into the web database.",
        description=(
            "Apply one or more legacy table mappings into the web database. "
            "Use --check-only for a dry-run that computes the plan without writes."
        ),
    )
    apply_cmd.add_argument(
        "--table",
        choices=available_tables,
        default=None,
        help="Restrict apply to one mapping (default: all mappings).",
    )
    apply_cmd.add_argument(
        "--legacy-path",
        required=True,
        help="Absolute path to the legacy Access .accdb backend.",
    )
    apply_cmd.add_argument(
        "--since",
        default=None,
        help="ISO-8601 cursor for the apply plan.",
    )
    apply_cmd.add_argument(
        "--check-only",
        dest="check_only",
        action="store_true",
        help="Dry-run: report planned writes without mutating the web DB.",
    )

    status = sub.add_parser(
        "status",
        help="Show per-table web row counts for migration mappings.",
    )
    status.add_argument(
        "--table",
        choices=available_tables,
        default=None,
        help="Restrict status to one mapping (default: all mappings).",
    )

    ensure_bucket = sub.add_parser(
        "ensure-bucket",
        help="Ensure the private photo bucket exists for M0 bootstrap.",
        description=(
            "Prepare the apap-photos bucket infrastructure. By default this "
            "creates a missing bucket as private and reads it back. Use "
            "--check-only for a read-only operator checkpoint."
        ),
    )
    ensure_bucket.add_argument(
        "bucket_name",
        nargs="?",
        default=APAP_PHOTOS_BUCKET,
        help=f"Bucket to check or create (default: {APAP_PHOTOS_BUCKET}).",
    )
    ensure_bucket.add_argument(
        "--check-only",
        dest="check_only",
        action="store_true",
        help="Read bucket state without creating a missing bucket.",
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
#
# PR 5 follow-up fix (P2 from PR 5 code review): the original
# ``row.get('foo') or 'null'`` pattern collapses an empty string to
# the literal ``"null"``, which makes the operator unable to
# distinguish a NULL column from an empty-string value. The formatters
# below use ``_render_value`` which is NULL-aware: ``None`` → ``null``,
# empty string → ``''`` (empty literal), anything else → ``repr(x)``.
#
# PR5 PII contract: ``preserved_value`` carries raw PII (the value the
# applier would re-write to the web column). When the shadow row's
# ``web_column`` is one of the PII columns (the closed list at
# ``app.core.logging.REDACTED_FIELDS``), the formatter masks the
# value to ``"[REDACTED]"`` so the operator stdout never carries a
# raw DNI / email / phone. Mirrors the closed-list redaction that
# ``log_safe`` performs; the CLI is a second surface that needs the
# same protection (per spec REQ-PII-Audit + PR5 scope).
from app.core.logging import REDACTED_FIELDS, _normalize_key


def _is_pii_web_column(column: str | None) -> bool:
    """Return ``True`` when ``column`` names a PII web column.

    Mirrors the closed-list comparison in :func:`log_safe` (case
    insensitive, ``_``/``-`` normalised) so the CLI mask is consistent
    with the ``log_safe`` mask across the rest of the operator
    surface.
    """
    if not column:
        return False
    return _normalize_key(column) in REDACTED_FIELDS


def _mask_pii_value(column: str | None, raw: Any) -> Any:
    """Return ``"[REDACTED]"`` when ``column`` is PII, else ``raw``.

    Used by the CLI formatters to keep the operator-facing stdout
    free of raw PII while preserving the NULL-aware rendering for
    non-PII columns (state machines, natural keys, etc.).
    """
    if _is_pii_web_column(column):
        return "[REDACTED]"
    return raw


def _render_value(x: Any) -> str:
    """Render a single shadow-row value for the ``key=value`` output.

    Rules (PR 5 follow-up):

    - ``None`` → ``"null"`` (the operator can grep the literal).
    - Empty string → ``""`` (rendered as the empty literal, NOT
      collapsed to ``"null"`` — the original bug).
    - String → the string verbatim (preserves JSONB-serialised strings
      like ``'"Adoptado"'`` and bare tokens like ``"v-1"``).
    - Other value → ``str(x)`` (numbers, booleans).
    """
    if x is None:
        return "null"
    return str(x)


def _format_row_for_check_only(row: dict[str, Any]) -> str:
    """One ``key=value`` line per shadow row (T5.1 / design.md §7).

    PR5: ``preserved_value`` is masked to ``"[REDACTED]"`` when
    ``web_column`` is in the closed PII list (the same closed list
    that ``log_safe`` uses). The mask is per-row so non-PII columns
    (state machines, natural keys) keep their verbatim rendering
    for the operator decision surface. The row also carries
    ``origin_direction`` (PR5 spec) — every listed case is stamped
    so the operator dashboard can route by migration direction.
    """
    web_column = row.get("web_column")
    masked_preserved = _mask_pii_value(web_column, row.get("preserved_value"))
    parts: list[str] = [
        f"table={_render_value(row.get('table_name'))}",
        f"legacy_pk={_render_value(row.get('legacy_pk'))}",
        f"web_pk={_render_value(row.get('web_pk'))}",
        f"web_column={_render_value(web_column)}",
        f"origin_direction={_render_value(row.get('origin_direction'))}",
        f"status={_render_value(row.get('reconciliation_status'))}",
        f"strategy={_render_value(row.get('strategy'))}",
        f"web_value={_render_value(masked_preserved)}",
        f"derived_value={_render_value(row.get('derived_value'))}",
        f"derived_at={_render_value(row.get('derived_at'))}",
        f"last_legacy_snapshot_at={_render_value(row.get('last_legacy_snapshot_at'))}",
        f"last_reconciled_at={_render_value(row.get('last_reconciled_at'))}",
        f"review_reasons={_render_value(row.get('review_reasons'))}",
    ]
    return " ".join(parts)


def _format_row_for_interactive(row: dict[str, Any]) -> str:
    """Multi-line block per shadow row for the interactive prompt.

    Mirrors the ``--check-only`` field set but indented so the
    prompt header reads naturally. Optional fields are only shown
    when populated (skip the noise for ``null`` rows).

    PR5: ``preserved_value`` is masked to ``"[REDACTED]"`` when
    ``web_column`` is in the closed PII list (mirrors
    ``_format_row_for_check_only``). The interactive flow does NOT
    bypass the redaction — the operator still sees the column name,
    the status, and the categorical review reasons; they only lose
    the raw PII bytes. Resolution prompts that need the raw value
    (e.g. ``(b) accept derived``) go through ``_format_value_prompt``
    which renders the ``derived_value`` (NOT the preserved PII).
    PR5 also stamps ``origin_direction`` so the operator can see
    which migration direction produced the row.
    """
    web_column = row.get("web_column")
    masked_preserved = _mask_pii_value(web_column, row.get("preserved_value"))
    lines: list[str] = [
        f"  table:                   {_render_value(row.get('table_name'))}",
        f"  legacy_pk:               {_render_value(row.get('legacy_pk'))}",
        f"  web_pk:                  {_render_value(row.get('web_pk'))}",
        f"  web_column:              {_render_value(web_column)}",
        f"  origin_direction:        {_render_value(row.get('origin_direction'))}",
        f"  strategy:                {_render_value(row.get('strategy'))}",
        f"  web_value:               {_render_value(masked_preserved)}",
        f"  derived_value:           {_render_value(row.get('derived_value'))}",
        f"  derived_at:              {_render_value(row.get('derived_at'))}",
        f"  status:                  {_render_value(row.get('reconciliation_status'))}",
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

    PR 5 follow-up: the value prompt is pre-filled with the stored
    ``derived_value`` so the operator can press Enter to accept.
    The prompt body carries the default in brackets (e.g.
    ``Enter value for current_state [default: Adoptado]: ``).
    Empty input from the operator is treated as "accept the default";
    if no default is stored (``derived_value is None``), the operator
    MUST type a value.
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


def _format_value_prompt(row: dict[str, Any]) -> str:
    """Build the ``(b) accept derived`` value prompt with the stored
    ``derived_value`` as the default.

    PR 5 follow-up: the operator can press Enter to accept the
    derived value (no retyping). When ``derived_value`` is missing
    (NULL or absent), the prompt does NOT carry a default — the
    operator MUST type a value (the caller still validates the
    non-empty case; an empty input without a default is rejected).
    """
    web_column = row.get("web_column", "")
    derived_value = row.get("derived_value")
    if derived_value is None:
        return f"Enter value for {web_column}: "
    # Strip JSON quotes if the value was serialised through JSONB and
    # came back as a quoted string (e.g. ``'"Adoptado"'`` → ``Adoptado``).
    rendered = derived_value
    if (
        isinstance(derived_value, str)
        and len(derived_value) >= 2
        and derived_value[0] == derived_value[-1] == '"'
    ):
        rendered = derived_value[1:-1]
    return f"Enter value for {web_column} [default: {rendered}]: "


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
    # PR5 adds ``origin_direction``: the closed vocabulary is
    # ``legacy-to-web`` / ``web-to-legacy`` / ``both``. ``both``
    # disables the filter (PR4-equivalent listing); the other two
    # narrow to one direction. The repository stamps
    # ``origin_direction="legacy-to-web"`` on every row until the
    # PR6 reverse applier starts producing its own rows.
    origin_filter: str | None
    if args.filter_direction == "both":
        origin_filter = None
    else:
        origin_filter = args.filter_direction
    rows = shadow_state.list_needs_review(
        table_name=args.table,
        since=args.since,
        origin_direction=origin_filter,
    )

    if not args.interactive:
        # Default mode (``--check-only`` or no flag): list rows, no
        # writes, exit 0 (design.md §7).
        for row in rows:
            stream.write(_format_row_for_check_only(row) + "\n")
        return 0

    # T5.2 --interactive: walk each case with a/b/c/q prompts.
    # PR 5 follow-up (P2): acquire the migration lock for the duration
    # of the interactive session. Regla #13474 v2: two concurrent
    # interactive sessions would double-resolve cases. The lock is
    # released on exit (normal return, error, or q-quit) via
    # try/finally — the operator can re-run safely on a stale lock.
    from migration import LockActiveError
    from migration import acquire_lock as _acquire_lock
    from migration import check_lock as _check_lock
    from migration import release_lock as _release_lock
    from migration.lock import _is_lock_stale

    lock_path = _resolve_lock_path()
    # Best-effort: if a non-stale lock is held, fail fast with a
    # clear error. Only locks whose owner PID is verifiably dead are
    # auto-overwritten by ``acquire_lock`` (see lock.py).
    existing = _check_lock(lock_path)
    if existing is not None and not _is_lock_stale(existing):
        # Active lock → fail fast. Dead-owner stale locks are picked up by
        # ``acquire_lock`` (it overwrites them after re-checking).
        raise LockActiveError(
            f"apap-migrate reconcile: another interactive session is "
            f"running (pid={existing.pid}, acquired_at="
            f"{existing.acquired_at.isoformat()})"
        )
    _acquire_lock(lock_path)
    try:
        return _run_reconcile_interactive(
            rows=rows,
            prompt=prompt,
            stream=stream,
            shadow_state=shadow_state,
            web_client=web_client,
        )
    finally:
        _release_lock(lock_path)


def _run_reconcile_interactive(
    *,
    rows: list[dict[str, Any]],
    prompt: _PromptReader,
    stream: IO[str],
    shadow_state: ShadowStateRepository,
    web_client: InsForgeClient | None,
) -> int:
    """Walk each ``needs_review`` case with ``a/b/c/q`` prompts.

    Extracted from :func:`run_reconcile` so the lock-acquisition /
    lock-release try/finally wraps cleanly around the interactive loop.
    """
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
            # PR 5 follow-up: prompt is pre-filled with the stored
            # ``derived_value`` so the operator can press Enter to
            # accept. An empty input is treated as "accept the default"
            # only when a default was offered; the ``_format_value_prompt``
            # helper is NULL-aware (no default → operator MUST type).
            prompt_text = _format_value_prompt(row)
            typed = prompt(prompt_text).strip()
            derived_default = row.get("derived_value")
            if not typed and derived_default is not None:
                # Press Enter on a default-prompt → accept the default.
                # Strip JSON quotes if the default came back as a
                # JSONB-serialised string (e.g. ``'"Adoptado"'``).
                if (
                    isinstance(derived_default, str)
                    and len(derived_default) >= 2
                    and derived_default[0] == derived_default[-1] == '"'
                ):
                    new_value: Any = derived_default[1:-1]
                else:
                    new_value = derived_default
            else:
                new_value = typed
            if not new_value:
                sys.stderr.write("apap-migrate reconcile: empty value; case kept as needs_review\n")
                continue
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


def _resolve_lock_path() -> Path:
    """Resolve the migration lock path for the CLI.

    The CLI doesn't have a direct injection seam for the lock path
    today; we read it from the same convention the applier uses
    (``<migration_dir>/migration.lock``) — ``migration_dir`` is the
    directory that contains ``sync_state.json``. When the env var
    ``APAP_MIGRATION_DIR`` is not set (dev mode without the full app
    config), we fall back to ``./migration/migration.lock`` so the
    test surface stays hermetic.
    """
    import os

    from app.core.config import get_settings

    # We use ``get_settings()`` so a future ``migration_dir`` field
    # added to ``Settings`` is picked up automatically; meanwhile the
    # env var fallback covers current callers.
    try:
        settings = get_settings()
        migration_dir = getattr(settings, "migration_dir", None)
    except Exception:  # noqa: BLE001 — settings may not be loadable in tests
        migration_dir = None
    if not migration_dir:
        migration_dir = os.environ.get("APAP_MIGRATION_DIR", "./migration")
    return Path(migration_dir) / "migration.lock"


def run_apply(
    args: argparse.Namespace,
    *,
    web_client: InsForgeClient | None = None,
    stream: IO[str] | None = None,
) -> int:
    """Body of ``apap-migrate apply``.

    Exit code contract (PR3 verification remediation, per user
    directive 2026-07-11) — every typed exception produces a single
    categorical line on the operator stream:

        apap-migrate apply: status=error reason=<cat> exit=<N> runbook=<ref>

    The reasons form a closed vocabulary; the exit codes are
    deterministic. The runbook reference is the stable constant
    :data:`MIGRATION_RUNBOOK_REF`. Operator output carries no traceback,
    no raw exception payloads, no PII, and no filesystem paths —
    the operator reads the runbook for the verbose interpretation.

    | Exception                              | Exit | reason                              |
    |----------------------------------------|------|-------------------------------------|
    | ``MsAccessPreflightUnavailableError``  | 5    | ``msaccess_preflight_unavailable``   |
    | ``MsAccessRunningError``               | 5    | ``msaccess_running``                 |
    | ``LegacyReaderError``                  | 5    | ``legacy_read_failed``               |
    | ``InsForgeError`` (bootstrap path)     | 5    | ``infra_bootstrap_failed``          |
    | ``SourceDriftError``                   | 6    | ``source_drift``                     |
    | ``PartialApplyInterruptedError``       | 7    | ``partial_apply_interrupted``        |

    Unknown exceptions propagate as a Python traceback — the CLI
    does not swallow them. Operators see a real stack so they can
    diagnose bugs; the categorical handlers above cover every
    expected failure mode from the PR3/M1 apply pipeline.
    """
    if stream is None:
        stream = sys.stdout
    if web_client is None:
        sys.stderr.write("apap-migrate apply: requires a web_client in this runtime\n")
        return 2

    since: datetime | None = None
    if args.since is not None:
        try:
            since = datetime.fromisoformat(args.since)
        except (TypeError, ValueError) as exc:
            stream.write(f"apap-migrate apply: invalid ISO-8601 timestamp {args.since!r}: {exc}\n")
            return 2

    tables = [args.table] if args.table else list_available_tables()
    results: list[ApplyResult] = []
    try:
        for table in tables:
            results.append(
                apply_legacy_to_web(
                    web_client,
                    table,
                    legacy_path=args.legacy_path,
                    since=since,
                    dry_run=bool(args.check_only),
                )
            )
    except MsAccessPreflightUnavailableError:
        # psutil missing or process iteration failed. The apply
        # layer already emitted ``log_safe("apply.preflight_unavailable",
        # reason=<cat>)`` before re-raising; the CLI just renders
        # the categorical operator line. No PIDs, no error strings,
        # no path data.
        stream.write(
            _format_apply_error("msaccess_preflight_unavailable", exit_code=5)
        )
        return 5
    except MsAccessRunningError:
        # Live MSACCESS.EXE process detected. The exception carries
        # ``.pids`` — we deliberately do NOT print them (operator
        # output is categorical; runbook explains what to do).
        stream.write(
            _format_apply_error("msaccess_running", exit_code=5)
        )
        return 5
    except LegacyReaderError:
        # pyodbc / dysflow I/O failure. The exception's ``str()``
        # can include the failing SQL fragment — categorical only.
        stream.write(
            _format_apply_error("legacy_read_failed", exit_code=5)
        )
        return 5
    except InsForgeError:
        # Bootstrap failure (private bucket missing, shadow table
        # invariant broken, etc.). ``InsForgeError.body`` may carry
        # internal server-side details — categorical only.
        stream.write(
            _format_apply_error("infra_bootstrap_failed", exit_code=5)
        )
        return 5
    except SourceDriftError:
        # PR3 fails closed on drift (no informational proceed).
        # The exception carries boolean + delta fields — categorical
        # only. A future PR may add ``--accept-drift`` for explicit
        # acknowledgement.
        stream.write(
            _format_apply_error("source_drift", exit_code=6)
        )
        return 6
    except PartialApplyInterruptedError:
        # Prior run was interrupted; ``partial_apply.json`` exists
        # on disk. The operator MUST review and remove the file
        # before retrying — PR3 deliberately does NOT auto-resume.
        # The follow-up ``--resume-from-partial`` operator command
        # is scheduled for the apply runbook PR (PR4 follow-up).
        stream.write(
            _format_apply_error("partial_apply_interrupted", exit_code=7)
        )
        return 7

    for result in results:
        action = "would insert" if args.check_only else "inserted"
        stream.write(
            f"table={result.table_name} {action}={result.applied} "
            f"skipped={result.skipped} errors={len(result.errors)}\n"
        )
        for error in result.errors:
            stream.write(f"  error={error}\n")
    return 0 if not any(r.errors for r in results) else 1


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
        rows = web_client.execute_sql(f"SELECT COUNT(*) FROM {mapping.web_table}")
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

    owned_web_client: InsForgeClient | None = None
    if web_client is None:
        from app.core.config import get_settings

        settings = get_settings()
        owned_web_client = InsForgeClient(
            settings.insforge_url,
            settings.insforge_service_key,
        )
        web_client = owned_web_client

    try:
        if args.command == "reconcile":
            return run_reconcile(
                args,
                web_client=web_client,
                shadow_state=shadow_state,
                prompt=prompt,
                stream=stream,
            )
        if args.command == "apply":
            return run_apply(args, web_client=web_client, stream=stream)
        if args.command == "status":
            return run_status(args, web_client=web_client, stream=stream)
        if args.command == "ensure-bucket":
            return run_ensure_bucket(args, web_client=web_client, stream=stream)
    finally:
        if owned_web_client is not None:
            owned_web_client.close()

    # Defensive: ``required=True`` on the subparsers means argparse
    # already rejected empty invocations; this line is unreachable
    # in normal operation but keeps the return type total.
    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


__all__ = [
    "build_parser",
    "main",
    "run_apply",
    "run_ensure_bucket",
    "run_reconcile",
    "run_status",
]
