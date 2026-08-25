"""Animals domain entity and enums (AGENTS.md §31: domain has no I/O).

Field names match the schema in CamelCase Spanish per
``docs/discovery/feature-01-animal-lifecycle.md`` and the legacy
``TbFichaAnimal`` mapping. The :class:`Animal` dataclass carries the
complete 28-field read shape. ``updated_at`` stays adapter-internal
because legacy application surfaces never expose it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_INSERT_COLUMNS = (
    "NCHIP",
    "NombreAnimal",
    "Especie",
    "Sexo",
    "FNacimiento",
    "TraeNChip",
    "FIMPLANTACIONCHIP",
    "Raza",
    "Color",
    "Pelo",
    "Tamano",
    "Caracter",
    "FDefuncion",
    "Terapia",
    "Observaciones",
    "NombreFoto",
    "Cartilla",
    "Eutanasia",
    "RazaPPP",
    "Mestizo",
    "EutanasiaOtrasCausas",
    "EutanasiaEnfermedad",
    "UltimoEstadoAntesDeFallecido",
    "ComunicacionARIAC",
)


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
    """The complete 28-field animal read entity.

    ``id`` is the UUID primary key. ``FNacimiento`` is ``DATE`` on
    the wire and an ISO 8601 string in the API. ``activo`` defaults
    to ``True`` (the column is ``NOT NULL DEFAULT TRUE``). The 21
    widened fields are optional so seven-field adapter rows remain
    valid. ``updated_at`` is intentionally excluded because it is a
    system-internal column that legacy API surfaces never exposed.
    """

    id: str
    NCHIP: str
    NombreAnimal: str
    Especie: Especie
    Sexo: Sexo
    FNacimiento: str
    activo: bool = True
    fecha_alta: str | None = None
    estado: str | None = None
    TraeNChip: str | None = None
    FIMPLANTACIONCHIP: str | None = None
    Raza: str | None = None
    Color: str | None = None
    Pelo: str | None = None
    Tamano: str | None = None
    Caracter: str | None = None
    FDefuncion: str | None = None
    Terapia: str | None = None
    Observaciones: str | None = None
    NombreFoto: str | None = None
    Cartilla: str | None = None
    Eutanasia: str | None = None
    RazaPPP: str | None = None
    Mestizo: str | None = None
    EutanasiaOtrasCausas: str | None = None
    EutanasiaEnfermedad: str | None = None
    UltimoEstadoAntesDeFallecido: str | None = None
    ComunicacionARIAC: str | None = None


@dataclass(frozen=True, slots=True)
class AnimalSearchResult:
    """Paginated search result for ``AnimalsPort.search_animals``.

    Mirrors the legacy ``service.search_animals`` contract: data + total +
    pagination. ``data`` carries the complete :class:`Animal` read entity.
    """

    data: tuple[Animal, ...]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Animal estado mappings (domain-owned, single source of truth per §4).
# ---------------------------------------------------------------------------
#
# Canonical spelling (LIFECYCLE-03 PR-C MODIFIED Requirement
# ``animal-state-db-label-spelling``):
#
# - ``pendiente_nueva_situacion`` carries the accented
#   ``"Pendiente de Nueva Situación"`` (with acute) — matches the
#   ``animal_current_state`` CHECK constraint at
#   ``app/core/domain_lifecycle.py:149`` and the cascade output at
#   ``app/modules/lifecycle/domain/constants.py:17``.
# - ``fallecido`` is split into the 5 CHECK-allowed variants
#   (``fallecido_albergue`` … ``fallecido_desconocido``). The previous
#   collapsed ``fallecido`` key that mapped every death to
#   ``"Fallecido (Albergue)"`` was the P1 fidelity gap: the cascade
#   writes 5 distinct strings to ``animal_current_state.current_state``
#   (one per pre-death state + ``Desconocido``), and a search filter
#   that collapsed them to one DB label silently undercounted the
#   REPORT-05 dashboard counters.
_ESTADO_DB_LABEL: dict[str, str] = {
    "pendiente_entrada": "Pendiente de Entrada",
    "pendiente_nueva_situacion": "Pendiente de Nueva Situación",
    "albergue": "Albergue",
    "acogida": "Acogida",
    "adoptado": "Adoptado",
    "entregado": "Entregado",
    "fallecido_albergue": "Fallecido (Albergue)",
    "fallecido_acogida": "Fallecido (Acogida)",
    "fallecido_adoptado": "Fallecido (Adoptado)",
    "fallecido_entregado": "Fallecido (Entregado)",
    "fallecido_desconocido": "Fallecido (Desconocido)",
    "incoherente": "Incoherente",
}

# Reverse mapping: DB Spanish label → API snake_case estado.
# Single source of truth for DB→API normalization (AGENTS.md §4).
DB_LABEL_TO_ESTADO: dict[str, str] = {v: k for k, v in _ESTADO_DB_LABEL.items()}

# Valid API estado values.
VALID_ESTADOS: frozenset[str] = frozenset(_ESTADO_DB_LABEL)


__all__ = [
    "Animal",
    "AnimalSearchResult",
    "DB_LABEL_TO_ESTADO",
    "Especie",
    "Sexo",
    "VALID_ESTADOS",
    "_INSERT_COLUMNS",
]
