"""Animals domain entity and enums (AGENTS.md §31: domain has no I/O).

Field names match the schema in CamelCase Spanish per
``docs/discovery/feature-01-animal-lifecycle.md`` and the legacy
``TbFichaAnimal`` mapping. The :class:`Animal` dataclass is a partial
migration target — only the columns the first read use case
(``get_animal_by_nchip``) needs to round-trip are present; write
paths will land additional columns as they migrate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Especie(StrEnum):
    """Species per legacy ``TbFichaAnimal.Especie``."""

    CANINA = "CANINA"
    FELINA = "FELINA"


class Sexo(StrEnum):
    """Sex per legacy ``TbFichaAnimal.Sexo``."""

    M = "M"
    H = "H"


@dataclass(frozen=True, slots=True)
class Animal:
    """A row of the ``animales`` table as the read side needs it.

    ``id`` is the UUID primary key. ``FNacimiento`` is ``DATE`` on
    the wire and an ISO 8601 string in the API. ``activo`` defaults
    to ``True`` (the column is ``NOT NULL DEFAULT TRUE``).
    """

    id: str
    NCHIP: str
    NombreAnimal: str
    Especie: Especie
    Sexo: Sexo
    FNacimiento: str
    activo: bool = True


__all__ = ["Animal", "Especie", "Sexo"]
