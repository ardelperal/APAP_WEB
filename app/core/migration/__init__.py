"""Migración bidireccional web ↔ legacy Access (LIFECYCLE-03 / migration-01).

Este paquete provee la función de migración siempre disponible
(issue #13474): web → legacy para volcar el estado del web al backend
Access, y legacy → web para cargar los datos del legacy al web. La
función es atómica, bidireccional, con mapeo configurable vía YAML y
round-trip test obligatorio.

Este slice (PR 1) entrega solo el esqueleto: dataclasses ``MigrationReport``,
``Diff`` y ``Conflict``, jerarquía de excepciones, y entry point. La CLI,
los readers (legacy/web), el diff engine, el applier, los YAMLs de
mapeo y los tests E2E con sandbox .accdb llegan en PRs posteriores
(PR 2..6), cada uno como work-unit revisable individualmente.
"""

from __future__ import annotations

from app.core.migration.reporting import (
    Conflict,
    Diff,
    MigrationReport,
)


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
    "Conflict",
    "Diff",
    "FkLookupError",
    "LockActiveError",
    "MappingNotFoundError",
    "MigrationError",
    "MigrationReport",
]
