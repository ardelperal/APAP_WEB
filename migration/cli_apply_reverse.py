"""Reverse-direction (``web-to-legacy``) seam for ``apap-migrate apply``.

PR6 introduced the ``--direction`` flag with two accepted values:
``legacy-to-web`` (default; PR3 / M1 forward) and ``web-to-legacy``
(PR6 / M2 reverse). The reverse path builds a ``MigrationReport``
with ``direction="web-to-legacy"``, instantiates the
``DniCollisionCounter``, dispatches per-table to
``migration.apply_reverse.apply_web_to_legacy``, and threads the
report through the same typed-exception / exit-code contract as
the forward path (PR3 verification remediation).

Module attribute lookup — not name binding — is used for the
``apply_legacy_to_web`` call inside :func:`run_apply` so the
``tests/migration/test_cli_apply_safety.py`` atoms that monkeypatch
``migration.cli.apply_legacy_to_web`` still observe their patched
callable. Pattern mirrors the ``logging_mod.log_safe`` /
``semantic_events_mod.record_lifecycle_reversed`` seams that PR6
established in the reverse applier (commit e69aa2b).

Backwards compat: ``migration/cli.py`` re-exports :func:`run_apply`
and the ``APPLY_DIRECTION_*`` constants so the existing CLI entry
point and the 12 ``test_cli_apply_safety.py`` atoms continue to
import ``from migration.cli import run_apply`` unchanged.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import UTC, datetime
from typing import IO

import migration.cli as cli_mod
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.logging import log_safe
from migration import MsAccessPreflightUnavailableError
from migration.apply import (
    ApplyResult,
    MsAccessRunningError,
    PartialApplyInterruptedError,
    SourceDriftError,
)
from migration.apply_reverse import apply_web_to_legacy
from migration.cli import MIGRATION_RUNBOOK_REF
from migration.dni_collision import DniCollisionCounter
from migration.legacy_reader import LegacyReaderError
from migration.mappings import list_available_tables
from migration.reporting import MigrationReport

# Direction flag values (PR6 / M2 reverse apply). The forward path
# remains ``legacy-to-web`` (default); the operator opts in to the
# reverse path with ``apap-migrate apply --direction web-to-legacy``.
# Closed vocabulary; PR7's verify-fallback-ready gate reads the
# same flag to assert the reverse branch was exercised.
APPLY_DIRECTION_LEGACY_TO_WEB = "legacy-to-web"
APPLY_DIRECTION_WEB_TO_LEGACY = "web-to-legacy"


def add_direction_arg(apply_cmd: argparse.ArgumentParser) -> None:
    """Add the ``--direction`` flag to the apply subparser.

    Re-binding seam from PR6 — kept here so the flag setup (which
    only matters for the reverse direction) lives next to the
    constant vocabulary and the orchestrator that consumes it.

    The default ``legacy-to-web`` preserves PR1..PR5 callers; the
    ``web-to-legacy`` value opts in to the M2 reverse applier.
    """
    apply_cmd.add_argument(
        "--direction",
        dest="direction",
        choices=(APPLY_DIRECTION_LEGACY_TO_WEB, APPLY_DIRECTION_WEB_TO_LEGACY),
        default=APPLY_DIRECTION_LEGACY_TO_WEB,
        help=(
            "Apply direction. ``legacy-to-web`` (default) reads from the "
            "legacy ``.accdb`` and writes into the web DB (PR3 / M1). "
            "``web-to-legacy`` reads from the web DB and writes to the "
            "legacy ``.accdb`` via the reverse applier (PR6 / M2). "
            "The reverse path carries the MSACCESS pre-flight, the "
            "advisory lock, the per-strategy preserve/derived/fixed "
            "rules from ``web-only-feature-preservation/spec.md``, "
            "the LIFECYCLE_REVERSED event surface, and the rowcount=0 "
            "drift detection that records ``needs_review`` rows."
        ),
    )


def _format_apply_error(reason: str, *, exit_code: int) -> str:
    """Render the canonical ``apap-migrate apply`` error line.

    Format is deterministic so log scrapers and operator tooling can
    parse it without regex on free-form text. The line carries ONLY
    a categorical reason + exit code + stable runbook reference —
    no raw exception payloads, no PII, no filesystem paths.
    """
    return (
        f"apap-migrate apply: status=error "
        f"reason={reason} exit={exit_code} runbook={MIGRATION_RUNBOOK_REF}\n"
    )


def _emit_migration_report(
    report: MigrationReport,
    results: list[ApplyResult],
    *,
    started_at: datetime,
    stream: IO[str],
    dry_run: bool,
    error: str | None = None,
    emit_stream: bool = False,
) -> None:
    """Finalize the per-run ``MigrationReport`` and emit it.

    Used by every typed-exception handler in :func:`run_apply` and
    by the happy-path tail. The function is module-private; the
    public surface (CLI subcommands) reads the report through
    :func:`migration.reporting.MigrationReport` directly.
    """
    finished_at = datetime.now(UTC)
    finalized = replace(
        report,
        applied=not dry_run and any(result.applied > 0 for result in results),
        finished_at=finished_at,
        duration_seconds=(finished_at - started_at).total_seconds(),
        error=error,
    )
    if emit_stream:
        stream.write(finalized.to_json() + "\n")
    else:
        log_safe(
            "migration.report",
            report=finalized.to_json(),
        )


# Exception → (categorical reason, exit code) mapping used by
# :func:`_emit_apply_categorical_error` to consolidate the six
# ``except`` branches the apply pipeline may raise. ``LegacyReaderError``
# and ``InsForgeError`` are excluded because their reason strings are
# not derivable from the exception class alone — they need the
# original branching for the per-class comment that documents why
# the operator sees a categorical line.
_APPLY_EXIT_CODE_BY_EXCEPTION: dict[type[BaseException], tuple[str, int]] = {
    MsAccessPreflightUnavailableError: ("msaccess_preflight_unavailable", 5),
    MsAccessRunningError: ("msaccess_running", 5),
    SourceDriftError: ("source_drift", 6),
    PartialApplyInterruptedError: ("partial_apply_interrupted", 7),
}


def _emit_apply_categorical_error(
    stream: IO[str],
    migration_report: MigrationReport,
    results: list[ApplyResult],
    *,
    started_at: datetime,
    dry_run: bool,
    exc: BaseException,
) -> int:
    """Emit the canonical ``apap-migrate apply`` error line + report.

    Returns the exit code associated with ``exc`` (looked up in
    :data:`_APPLY_EXIT_CODE_BY_EXCEPTION`). Extracted from
    :func:`run_apply` so the parent function stays under the PLR0911
    return-statement cap.
    """
    reason, exit_code = _APPLY_EXIT_CODE_BY_EXCEPTION[type(exc)]
    stream.write(_format_apply_error(reason, exit_code=exit_code))
    _emit_migration_report(
        migration_report,
        results,
        started_at=started_at,
        stream=stream,
        dry_run=dry_run,
        error=reason,
    )
    return exit_code


def _apply_tables(
    args: argparse.Namespace,
    web_client: InsForgeClient,
    stream: IO[str],
    *,
    started_at: datetime,
    migration_report: MigrationReport,
    since: datetime | None,
    tables: list[str],
) -> int:
    """Per-table apply loop with the typed-exception / exit-code contract.

    Extracted from :func:`run_apply` so the parent function stays under
    the PLR0911 return-statement cap. Returns the exit code; emits the
    final per-row summary on success.
    """
    dni_collision_counter = DniCollisionCounter()
    results: list[ApplyResult] = []
    direction = getattr(args, "direction", APPLY_DIRECTION_LEGACY_TO_WEB)

    try:
        for table in tables:
            if direction == APPLY_DIRECTION_WEB_TO_LEGACY:
                results.append(
                    apply_web_to_legacy(
                        web_client,
                        table,
                        legacy_path=args.legacy_path,
                        dry_run=bool(args.check_only),
                        web_snapshot=None,
                        lock_path=None,
                        dni_collision_counter=dni_collision_counter,
                        migration_report=migration_report,
                    )
                )
                continue
            results.append(
                cli_mod.apply_legacy_to_web(
                    web_client,
                    table,
                    legacy_path=args.legacy_path,
                    since=since,
                    dry_run=bool(args.check_only),
                )
            )
    except (MsAccessPreflightUnavailableError, MsAccessRunningError,
            SourceDriftError, PartialApplyInterruptedError) as exc:
        return _emit_apply_categorical_error(
            stream,
            migration_report,
            results,
            started_at=started_at,
            dry_run=bool(args.check_only),
            exc=exc,
        )
    except LegacyReaderError:
        # pyodbc I/O failure. The exception's ``str()`` can include the
        # failing SQL fragment — categorical only.
        stream.write(_format_apply_error("legacy_read_failed", exit_code=5))
        _emit_migration_report(
            migration_report,
            results,
            started_at=started_at,
            stream=stream,
            dry_run=bool(args.check_only),
            error="legacy_read_failed",
        )
        return 5
    except InsForgeError:
        # Bootstrap failure (private bucket missing, shadow table
        # invariant broken, etc.). ``InsForgeError.body`` may carry
        # internal server-side details — categorical only.
        stream.write(_format_apply_error("infra_bootstrap_failed", exit_code=5))
        _emit_migration_report(
            migration_report,
            results,
            started_at=started_at,
            stream=stream,
            dry_run=bool(args.check_only),
            error="infra_bootstrap_failed",
        )
        return 5

    for result in results:
        action = "would insert" if args.check_only else "inserted"
        stream.write(
            f"table={result.table_name} {action}={result.applied} "
            f"skipped={result.skipped} errors={len(result.errors)}\n"
        )
        for error in result.errors:
            stream.write(f"  error={error}\n")
    exit_code = 0 if not any(r.errors for r in results) else 1
    _emit_migration_report(
        migration_report,
        results,
        started_at=started_at,
        stream=stream,
        dry_run=bool(args.check_only),
        emit_stream=True,
    )
    return exit_code


def _parse_since_or_emit(
    args: argparse.Namespace,
    stream: IO[str],
    migration_report: MigrationReport,
    *,
    started_at: datetime,
) -> datetime | str | None:
    """Parse ``args.since`` as ISO-8601, or emit an invalid_timestamp report.

    Returns ``None`` when ``args.since`` is unset, the parsed
    ``datetime`` when parsing succeeds, or the literal string
    ``"_INVALID_TIMESTAMP"`` (a sentinel object) when parsing fails
    so the caller knows to emit the failure report and return exit
    code 2.
    """
    if args.since is None:
        return None
    try:
        return datetime.fromisoformat(args.since)
    except (TypeError, ValueError) as exc:
        stream.write(f"apap-migrate apply: invalid ISO-8601 timestamp {args.since!r}: {exc}\n")
        _emit_migration_report(
            migration_report,
            [],
            started_at=started_at,
            stream=stream,
            dry_run=bool(args.check_only),
            error="invalid_timestamp",
        )
        return _INVALID_TIMESTAMP


# Sentinel returned by :func:`_parse_since_or_emit` when ``args.since``
# is not a valid ISO-8601 timestamp. The string identity is checked
# with ``is`` (not equality) so the caller does not accidentally match
# a real ISO-8601 string.
_INVALID_TIMESTAMP = "_INVALID_TIMESTAMP"


def run_apply(
    args: argparse.Namespace,
    *,
    web_client: InsForgeClient | None = None,
    stream: IO[str] | None = None,
) -> int:
    """Body of ``apap-migrate apply`` (PR3 / M1 forward + PR6 / M2 reverse).

    Exit code contract (PR3 verification remediation, per user
    directive 2026-07-11) — every typed exception produces a single
    categorical line on the operator stream:

        apap-migrate apply: status=error reason=<cat> exit=<N> runbook=<ref>

    The reasons form a closed vocabulary; the exit codes are
    deterministic. The runbook reference is the stable constant
    :data:`migration.cli.MIGRATION_RUNBOOK_REF`. Operator output
    carries no traceback, no raw exception payloads, no PII, and no
    filesystem paths — the operator reads the runbook for the
    verbose interpretation.

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

    Monkeypatchability: the forward ``apply_legacy_to_web`` call
    goes through ``cli_mod.apply_legacy_to_web`` (module attribute
    lookup) so tests that patch ``migration.cli.apply_legacy_to_web``
    see their patched callable. This preserves the test surface
    that PR3's typed-exit-code contract was authored against.
    """
    if stream is None:
        stream = sys.stdout
    if web_client is None:
        sys.stderr.write("apap-migrate apply: requires a web_client in this runtime\n")
        return 2

    started_at = datetime.now(UTC)
    migration_report = MigrationReport(
        direction=(
            "web-to-legacy"
            if getattr(args, "direction", APPLY_DIRECTION_LEGACY_TO_WEB)
            == APPLY_DIRECTION_WEB_TO_LEGACY
            else "legacy-to-web"
        ),
        mode="dry-run" if args.check_only else "full",
        dry_run=bool(args.check_only),
        applied=False,
        started_at=started_at,
        finished_at=started_at,
        duration_seconds=0.0,
    )

    since = _parse_since_or_emit(args, stream, migration_report, started_at=started_at)
    if since is _INVALID_TIMESTAMP:
        return 2

    tables = [args.table] if args.table else list_available_tables()
    # ``_parse_since_or_emit`` narrowed to ``datetime | str | None``;
    # the ``_INVALID_TIMESTAMP`` branch returned above, so the
    # remaining value is ``datetime | None`` (or ``None`` when unset).
    return _apply_tables(
        args,
        web_client,
        stream,
        started_at=started_at,
        migration_report=migration_report,
        since=since,  # type: ignore[arg-type]
        tables=tables,
    )


__all__ = [
    "APPLY_DIRECTION_LEGACY_TO_WEB",
    "APPLY_DIRECTION_WEB_TO_LEGACY",
    "add_direction_arg",
    "run_apply",
]
