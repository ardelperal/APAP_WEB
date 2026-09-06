"""SQL builders for the lifecycle slice's InsForge adapter.

Per AGENTS.md §22 (query-construction seam): SQL strings and their
parameter shaping live here so the adapter orchestrates without
owning the literal SQL, and so unit tests can assert the shape of
the SQL without spinning up the transport.

The builders project web column names to the legacy field names
that ``app.modules.lifecycle.domain.animal_state.calculate_state``
consumes (the domain function mirrors ``migration/derivation.py``,
which reads the legacy ``Tb*`` table shapes). The mapping is:

- ``entradas.id`` → ``IDEntrada`` (legacy PK)
- ``entradas.fecha_salida`` → ``FSalida`` (active intake)
- ``entradas.fecha_entrega_propietario`` → ``FEntregaAPropietario``
  (P2 ``Entregado`` resolution)
- ``acogidas.id`` → ``IDAcogida``
- ``acogidas.fecha_final`` → ``FFinal`` (active foster)
- ``adopciones.id`` → ``IDAdopcion``
- ``adopciones.fecha_devolucion`` → ``FDevolucion`` (active adoption)
- ``animales.fdefuncion`` → ``FDefuncion``
- ``animales.ultimo_estado_antes_de_fallecido`` →
  ``UltimoEstadoAntesDeFallecido``
- ``animal_current_state.current_state`` → ``Situacion``
  (cached previous state for re-derivation safety)

Each builder returns ``tuple[str, list]``; the adapter in
``lifecycle_insforge_adapter.py`` invokes ``SqlExecutor.execute_sql``
on the tuple. No builder performs I/O on its own (AGENTS.md §22).

LIFECYCLE-03 (issue #33) PR-B.
"""

# Deprecated 2026-09-06: this module is no longer the production
# transport. The Coolify-hosted local backend (LocalPostgresExecutor)
# is the only supported backend as of issue #641 closing the
# self-host umbrella. This file remains so the legacy InsForge-
# touching tests can run in CI; production deploys use the
# SqlExecutor-based adapter (a follow-up slice).

from __future__ import annotations

from app.modules.lifecycle.domain.result import DerivationResult

# --- active placements (P3/P4/P5 single-active branch) -------------------

# An active intake is one whose ``fecha_salida`` is NULL (legacy
# ``FSalida`` IS NULL). The natural-key constraint on
# ``(animal_id, fecha_entrada)`` allows at most one row per
# fecha_entrada per animal, but a long-lived animal may have
# multiple historical rows whose fecha_salida is set. ``activo``
# guards against the rare tombstoned row (the schema has no
# soft-delete trigger; rows stay around when their fecha_salida is
# set).
_SELECT_ACTIVE_INTAKES_SQL = """
SELECT
    entradas.id AS "IDEntrada",
    entradas.fecha_salida AS "FSalida",
    entradas.fecha_entrega_propietario AS "FEntregaAPropietario"
FROM entradas
WHERE entradas.animal_id = $1
  AND entradas.fecha_salida IS NULL
  AND entradas.activo = true
"""


def build_select_active_intakes(animal_id: str) -> tuple[str, list]:
    """Return the SQL+params pair that lists an animal's active intakes.

    Active intakes are rows in ``entradas`` whose ``fecha_salida``
    is NULL. The projection aliases the web columns to the legacy
    field names that ``calculate_state`` reads (see module
    docstring). Empty result set means "no active intake for this
    animal" -- the cascade uses it to resolve the P3 Albergue
    branch and the P2 ``Entregado`` resolution.
    """
    return _SELECT_ACTIVE_INTAKES_SQL, [animal_id]


# --- active foster (P4 Acogida) ------------------------------------------

_SELECT_ACTIVE_FOSTERS_SQL = """
SELECT
    acogidas.id AS "IDAcogida",
    acogidas.fecha_final AS "FFinal"
FROM acogidas
WHERE acogidas.animal_id = $1
  AND acogidas.fecha_final IS NULL
  AND acogidas.activo = true
"""


def build_select_active_fosters(animal_id: str) -> tuple[str, list]:
    """Return the SQL+params pair that lists an animal's active fosters."""
    return _SELECT_ACTIVE_FOSTERS_SQL, [animal_id]


# --- active adoption (P5 Adoptado) ---------------------------------------

_SELECT_ACTIVE_ADOPTIONS_SQL = """
SELECT
    adopciones.id AS "IDAdopcion",
    adopciones.fecha_devolucion AS "FDevolucion"
FROM adopciones
WHERE adopciones.animal_id = $1
  AND adopciones.fecha_devolucion IS NULL
  AND adopciones.activo = true
"""


def build_select_active_adoptions(animal_id: str) -> tuple[str, list]:
    """Return the SQL+params pair that lists an animal's active adoptions."""
    return _SELECT_ACTIVE_ADOPTIONS_SQL, [animal_id]


# --- animal ficha (P1 death detection + P6 pre-death parenthetical) ------

# LEFT JOIN on ``animal_current_state`` so the cached state string
# (``Situacion``) is available to ``_resolve_pre_death_state`` for
# re-derivation safety -- if the cache already carries
# ``Fallecido (X)``, the cascade must NOT wrap it again. An animal
# with no cache row (e.g. never-derivered) returns ``Situacion =
# ''`` and the cascade falls through to ``Desconocido``.
_SELECT_FICHA_SQL = """
SELECT
    animales.fdefuncion AS "FDefuncion",
    animales.ultimo_estado_antes_de_fallecido AS "UltimoEstadoAntesDeFallecido",
    COALESCE(animal_current_state.current_state, '') AS "Situacion"
FROM animales
LEFT JOIN animal_current_state
    ON animal_current_state.animal_id = animales.id
WHERE animales.id = $1
  AND animales.activo = true
"""


def build_select_ficha(animal_id: str) -> tuple[str, list]:
    """Return the SQL+params pair that loads an animal's ficha fields.

    The projection carries the three legacy-named columns the
    cascade reads (``FDefuncion``, ``UltimoEstadoAntesDeFallecido``,
    ``Situacion``). When the animal does not exist the executor
    returns an empty list; the cascade treats that as "no death,
    no entries" and falls through to ``Pendiente de Entrada``.
    """
    return _SELECT_FICHA_SQL, [animal_id]


# --- upsert current state (cache write) ----------------------------------

# The cache carries a CHECK-constrained ``current_state`` value
# (12 allowed strings, see ``app/core/domain_lifecycle.py:147-156``)
# plus the placement IDs and pre-death state produced by the domain
# cascade. Terminal states clear placement IDs so an upsert cannot
# retain stale references from the previous cache row.
#
# ``ON CONFLICT (animal_id) DO UPDATE`` is the natural-key arbiter
# (the ``animal_current_state`` PK is on ``animal_id``).
_UPSERT_CURRENT_STATE_SQL = """
INSERT INTO animal_current_state (
    animal_id,
    current_state,
    active_intake_id,
    active_foster_id,
    active_adoption_id,
    pre_death_state,
    state_changed_at,
    reconciliation_status
) VALUES ($1, $2, $3, $4, $5, $6, now(), 'matched')
ON CONFLICT (animal_id) DO UPDATE SET
    current_state = EXCLUDED.current_state,
    active_intake_id = EXCLUDED.active_intake_id,
    active_foster_id = EXCLUDED.active_foster_id,
    active_adoption_id = EXCLUDED.active_adoption_id,
    pre_death_state = EXCLUDED.pre_death_state,
    state_changed_at = EXCLUDED.state_changed_at,
    reconciliation_status = 'matched'
"""

def build_upsert_current_state(
    animal_id: str,
    result: DerivationResult,
) -> tuple[str, list]:
    """Return the SQL+params pair that upserts the cache row.

    ``result.state`` must be one of the 12 CHECK-allowed strings; the
    cascade guarantees that contract. Terminal placement IDs are guaranteed
    to be ``None`` by the domain cascade (see ``DerivationResult`` docstring
    and ``test_terminal_states_have_no_placement_ids``); the adapter does not
    defensively re-clear them. Only ``fallecido`` retains ``pre_death_state``.
    """
    kind = str(getattr(result.kind, "value", result.kind))
    pre_death_state = result.pre_death_state if kind == "fallecido" else None
    return _UPSERT_CURRENT_STATE_SQL, [
        animal_id,
        result.state,
        result.active_intake_id,
        result.active_foster_id,
        result.active_adoption_id,
        pre_death_state,
    ]


__all__ = [
    "build_select_active_intakes",
    "build_select_active_fosters",
    "build_select_active_adoptions",
    "build_select_ficha",
    "build_upsert_current_state",
]
