"""Migración bidireccional web ↔ legacy Access (LIFECYCLE-03 / migration-01).

Este paquete provee la función de migración siempre disponible
(issue #13474): web → legacy para volcar el estado del web al backend
Access, y legacy → web para cargar los datos del legacy al web. La
función es atómica, bidireccional, con mapeo configurable vía YAML y
round-trip test obligatorio.

PR 1/6 (issue #93) entrega el esqueleto: dataclasses ``MigrationReport``,
``Diff`` y ``Conflict``, jerarquía de excepciones, y entry point.
PR 2/6 (issue #94) entrega los 5 YAML mappings.
PR 3/6 (issue #95) entrega los readers (legacy + web) + dysflow_client stub.
PR 4/6 entrega el cerebro: ``diff_engine`` (clasificación INSERT/UPDATE/
DELETE/NOOP + conflictos ``modified_both_sides``), ``sync_state``
(persistencia atómica + lookups legacy↔web) y ``lock`` (PID + TTL +
stale recovery + pre-flight MSACCESS).
PR 5/6 entrega el applier; PR 6/6 la CLI + round-trip tests + docs.
"""

from __future__ import annotations

from app.core.migration.diff_engine import (
    Conflict as DiffEngineConflict,
)
from app.core.migration.legacy_reader import LegacyReaderError
from app.core.migration.lock import (
    DEFAULT_TTL_SECONDS,
    LockInfo,
    acquire_lock,
    check_lock,
    check_msaccess_running,
    release_lock,
)
from app.core.migration.reporting import (
    Conflict,
    Diff,
    MigrationReport,
)
from app.core.migration.sync_state import (
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
from app.core.migration.web_reader import WebReaderError


class MigrationError(Exception):
    """Base para todos los errores del módulo de migración."""


class MappingNotFoundError(FileNotFoundError, MigrationError):
    """Levantada cuando un YAML de mapeo no existe para una tabla.

    Hereda de ``FileNotFoundError`` además de ``MigrationError`` para que
    los callers genéricos que esperan ``OSError`` también la capturen.
    """


class LockActiveError(MigrationError):
    """Levantada cuando hay un lock activo de otro proceso de migración."""


class FkLookupError(MigrationError):
    """Levantada cuando no se puede resolver un FK durante el mapeo."""


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
