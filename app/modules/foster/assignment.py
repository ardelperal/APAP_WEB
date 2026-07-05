"""Service layer for FOSTER-03 foster assignment gate.

FOSTER-03 (#45) implementa el **gate de admision** entre animales y
casas de acogida: hard block por especie + advisory de capacidad con
override auditado. Este modulo es ortogonal a ``foster.service``
(CRUD de casas) y a ``acogidas.service`` (CRUD de estancias); el
gate evalua "¿puedo asignar este animal a esta casa?" antes del
create de la estancia, sin modificar el create existente
(decisión D-GC-05).

Superficie pública:

- :class:`AssignmentDecision` y :class:`FosterCapacityOverride`:
  dataclasses de salida.
- :func:`evaluate_assignment`: ejecuta el gate (especie + capacidad)
  y devuelve un ``AssignmentDecision`` describiendo admit / block /
  admit_with_warning.
- :func:`record_override`: graba un override de capacidad en
  ``foster_capacity_overrides`` (audit log) tras validar motivo
  obligatorio.
- :func:`list_overrides_for_casa`: lista overrides aplicadas a una
  casa para el detail/overrides.html.

Decisiones aplicadas (justificadas en
``openspec/changes/foster-gate-capacidad/proposal.md``):

- D-GC-01: tabla propia ``foster_capacity_overrides`` (no reusar
  ``animal_lifecycle_events``).
- D-GC-02: ``operador_user_id`` UUID del session, no email.
- D-GC-03: capacity cuenta solo estancias de la especie preferida
  (OD-3a) — casas con ``especie_preferente = NULL`` cuentan todas.
- D-GC-04: ``AssignmentDecision`` con ``Literal["admit", "block",
  "admit_with_warning"]`` + ``reason`` + ``warnings``.
- D-GC-05: gate como módulo separado; ``acogidas.create_acogida`` no
  se modifica.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from app.core.insforge import InsForgeClient
from app.core.logging import log_safe
from app.modules.animals import service as animals_service
from app.modules.foster import service as foster_service

# --- dataclasses -----------------------------------------------------------


AssignmentOutcome = Literal["admit", "block", "admit_with_warning"]


@dataclass(frozen=True, slots=True)
class AssignmentDecision:
    """Resultado de evaluar la asignación de un animal a una casa.

    Tres outcomes ortogonales:

    - ``"admit"``: el animal y la casa pasan ambos checks. ``warnings``
      es tupla vacía. El handler redirige al create de la estancia.
    - ``"block"``: la casa rechaza al animal por especie. ``reason``
      trae el texto en castellano claro para mostrar al operador.
      ``warnings`` es tupla vacía. El handler retorna 422.
    - ``"admit_with_warning"``: la asignación procede pero con
      advertencia (capacidad excedida). ``warnings`` trae la lista
      de mensajes a renderizar. El handler pide ``motivo`` obligatorio
      antes de redirigir al create.
    """

    decision: AssignmentOutcome
    reason: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FosterCapacityOverride:
    """Una fila del audit log ``foster_capacity_overrides``.

    Inmutable; el service graba una fila por override aplicada. El
    ``motivo`` es texto libre validado non-empty en
    :func:`record_override`. El ``operador_user_id`` viene de la
    sesion (no de un form field); ver D-GC-02.

    Issue #142: ``estancia_id`` enlaza el override con la estancia
    (``acogidas.id``) que justificó el override; ``None`` mientras el
    operador no completa el create de la estancia o si el link falla.
    """

    id: str
    casa_acogida_id: str
    animal_id: str
    operador_user_id: str
    motivo: str
    created_at: str
    estancia_id: str | None = None


# --- SQL constants ---------------------------------------------------------


# Single query that folds (1) the active count of the preferred species
# + (2) the casa lookup via subquery. We could split into two queries
# (one for casa, one for count) but folding keeps the wire round-trips
# low and lets us do both checks in one statement. The subquery
# ``(SELECT especie_preferente FROM casas_acogida WHERE id = $1)``
# appears twice to keep the logic explicit; PostgreSQL's planner
# collapses it into a single lookup.
#
# D-GC-03: el ``OR especie_preferente IS NULL`` cubre el patron
# conservador de FOSTER-01 — casa "cualquier especie" cuenta TODAS las
# estancias activas, sin filtrar por especie del animal.
#
# JOIN a ``animales`` necesario para conocer la especie del animal
# asignado (la ``acogidas`` solo guarda ``animal_id``, no la especie
# denormalizada). Sin JOIN no podriamos aplicar el filtro de especie.
_ACTIVE_COUNT_PREFERRED_SQL: Final[str] = """
SELECT COUNT(*) AS active_count
FROM acogidas a
JOIN animales ani ON ani.id = a.animal_id
WHERE a.casa_acogida_id = $1
  AND a.fecha_final IS NULL
  AND a.activo = true
  AND (
    ani.Especie = (
      SELECT especie_preferente FROM casas_acogida WHERE id = $1
    )
    OR (SELECT especie_preferente FROM casas_acogida WHERE id = $1) IS NULL
  )
"""


_INSERT_OVERRIDE_SQL: Final[str] = """
INSERT INTO foster_capacity_overrides
    (casa_acogida_id, animal_id, operador_user_id, motivo)
VALUES ($1, $2, $3, $4)
RETURNING id, casa_acogida_id, animal_id, operador_user_id, motivo,
          created_at, estancia_id
"""


_LIST_OVERRIDES_FOR_CASA_SQL: Final[str] = """
SELECT id, casa_acogida_id, animal_id, operador_user_id, motivo, created_at,
       estancia_id
FROM foster_capacity_overrides
WHERE casa_acogida_id = $1
ORDER BY created_at DESC
"""


# --- helpers ---------------------------------------------------------------


def _row_to_override(row: dict[str, Any]) -> FosterCapacityOverride:
    return FosterCapacityOverride(
        id=str(row["id"]),
        casa_acogida_id=str(row["casa_acogida_id"]),
        animal_id=str(row["animal_id"]),
        operador_user_id=str(row["operador_user_id"]),
        motivo=str(row["motivo"]),
        created_at=str(row["created_at"]) if row.get("created_at") else "",
        estancia_id=str(row["estancia_id"]) if row.get("estancia_id") else None,
    )


# --- public API ------------------------------------------------------------


def evaluate_assignment(
    client: InsForgeClient, animal_id: str, casa_id: str
) -> AssignmentDecision:
    """Evalúa si ``animal_id`` puede ser asignado a ``casa_id``.

    Pasos (D-GC-01/02/03/04/05):

    1. Carga el animal via :func:`animals_service.get_animal_by_id`.
       Si no existe o está inactivo, raise ``ValueError`` con mensaje
       claro. La verificación se hace ANTES del load de la casa para
       que el error message apunte al animal cuando aplique.
    2. Carga la casa via :func:`foster_service.get_casa_acogida_by_id`.
       Si no existe o está inactiva, raise ``ValueError``.
    3. **Gate de especie (hard block):** si la casa tiene
       ``especie_preferente`` explícita y no coincide con la del
       animal, retorna ``decision = "block"`` con ``reason`` claro.
       Sin override (D-GC-01).
    4. **Capacity check (advisory):** cuenta las estancias activas de
       la especie preferida (D-GC-03). Si ``count >= capacidad``,
       retorna ``decision = "admit_with_warning"`` con un warning
       "capacidad excedida: N/M".
    5. Si pasa todo, retorna ``decision = "admit"``.

    Raises:
        ValueError: si el animal no existe, está inactivo, la casa no
            existe, o la casa está inactiva (dada de baja).
    """
    # Paso 1 — cargar el animal (raise si no existe o inactivo).
    animal = animals_service.get_animal_by_id(client, animal_id)
    if animal is None or not animal.activo:
        raise ValueError("el animal no existe o no está activo")

    # Paso 2 — cargar la casa (raise si no existe o inactiva).
    casa = foster_service.get_casa_acogida_by_id(client, casa_id)
    if casa is None:
        raise ValueError("la casa no existe")
    if not casa.activo:
        raise ValueError("la casa está dada de baja")

    # Paso 3 — gate de especie (hard block).
    if (
        casa.especie_preferente is not None
        and animal.Especie.value != casa.especie_preferente
    ):
        return AssignmentDecision(
            decision="block",
            reason=(
                f"la casa solo admite {casa.especie_preferente}, "
                f"no {animal.Especie.value}"
            ),
            warnings=(),
        )

    # Paso 4 — capacity check (advisory).
    rows = client.execute_sql(_ACTIVE_COUNT_PREFERRED_SQL, [casa_id])
    active_count = int(rows[0]["active_count"]) if rows else 0
    if active_count >= casa.capacidad:
        return AssignmentDecision(
            decision="admit_with_warning",
            reason=None,
            warnings=(f"capacidad excedida: {active_count}/{casa.capacidad}",),
        )

    # Paso 5 — verde.
    return AssignmentDecision(decision="admit", reason=None, warnings=())


def record_override(
    client: InsForgeClient,
    casa_id: str,
    animal_id: str,
    operador_user_id: str,
    motivo: str,
) -> str:
    """Graba un override de capacidad en ``foster_capacity_overrides``.

    Validación (REQ-GC-6): ``motivo`` debe ser non-empty tras
    ``.strip()``. Si es vacío o solo whitespace, raise
    ``ValueError`` y NO se ejecuta el INSERT (defensa: el test
    ``record_override_no_sql_when_motivo_invalido`` verifica que
    ``captured`` queda vacío).

    El ``operador_user_id`` viene de la sesion (D-GC-02) — el
    handler lo extrae via ``read_session_payload`` y nunca acepta
    input del form en ese campo.

    Issue #142: retorna el UUID del override como ``str`` (NO el
    dataclass ``FosterCapacityOverride``) para que el route handler
    pueda encadenarlo directo en la URL de redirect
    (``/acogidas/new?...&override_id=<uuid>``) sin tener que hacer
    ``.id``. ``_row_to_override`` sigue disponible para los callers
    que necesitan la fila completa (``list_overrides_for_casa`` lo
    usa internamente para mapear el dataclass desde ``SELECT``).

    Tras el INSERT, emite ``log_safe("foster.capacity_override.recorded",
    casa_acogida_id=..., animal_id=..., operador=...)``. El ``motivo``
    NO se loguea: es texto libre del operador y puede llevar PII
    (D-GC-12 / REQ-GC-12).

    Raises:
        ValueError: si ``motivo`` es vacío o solo whitespace.

    Returns:
        El UUID del row insertado (``str``).
    """
    motivo_clean = (motivo or "").strip()
    if not motivo_clean:
        raise ValueError("motivo es obligatorio y no puede estar vacio")

    rows = client.execute_sql(
        _INSERT_OVERRIDE_SQL,
        [casa_id, animal_id, operador_user_id, motivo_clean],
    )
    override_id = str(rows[0]["id"])
    log_safe(
        "foster.capacity_override.recorded",
        casa_acogida_id=casa_id,
        animal_id=animal_id,
        operador=operador_user_id,
    )
    return override_id


def list_overrides_for_casa(
    client: InsForgeClient, casa_id: str
) -> list[FosterCapacityOverride]:
    """Lista overrides aplicadas a una casa, ordenadas ``created_at DESC``.

    Si la casa no tiene overrides, devuelve ``[]``. La query es un
    SELECT simple por FK; el orden descendente es por
    ``created_at`` (más reciente primero) — el patrón del detail y
    el overrides.html.
    """
    rows = client.execute_sql(_LIST_OVERRIDES_FOR_CASA_SQL, [casa_id])
    return [_row_to_override(row) for row in rows]


# --- detail helpers --------------------------------------------------------


_ACTIVE_ESTANCIAS_FOR_CASA_SQL: Final[str] = """
SELECT COUNT(*) AS active_count
FROM acogidas
WHERE casa_acogida_id = $1
  AND fecha_final IS NULL
  AND activo = true
"""


def count_active_estancias_for_casa(
    client: InsForgeClient, casa_id: str
) -> int:
    """Return the count of active stays for ``casa_id``.

    Counts ALL active stays of every species (not just preferred) —
    the operator-visible number is the literal "how many animals are
    staying at this house right now", independent of the capacity
    gate's preferred-species filter. The capacity gate uses a
    different filter (JOIN animales + especie match) to compute its
    own advisory count; this helper is for display only.

    The lookup is a SELECT simple contra la FK ``casa_acogida_id``
    con ``activo = true AND fecha_final IS NULL``. Las estancias
    soft-deleted o cerradas no cuentan.
    """
    rows = client.execute_sql(_ACTIVE_ESTANCIAS_FOR_CASA_SQL, [casa_id])
    return int(rows[0]["active_count"]) if rows else 0
