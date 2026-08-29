"""Voluntarios domain entity and enums.

Slice: app/modules/voluntarios (epic #420 PR-A).
Schema column names match the bootstrap schema in
``app/core/domain_voluntarios.py`` (lowercase: ``voluntario``, ``tel1``, etc.).
The InsForge adapter maps these to/from the transport row dicts.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Voluntario:
    """A row from the ``voluntarios`` table.

    Field names match the bootstrap schema (lowercase) defined in
    ``app/core/domain_voluntarios.py``.  The adapter translates between
    DB column names and this dataclass; the domain never touches SQL.

    ``id`` is the UUID primary key generated at INSERT time.
    ``activo`` starts ``True``; soft-delete sets it to ``False``.
    ``email`` and ``dni`` are UNIQUE in the DB — a duplicate raises
    the adapter's ``UniqueViolation`` which the use case translates to HTTP 409.
    """

    id: str
    voluntario: str
    activo: bool = True
    tel1: str | None = None
    tel2: str | None = None
    email: str | None = None
    dni: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None


__all__ = ["Voluntario"]
