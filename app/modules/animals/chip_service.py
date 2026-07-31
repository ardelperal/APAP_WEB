"""Chip cascade saga for animals (issue #29, LIFECYCLE-04).

Extracted from ``animals/service.py`` to keep that module under the 700-line
budget (AGENTS.md rule 21).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.data_access import SqlExecutor


# --- Result type -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChangeChipResult:
    """Resultado del saga de cambio de chip.

    ``success=True``: todos los registros se actualizaron atomicamente.
    ``success=False``: la operacion se revirtio; ``error`` contiene la causa.
    """

    success: bool
    old_chip: str
    new_chip: str
    updated_tables: dict[str, int]
    error: str | None = None


# --- public saga ----------------------------------------------------------


def change_animal_chip(
    client: SqlExecutor,
    *,
    animal_id: str,
    old_chip: str,
    new_chip: str,
    reason: str,
    operador_user_id: str,
) -> ChangeChipResult:
    """Saga: cambiar el chip de un animal en cascada a 6 tablas.

    Tablas: ``animals`` (NCHIP), ``entradas``, ``acogidas``,
    ``adopciones``, ``actuaciones_sanitarias``, ``terapias``.

    Validaciones pre-transaccion:
    - ``new_chip`` no puede estar vacio ni ser igual a ``old_chip``.
    - ``reason`` no puede estar vacio.
    - ``new_chip`` no puede estar asignado a otro animal.
    - ``old_chip`` debe coincidir con el chip actual del animal.

    Si cualquier tabla falla dentro de la transaccion, se ejecuta
    ROLLBACK y se devuelve ``ChangeChipResult(success=False)``.

    Returns: :class:`ChangeChipResult`
    """
    # --- pre-flight validations -----------------------------------------
    new_chip_val = new_chip.strip()
    if not new_chip_val:
        raise ValueError("new_chip es obligatorio y no puede estar vacio")
    if new_chip_val == old_chip:
        raise ValueError("new_chip no puede ser igual a old_chip")
    reason_val = reason.strip()
    if not reason_val:
        raise ValueError("reason es obligatorio y no puede estar vacio")

    # 1. Uniqueness: new_chip no esta asignado a otro animal?
    uniq_rows = client.execute_sql(
        _CHECK_CHIP_UNIQUENESS_SQL, [new_chip_val, animal_id]
    )
    if uniq_rows:
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables={},
            error=f"El chip {new_chip_val!r} ya esta asignado a otro animal (id={uniq_rows[0]['id']})",
        )

    # 2. old_chip coincide con el chip actual del animal?
    current_rows = client.execute_sql(_GET_CURRENT_CHIP_SQL, [animal_id])
    if not current_rows:
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables={},
            error=f"Animal {animal_id!r} no encontrado",
        )
    actual_chip = str(current_rows[0].get("NCHIP", ""))
    if actual_chip != old_chip:
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables={},
            error=f"El chip actual del animal ({actual_chip!r}) no coincide con old_chip ({old_chip!r})",
        )

    # --- saga: BEGIN transaction ----------------------------------------
    _begin_tx(client)

    updated: dict[str, int] = {}

    try:
        # animals
        rows_ani = client.execute_sql(
            _UPDATE_ANIMALS_CHIP_SQL, [new_chip_val, animal_id, old_chip]
        )
        updated["animals"] = len(rows_ani)

        # entradas
        rows_ent = client.execute_sql(
            _UPDATE_ENTRADAS_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["entradas"] = len(rows_ent)

        # acogidas
        rows_aco = client.execute_sql(
            _UPDATE_ACOGIDAS_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["acogidas"] = len(rows_aco)

        # adopciones
        rows_ado = client.execute_sql(
            _UPDATE_ADOPCIONES_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["adopciones"] = len(rows_ado)

        # actuaciones_sanitarias
        rows_act = client.execute_sql(
            _UPDATE_ACTUACIONES_SANITARIAS_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["actuaciones_sanitarias"] = len(rows_act)

        # terapias
        rows_ter = client.execute_sql(
            _UPDATE_TERAPIAS_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["terapias"] = len(rows_ter)

        # lifecycle event
        metadata_json = json.dumps(
            {"old_chip": old_chip, "new_chip": new_chip_val, "reason": reason_val}
        )
        client.execute_sql(
            _INSERT_LIFECYCLE_EVENT_SQL,
            [animal_id, "CHIP_CHANGED", metadata_json, operador_user_id],
        )

        _commit_tx(client)

        return ChangeChipResult(
            success=True,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables=updated,
        )

    except Exception as exc:  # noqa: BLE001
        _rollback_tx(client)
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables=updated,
            error=f"Error en la transaccion: {exc}",
        )


# --- chip change SQL constants (issue #29, LIFECYCLE-04) -------------------

_CHECK_CHIP_UNIQUENESS_SQL = """
SELECT id FROM animals WHERE NCHIP = $1 AND id != $2 LIMIT 1
"""

_GET_CURRENT_CHIP_SQL = """
SELECT NCHIP FROM animals WHERE id = $1
"""

_UPDATE_ANIMALS_CHIP_SQL = """
UPDATE animals SET NCHIP = $1, updated_at = now()
WHERE id = $2 AND NCHIP = $3
RETURNING id
"""

_UPDATE_ENTRADAS_CHIP_SQL = """
UPDATE entradas SET chip = $1, updated_at = now()
WHERE chip = $2 AND activo = true
RETURNING id
"""

_UPDATE_ACOGIDAS_CHIP_SQL = """
UPDATE acogidas SET chip = $1, updated_at = now()
WHERE chip = $2 AND activo = true
RETURNING id
"""

_UPDATE_ADOPCIONES_CHIP_SQL = """
UPDATE adopciones SET chip = $1, updated_at = now()
WHERE chip = $2 AND activo = true
RETURNING id
"""

_UPDATE_ACTUACIONES_SANITARIAS_CHIP_SQL = """
UPDATE actuaciones_sanitarias SET chip = $1, updated_at = now()
WHERE chip = $2
RETURNING id
"""

_UPDATE_TERAPIAS_CHIP_SQL = """
UPDATE terapias SET chip = $1, updated_at = now()
WHERE chip = $2
RETURNING id
"""

_INSERT_LIFECYCLE_EVENT_SQL = """
INSERT INTO animal_lifecycle_events (
    animal_id,
    event_type,
    event_timestamp,
    metadata,
    created_by
) VALUES ($1, $2, now(), $3, $4)
ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING
"""


# --- private helpers (inline SQL for tx control) --------------------------


def _begin_tx(client: SqlExecutor) -> None:
    client.execute_sql("BEGIN", [])


def _commit_tx(client: SqlExecutor) -> None:
    client.execute_sql("COMMIT", [])


def _rollback_tx(client: SqlExecutor) -> None:
    client.execute_sql("ROLLBACK", [])
