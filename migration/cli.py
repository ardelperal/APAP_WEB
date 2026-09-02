"""CLI for ``apap-migrate reconcile`` + ``ensure-bucket`` + others.

The reconcile subcommands wire the parser (PR1) and the body (PR5).
``ensure-bucket`` lives in ``migration.cli_ensure_bucket`` (module-size
split, issue #203) and is re-exported here so the public surface
``from migration.cli import X`` is unchanged.

Two testability seams are injected through ``main`` / ``run_reconcile``:

- ``prompt``: a ``Callable[[str], str]`` that the CLI uses to read
  the operator's choice. Production binds it to ``input``; tests
  bind it to a list-driven fake so the suite never touches stdin.
- ``stream``: a text stream the CLI writes its non-interactive
  output to. Production binds it to ``sys.stdout``; tests bind
  it to an ``io.StringIO`` and assert against ``.getvalue()``.

Output formatting + PII masking live in ``migration.cli_format``;
this module re-imports those helpers for backwards-compat callers.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from app.core.insforge import InsForgeClient
from migration.apply import (  # noqa: F401 — test_cli_apply_safety monkeypatch
    _safe_table,
    apply_legacy_to_web,
)
from migration.bootstrap import (
    APAP_PHOTOS_BUCKET,  # check_private_bucket/ensure_private_bucket moved to cli_ensure_bucket
)
from migration.cli_format import (
    _format_row_for_check_only,
    _format_row_for_interactive,
    _format_value_prompt,
    _parse_since,
)
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

# Import after the runbook constant so the reverse-apply seam
# (``migration.cli_apply_reverse``) can import this constant back
# without hitting a partially-initialized module. The seam re-uses
# this constant for the ``apap-migrate apply: status=error ...``
# categorical line.
# ``run_ensure_bucket`` is defined in ``migration.cli_ensure_bucket``;
# re-exported here so ``from migration.cli import run_ensure_bucket``
# keeps working (tests + ``main`` dispatch rely on this surface).
from migration.cli_apply_reverse import (  # noqa: E402 — circular but deterministic
    APPLY_DIRECTION_LEGACY_TO_WEB,
    APPLY_DIRECTION_WEB_TO_LEGACY,
    add_direction_arg,
    run_apply,
)
from migration.cli_ensure_bucket import run_ensure_bucket  # noqa: E402,F401 — re-export

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
    add_direction_arg(apply_cmd)

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

    # --- verify-fallback-ready --------------------------------------
    # PR7 (issue #637, openspec live-data-migration-sandbox): the
    # M2 fallback-ready gate. Closes the migration openspec; the
    # gate is the operator's CI-clean signal that the bidirectional
    # migration is ready for production. ``--ci-only`` runs the
    # CI-runnable subset (round-trip test + PII audit + reverse
    # dry-run); the full mode adds the operator-attested signature
    # check. The dispatcher in main() routes to the standalone
    # ``migration.cli_verify_fallback_ready.main`` so the gate logic
    # lives in one place and the project CLI does not need to
    # import migration.verify_fallback_ready directly.
    verify_fb = sub.add_parser(
        "verify-fallback-ready",
        help=(
            "Verify the M2 fallback-ready gate. Exits 0 when every "
            "required check passes; otherwise exits 1 with "
            "missing_ci_condition=<name> on stderr."
        ),
        description=(
            "The M2 fallback-ready gate (PR7). The CI subset "
            "(--ci-only) is wired into .github/workflows/ci.yml; "
            "the full mode (no flag) is invoked by the operator "
            "before claiming the M2 milestone."
        ),
    )
    verify_fb.add_argument(
        "--ci-only",
        dest="ci_only",
        action="store_true",
        help=(
            "Run only CI-runnable checks (no operator attestation "
            "required). This is the mode the CI job uses."
        ),
    )

    return parser


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
    # noqa S608 (#387): identificadores ya validados arriba, valores por %s.
    web_client.execute_sql(
        f"UPDATE {table_name} SET {web_column} = %s WHERE id = %s",  # noqa: S608
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
        if args.command == "verify-fallback-ready":
            # Dispatch to the standalone entry point so the gate
            # logic lives in one place (migration.verify_fallback_ready).
            # The project CLI does not import that module directly
            # to keep the test surface tight; the standalone
            # module is the public face of the gate.
            from migration.cli_verify_fallback_ready import main as _vfb_main
            vfb_argv = ["--ci-only"] if args.ci_only else []
            return _vfb_main(vfb_argv)
    finally:
        if owned_web_client is not None:
            owned_web_client.close()

    # Defensive: ``required=True`` on the subparsers means argparse
    # already rejected empty invocations; this line is unreachable
    # in normal operation but keeps the return type total.
    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


__all__ = [
    "APPLY_DIRECTION_LEGACY_TO_WEB",
    "APPLY_DIRECTION_WEB_TO_LEGACY",
    "MIGRATION_RUNBOOK_REF",
    "build_parser",
    "main",
    "run_apply",
    "run_ensure_bucket",
    "run_reconcile",
    "run_status",
]
