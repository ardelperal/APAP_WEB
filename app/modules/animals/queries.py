"""SQL builder seam for ``app.modules.animals`` per AGENTS.md §22.

The query/service separation: SQL strings and parameter shaping live
here in pure builder functions that return ``(sql, params)`` tuples.
The service module (``app/modules/animals/service.py``) imports
these builders, applies domain validation, and talks to the SQL
executor.

Rule §22 — the seam is testable: the shape of the SQL is assertable
in a plain unit test without spinning up transport, InsForge, or HTTP.

Rule §1 — routes must never import from this module. The graph is
``routes.py -> service.py -> queries.py``; ``routes.py -> queries.py``
would violate the layer boundary.

Rule §4 — column lists and SQL templates live in exactly one place.
The animal search column set and filter logic are NOT redefined
anywhere else in the module.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as _dataclass_replace
from enum import StrEnum
from typing import Any, NamedTuple

# --- domain enums (shared with service.py) ----------------------------------


class Especie(StrEnum):
    CANINA = "CANINA"
    FELINA = "FELINA"


class Sexo(StrEnum):
    M = "M"
    H = "H"


# Mapping from API snake_case estado values to DB Spanish labels.
# Single source of truth per AGENTS.md §4.
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


# --- search params ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnimalSearchParams:
    q: str | None = None
    chip: str | None = None
    especie: str | None = None
    sexo: str | None = None
    estado: str | None = None
    fecha_alta_since: str | None = None
    fecha_alta_until: str | None = None
    limit: int = 50
    offset: int = 0

    def cap_limit(self) -> AnimalSearchParams:
        """Cap limit at 200 per spec."""
        if self.limit > 200:
            return _dataclass_replace(self, limit=200)
        return self




# --- base column list -------------------------------------------------------


_ANIMAL_SEARCH_COLUMNS: tuple[str, ...] = (
    "a.id",
    "a.NCHIP",
    "a.NombreAnimal",
    "a.Especie",
    "a.Sexo",
    "a.FNacimiento",
    "a.fecha_alta",
    "a.activo",
    "acs.current_state",
)


# --- query builders ---------------------------------------------------------


class SearchResult(NamedTuple):
    sql: str
    params: list[Any]


def build_animal_search(
    params: AnimalSearchParams,
) -> SearchResult:
    """Build the animal search query with filters.

    The ``estado`` filter requires a LEFT JOIN to ``animal_current_state``
    because the state is derived from the lifecycle event log and cached
    there (LIFECYCLE-02 / issue #69). When no ``estado`` filter is present
    the join is still included so the SELECT list can surface ``current_state``
    in the response without an extra round-trip.

    Parameters
    ----------
    params : AnimalSearchParams
        Search parameters. ``chip`` takes precedence over ``q`` (exact match
        vs substring). ``limit=0`` signals a count-only request: the caller
        should skip the data query and return only the total.

    Returns
    -------
    SearchResult
        ``(sql, params)`` ready to pass to ``client.execute_sql``.
    """
    p = params.cap_limit()

    conditions: list[str] = ["a.activo = true"]
    query_params: list[Any] = []

    # chip exact match — takes precedence over q
    if p.chip:
        conditions.append("a.NCHIP = $" + str(len(query_params) + 1))
        query_params.append(p.chip)

    # q: substring match on nombre (case-insensitive via ILIKE)
    # Only used when chip is not present
    if p.q and not p.chip:
        conditions.append("a.NombreAnimal ILIKE $" + str(len(query_params) + 1))
        query_params.append("%" + p.q + "%")

    # especie exact match
    if p.especie:
        conditions.append("a.Especie = $" + str(len(query_params) + 1))
        query_params.append(p.especie)

    # sexo exact match
    if p.sexo:
        conditions.append("a.Sexo = $" + str(len(query_params) + 1))
        query_params.append(p.sexo)

    # estado filter — requires JOIN with animal_current_state
    if p.estado:
        db_label = _ESTADO_DB_LABEL.get(p.estado)
        if db_label:
            conditions.append("acs.current_state = $" + str(len(query_params) + 1))
            query_params.append(db_label)

    # fecha_alta range
    if p.fecha_alta_since:
        conditions.append("a.fecha_alta >= $" + str(len(query_params) + 1))
        query_params.append(p.fecha_alta_since)
    if p.fecha_alta_until:
        conditions.append("a.fecha_alta <= $" + str(len(query_params) + 1))
        query_params.append(p.fecha_alta_until)

    where_clause = " AND ".join(conditions)

    # Assemble the query with optional LIMIT/OFFSET
    # LIMIT 0 signals count-only (no data rows returned)
    if p.limit == 0:
        sql = (
            f"SELECT COUNT(*) AS total "  # noqa: S608 constant identifiers; values are $N binds
            f"FROM animales a "
            f"LEFT JOIN animal_current_state acs ON a.id = acs.animal_id "
            f"WHERE {where_clause}"
        )
    else:
        sql = (
            f"SELECT {', '.join(_ANIMAL_SEARCH_COLUMNS)} "  # noqa: S608 constant identifiers
            f"FROM animales a "
            f"LEFT JOIN animal_current_state acs ON a.id = acs.animal_id "
            f"WHERE {where_clause} "
            f"ORDER BY a.fecha_alta DESC "
            f"LIMIT ${len(query_params) + 1} OFFSET ${len(query_params) + 2}"
        )
        query_params.extend([p.limit, p.offset])

    return SearchResult(sql=sql, params=query_params)


def build_animal_count(params: AnimalSearchParams) -> SearchResult:
    """Build a count-only query for total (used when limit > 0)."""
    p = params.cap_limit()

    conditions: list[str] = ["a.activo = true"]
    query_params: list[Any] = []

    if p.chip:
        conditions.append("a.NCHIP = $" + str(len(query_params) + 1))
        query_params.append(p.chip)
    if p.q and not p.chip:
        conditions.append("a.NombreAnimal ILIKE $" + str(len(query_params) + 1))
        query_params.append("%" + p.q + "%")
    if p.especie:
        conditions.append("a.Especie = $" + str(len(query_params) + 1))
        query_params.append(p.especie)
    if p.sexo:
        conditions.append("a.Sexo = $" + str(len(query_params) + 1))
        query_params.append(p.sexo)
    if p.estado:
        db_label = _ESTADO_DB_LABEL.get(p.estado)
        if db_label:
            conditions.append("acs.current_state = $" + str(len(query_params) + 1))
            query_params.append(db_label)
    if p.fecha_alta_since:
        conditions.append("a.fecha_alta >= $" + str(len(query_params) + 1))
        query_params.append(p.fecha_alta_since)
    if p.fecha_alta_until:
        conditions.append("a.fecha_alta <= $" + str(len(query_params) + 1))
        query_params.append(p.fecha_alta_until)

    where_clause = " AND ".join(conditions)

    sql = (
        f"SELECT COUNT(*) AS total "  # noqa: S608 constant identifiers; values are $N binds
        f"FROM animales a "
        f"LEFT JOIN animal_current_state acs ON a.id = acs.animal_id "
        f"WHERE {where_clause}"
    )
    return SearchResult(sql=sql, params=query_params)
