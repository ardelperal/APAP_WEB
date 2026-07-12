"""ETL one-time de migracion web <-> legacy Access (issue #93).

Este paquete provee la funcion de migracion siempre disponible:
web -> legacy para volcar el estado del web al backend Access, y
legacy -> web para cargar los datos del legacy al web. La funcion es
atomica, bidireccional, con mapeo configurable via YAML y round-trip
test obligatorio.

Public surface (re-exported here so callers can do
``from migration import X``):

PR 1/6 (issue #93) entrego el esqueleto: dataclasses ``MigrationReport``,
``Diff`` y ``Conflict``, jerarquia de excepciones, y entry point.
PR 2/6 (issue #94) entrego los 5 YAML mappings.
PR 3/6 (issue #95) entrego los readers (legacy + web) + dysflow_client stub.
PR 4/6 entrego el cerebro: ``diff_engine`` (clasificacion INSERT/UPDATE/
DELETE/NOOP + conflictos ``modified_both_sides``), ``sync_state``
(persistencia atomica + lookups legacy->web) y ``lock`` (PID + TTL +
stale recovery + pre-flight MSACCESS).
PR 5/6 entrego el applier; PR 6/6 la CLI + round-trip tests + docs.

This package is NOT shipped in the production wheel
(``pyproject.toml [tool.hatch.build.targets.wheel] only-include = ["app", "tests"]``).
The web application's runtime cold-start imports
``app.core.migration.sql_runner.apply_sql_migrations`` which lives
in ``app/core/migration/`` (separate from this package). The split
keeps the production image small and the ETL installable only on
operator machines that need to run the one-time data migration.
"""

from __future__ import annotations

from migration.diff_engine import (
    Conflict as DiffEngineConflict,
)
from migration.legacy_reader import LegacyReaderError
from migration.lock import (
    DEFAULT_TTL_SECONDS,
    LockInfo,
    acquire_lock,
    check_lock,
    check_msaccess_running,
    release_lock,
)
from migration.reporting import (
    Conflict,
    Diff,
    MigrationReport,
)
from migration.sync_state import (
    SyncState,
    SyncStateError,
    TableState,
    get_or_create_table_state,
    load_sync_state,
    lookup_legacy_pk,
    lookup_web_pk,
    record_legacy_to_web_mapping,
    save_sync_state,
    update_last_sync_at,
)
from migration.web_reader import WebReaderError


class MigrationError(Exception):
    """Base para todos los errores del modulo de migracion."""


class MappingNotFoundError(FileNotFoundError, MigrationError):
    """Levantada cuando un YAML de mapeo no existe para una tabla.

    Hereda de ``FileNotFoundError`` ademas de ``MigrationError`` para que
    los callers genericos que esperan ``OSError`` tambien la capturen.
    """


class LockActiveError(MigrationError):
    """Levantada cuando hay un lock activo de otro proceso de migracion."""


class FkLookupError(MigrationError):
    """Levantada cuando no se puede resolver un FK durante el mapeo."""


class MsAccessPreflightUnavailableError(MigrationError):
    """The MSACCESS pre-flight could not be performed (fail-closed).

    Raised by ``check_msaccess_running`` when ``psutil`` is missing
    on the operator box OR when ``psutil.process_iter`` raises during
    iteration (permission denied, transient OS error, etc.).

    The apply pipeline MUST fail closed when the preflight cannot
    run — better to abort than to claim "no MSACCESS live" while the
    check was unable to actually look. The CLI converts this
    exception to exit 5 with reason ``msaccess_preflight_unavailable``.

    Categorical reasons (no PII, no process/error data):

    - ``REASON_PSUTIL_MISSING`` — ``import psutil`` failed at module load.
    - ``REASON_PROCESS_ITERATION_FAILED`` — ``psutil.process_iter``
      raised mid-iteration. The apply MUST NOT catch this and
      attempt recovery — fail closed, let the operator diagnose
      via the runbook.

    Dry-run (``--check-only``) bypasses the preflight entirely; this
    exception never fires on the dry-run path.
    """

    REASON_PSUTIL_MISSING = "psutil_missing"
    REASON_PROCESS_ITERATION_FAILED = "process_iteration_failed"

    def __init__(self, *, reason: str) -> None:
        super().__init__(f"msaccess preflight unavailable: {reason}")
        self.reason = reason


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "Conflict",
    "Diff",
    "DiffEngineConflict",
    "FkLookupError",
    "LegacyReaderError",
    "LockActiveError",
    "LockInfo",
    "MappingNotFoundError",
    "MigrationError",
    "MigrationReport",
    "MsAccessPreflightUnavailableError",
    "SyncState",
    "SyncStateError",
    "TableState",
    "WebReaderError",
    "acquire_lock",
    "check_lock",
    "check_msaccess_running",
    "get_or_create_table_state",
    "load_sync_state",
    "lookup_legacy_pk",
    "lookup_web_pk",
    "record_legacy_to_web_mapping",
    "release_lock",
    "save_sync_state",
    "update_last_sync_at",
]
