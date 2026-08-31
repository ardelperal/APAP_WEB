"""Integration tests for ``app.modules.cesiones.queries``.

Validates the natural UNIQUE constraint on ``cesiones_propietario.entrada_id``
against the real Postgres fixture. The unit-test suite
(``tests/test_cesiones.py``) verifies the wire-shape of the SQL via
``httpx.MockTransport`` and the ``InsForgeError`` → ``CesionConflictError``
mapping via a staged handler. The integration atom closes the audit
P0 gap documented in ``docs/quality/test-audit.md`` §Critical-gaps
point 4 by asserting that the constraint itself fires against the real
database engine, not a mock.

Issue #633.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from app.modules.cesiones import service
from tests.integration.conftest import _EphemeralPostgres

# Import the SQL constants directly. They are private by convention
# (leading underscore) but the surrounding functions are not; pinning
# these strings here keeps the test faithful to whatever the production
# service emits today.
_INSERT_CESION_SQL = service._INSERT_CESION_SQL


def _seed_animal(ep: _EphemeralPostgres, nchip: str) -> str:
    """INSERT a minimal animales row and return its UUID."""
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        f"VALUES ('{animal_id}', '{nchip}', 'Test Animal', 'CANINA', 'H', '2020-01-01', now(), true) "
        f"RETURNING id"
    )
    return animal_id


def _seed_entrada(ep: _EphemeralPostgres, animal_id: str) -> str:
    """INSERT a minimal entradas row and return its UUID."""
    entrada_id = str(uuid4())
    ep.execute(
        f"INSERT INTO entradas (id, animal_id, fecha_entrada, motivo, observaciones, fecha_alta, activo) "
        f"VALUES ('{entrada_id}', '{animal_id}', '2026-06-01', 'Ingreso', 'Test', now(), true) "
        f"RETURNING id"
    )
    return entrada_id


def _cesion_params(entrada_id: str, **overrides: str) -> dict[str, str]:
    """Build a minimal valid create_cesion params dict.

    The 20-column INSERT in ``_INSERT_CESION_SQL`` requires every
    NOT-NULL column to have a value. Optionals are left as None.
    """
    base = {
        "entrada_id": entrada_id,
        "numero_contrato": f"CP{uuid4().hex[:8]}",
        "nombre_representante": "Representante Test",
    }
    base.update(overrides)
    return base


def _build_cesion_insert_params_kwargs(entrada_id: str) -> list[str | None]:
    """Return the positional params for ``_INSERT_CESION_SQL``.

    The 20-column INSERT in production code lives behind
    ``_build_cesion_insert_params`` (also module-private). Mirror its
    positional layout here so we exercise the real SQL without
    importing the whole use-case surface. Each value is the column's
    NOT-NULL or sentinel value.
    """
    # The order matches _INSERT_CESION_COLUMNS in service.py.
    return [
        entrada_id,                       # entrada_id
        f"CP{uuid4().hex[:8]}",           # numero_contrato
        "Representante Test",             # nombre_representante
        None,                             # cartilla_sanitaria
        None,                             # certificado_veterinario
        None,                             # autorizacion_recogida
        None,                             # fecha_vacuna_rabia
        None,                             # numero_colegiado
        None,                             # numero_colaborador
        None,                             # dni_representante
        None,                             # calle_representante
        None,                             # numero_calle_representante
        None,                             # piso_representante
        None,                             # letra_representante
        None,                             # localidad_representante
        None,                             # provincia_representante
        None,                             # cp_representante
        None,                             # telefono_representante
        None,                             # email_representante
        None,                             # hora_cesion
    ]


@pytest.mark.integration
def test_cesion_unique_constraint_fires_on_duplicate_entrada(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Two cesiones for the same entrada must violate the UNIQUE constraint.

    The 1-a-1 relationship between ``entradas`` and ``cesiones_propietario``
    is enforced by ``UNIQUE (entrada_id)`` at the database level. This
    atom pins that constraint against real Postgres: a second INSERT
    with the same entrada_id must raise ``psycopg.errors.UniqueViolation``
    AND leave the first row intact (the operator can read it back).
    """
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep, "CHIP-CES-001")
    entrada_id = _seed_entrada(ep, animal_id)

    # First INSERT lands. The SQL has RETURNING so the row is fetchable.
    first = ep.execute(_INSERT_CESION_SQL, _build_cesion_insert_params_kwargs(entrada_id))
    assert len(first) == 1
    first_id = str(first[0]["id"])

    # Second INSERT with the same entrada_id must violate the UNIQUE
    # constraint. The service maps this to ``CesionConflictError`` via
    # ``_is_unique_conflict``; here we exercise the raw psycopg side.
    with pytest.raises(psycopg.errors.UniqueViolation):
        ep.execute(
            _INSERT_CESION_SQL, _build_cesion_insert_params_kwargs(entrada_id)
        )

    # The first row is still there, untouched. The DB did not silently
    # overwrite or commit half the operation.
    rows_after = ep.execute(
        "SELECT id FROM cesiones_propietario WHERE entrada_id = %s", [entrada_id]
    )
    assert len(rows_after) == 1
    assert str(rows_after[0]["id"]) == first_id


@pytest.mark.integration
def test_cesion_fk_constraint_fires_on_ghost_entrada(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """An INSERT with a non-existent entrada_id must violate the FK.

    Companion to the UNIQUE atom: the FK from ``cesiones_propietario.entrada_id``
    to ``entradas.id`` is the second flavour of constraint that protects
    referential integrity. A pre-existing ``ValueError`` is raised by
    the service's ``_CHECK_ENTRADA_SQL`` pre-validation, but the
    database-level FK is the actual guarantee — the integration atom
    pins that guarantee against real Postgres.
    """
    ep = ephemeral_postgres
    ghost_entrada_id = str(uuid4())

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        ep.execute(
            _INSERT_CESION_SQL,
            _build_cesion_insert_params_kwargs(ghost_entrada_id),
        )

    # No row was inserted.
    rows = ep.execute("SELECT id FROM cesiones_propietario")
    assert rows == []


@pytest.mark.integration
def test_cesion_happy_path_inserts_a_row(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Control atom: with no constraint violated, the INSERT lands and
    is fetchable. The companion to the two failure-path atoms above.

    Pinning the success path means a future CTE or trigger refactor
    that accidentally over-rolls back (e.g. by wrapping a non-required
    field in a CHECK that fails for valid input) would surface here.
    """
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep, "CHIP-CES-002")
    entrada_id = _seed_entrada(ep, animal_id)

    rows = ep.execute(_INSERT_CESION_SQL, _build_cesion_insert_params_kwargs(entrada_id))
    assert len(rows) == 1
    assert str(rows[0]["entrada_id"]) == entrada_id
    assert rows[0]["numero_contrato"] is not None
    assert rows[0]["nombre_representante"] == "Representante Test"
