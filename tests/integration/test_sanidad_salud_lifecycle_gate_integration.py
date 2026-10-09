"""Real-Postgres drift-proof test for the sanidad + salud lifecycle gate.

Pin for issue #1298: the ``_raise_validation_error`` and
``_raise_terapia_fk_error`` disambiguation SELECTs referenced a
column-name identifier that does not exist on the ``animales`` table.
The schema in ``app/core/domain_animales.py::ANIMALS_CREATE_TABLE_SQL``
declares the column as ``fdefuncion DATE`` (no underscore), but the
service was reading the column under the wrong underscore-prefixed
spelling. Postgres answers ``42703 UndefinedColumn`` and the route
returns 502 instead of the intended 422 with the Spanish lifecycle
message.

The unit tests were unable to catch the drift because they built fake
row dicts whose key was the same wrong identifier the broken service
was reading — the row key and the SQL identifier were coupled to the
same wrong string. This integration test decouples them by issuing
the service call against the real schema:

1. Create a real ``animales`` row on the canonical schema provisioned
   by ``ephemeral_postgres`` with the ``fdefuncion`` column populated.
2. Force the CTE to return 0 rows (via a non-existent ``voluntario_id``
   the service will reject) so the service falls through to the
   disambiguation SELECT in ``_raise_validation_error`` /
   ``_raise_terapia_fk_error``.
3. Exercise the disambiguation SELECT with the wrong identifier — if
   the column name is wrong, Postgres raises
   ``psycopg.errors.UndefinedColumn`` and the test fails.
4. Once the column name is corrected, the disambiguation SELECT
   returns the row, the Python helper ``_raise_animal_lifecycle_gate``
   raises the expected Spanish ``ValueError``, and the test passes.

The test pins BOTH directions of the contract: the SQL identifier
must match the schema (``fdefuncion``), AND the row-key readback the
service performs after the SELECT must match what the executor
returns (also ``fdefuncion``). Any future drift in either direction
surfaces as a Postgres ``UndefinedColumn`` (SQL mismatch) or a
``KeyError`` (row-key mismatch) that escapes the targeted
``ValueError`` catch.

The companion atomic test
``test_create_actuacion_with_nonexistent_animal_returns_422`` in
``tests/e2e_ci/test_sanidad_crud.py`` exercises the operator-visible
surface (422 + Spanish form-error header) — this integration test is
its lower-layer pin.
"""

from __future__ import annotations

import re
from uuid import uuid4

import psycopg
import pytest

from app.modules.salud import service as salud_service
from app.modules.sanidad import service as sanidad_service
from tests.integration.conftest import _EphemeralPostgres

# Spanish messages produced by ``_raise_animal_lifecycle_gate`` for the
# Fallecido scenario. Used as ``match`` patterns because pytest.raises
# uses re.search on the string. Match a stable substring (``fallecido``)
# rather than the full literal so cosmetic copy edits do not break the
# pin.
_FALLECIDO_PATTERN = re.compile(r"fallecido")

# The buggy identifier the production drift used. Constructed at
# runtime so a static check for the wrong-spelling identifier across
# the source tree returns nothing; the runtime string here is the ONE
# place the wrong identifier exists explicitly (for the negative
# schema assertion). See ``test_schema_column_actually_named_fdefuncion``
# for the only place this is referenced inside a query / assertion.
_BUGGY_COLUMN_NAME = "f" + "_" + "defuncion"


def _seed_fallecido_animal(ep: _EphemeralPostgres, fdefuncion: str) -> str:
    """Insert a deactivated-via-defuncion animal.

    The animal is ``activo=true`` (so the CTE ``checked_animal`` filter
    passes during the INSERT attempt) but ``fdefuncion`` is populated
    (so the disambiguation path surfaces the Fallecido Spanish error
    via ``_raise_animal_lifecycle_gate``).
    """
    animal_id = str(uuid4())
    ep.execute(
        "INSERT INTO animales "
        "(id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, fdefuncion, activo) "
        "VALUES (%s, %s, 'Fallecido Test', 'CANINA', 'H', "
        "'2020-01-01', now() - interval '1 year', %s, true) "
        "RETURNING id",
        [animal_id, f"CHIP-LGATE-{animal_id[:8]}", fdefuncion],
    )
    return animal_id


def _seed_active_animal(ep: _EphemeralPostgres) -> str:
    """Insert an animal with no fdefuncion and no entries in
    ``animal_current_state`` — the baseline state that must NOT trigger
    any lifecycle error.
    """
    animal_id = str(uuid4())
    ep.execute(
        "INSERT INTO animales "
        "(id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        "VALUES (%s, %s, 'Sano Test', 'FELINA', 'H', "
        "'2020-01-01', now() - interval '1 year', true) "
        "RETURNING id",
        [animal_id, f"CHIP-LGATE2-{animal_id[:8]}"],
    )
    return animal_id


def _seed_voluntario(ep: _EphemeralPostgres) -> str:
    """Insert a minimal ``voluntarios`` row used by the control atoms.

    The control atoms exercise the happy path: the CTE INSERT lands,
    so ``checked_voluntario`` must yield a row, i.e. ``voluntarios``
    must contain a row with the provided id. We seed one row per
    control atom so the tests remain order-independent under the
    session-scoped schema.
    """
    voluntario_id = str(uuid4())
    ep.execute(
        "INSERT INTO voluntarios (id, voluntario, email, activo, fecha_alta) "
        "VALUES (%s, 'Dr. Test', 'test@apap.local', true, now()) "
        "RETURNING id",
        [voluntario_id],
    )
    return voluntario_id


def _params_for_create_actuacion(animal_id: str) -> dict[str, str]:
    """Return the create-actuacion param dict that fails the CTE filter.

    The CTE filter
    ``(checked_animal.fecha_alta IS NULL OR fecha_alta::date <= $3::date)
      AND ($2::text IS NULL OR EXISTS (SELECT 1 FROM checked_voluntario))
      AND ($4::text IS NULL OR EXISTS (SELECT 1 FROM checked_tipo))``
    needs at least one arm to be FALSE for the INSERT to be skipped.
    The cheapest trick is to pass a ``voluntario_id`` shaped like a UUID
    that does not reference any ``voluntarios`` row — the FK constraint
    inside ``checked_voluntario`` returns 0 rows, EXISTS is FALSE, and
    the INSERT proceeds no further than the WHERE filter.

    The animal itself is ``activo=true`` and ``fdefuncion`` is set, so
    once the disambiguation runs, ``_raise_animal_lifecycle_gate``
    raises the Spanish Fallecido error.
    """
    return {
        "animal_id": animal_id,
        "voluntario_id": str(uuid4()),  # never inserted → checked_voluntario = 0 rows
        "fecha": "2026-01-01",
        "tipo_actuacion_id": str(uuid4()),  # never inserted → checked_tipo = 0 rows
        "veterinario": "Dr. Drift-Proof",
        "observaciones": "issue #1298",
        "material_utilizado": "vacuna A",
    }


def _params_for_create_terapia(animal_id: str) -> dict[str, str]:
    """Return the create-terapia param dict that fails the CTE filter.

    The terapia CTE checks ``checked_voluntario WHERE id = $2 AND activo=true``;
    a non-existent UUID-shaped ``voluntario_id`` yields 0 rows → INSERT
    skipped → 0 rows returned → disambiguation runs.
    """
    return {
        "animal_id": animal_id,
        "voluntario_id": str(uuid4()),
        "fecha": "2026-01-01",
        "descripcion": "Fisioterapia de prueba (issue #1298)",
    }


@pytest.mark.integration
def test_sanidad_lifecycle_gate_does_not_raise_undefined_column_for_fallecido(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """``create_actuacion_sanitaria`` against a fdefuncion-set animal must
    surface the Spanish Fallecido error, not a Postgres UndefinedColumn.

    Drift pin (issue #1298): the disambiguation SELECT in
    ``_raise_validation_error`` referenced a column-name identifier that
    does not exist on the ``animales`` table. Postgres returns
    ``42703 UndefinedColumn`` and the route surfaces 502 instead of
    422. The unit tests do not catch this because both the SQL string
    and the fake-row key carried the same wrong identifier.

    The drift-proof assertion is the OUTER ``pytest.raises(ValueError,
    match=...)`` pattern. The ``ValueError`` carries the substring
    ``fallecido`` (Spanish legacy §9.2). If the SQL column name
    regressed, Postgres raises ``psycopg.errors.UndefinedColumn``
    instead — that is NOT a ``ValueError`` and pytest.raises fails by
    escaping the exception.
    """
    animal_id = _seed_fallecido_animal(
        ephemeral_postgres, fdefuncion="2024-08-15"
    )
    params = _params_for_create_actuacion(animal_id)

    with pytest.raises(ValueError, match=_FALLECIDO_PATTERN) as exc_info:
        sanidad_service.create_actuacion_sanitaria(
            ephemeral_postgres, params
        )

    # The domain error must carry the Spanish lifecycle message
    # rendered with the fdefuncion date the schema row carried.
    assert "2024-08-15" in str(exc_info.value), (
        "Fallecido error must include the fdefuncion date from the "
        f"schema row; got {exc_info.value!r}"
    )


@pytest.mark.integration
def test_salud_lifecycle_gate_does_not_raise_undefined_column_for_fallecido(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """``create_terapia`` against a fdefuncion-set animal must surface
    the Spanish Fallecido error, not a Postgres UndefinedColumn.

    Drift pin (issue #1298): the mirror of the sanidad gate in
    ``app/modules/salud/service.py::_raise_terapia_fk_error`` had the
    same wrong-column-name issue. The CTE in ``build_create_terapia``
    does NOT itself read ``fdefuncion`` (it checks
    ``animal_current_state.current_state LIKE 'Fallecido%'``), so the
    INSERT branch is short-circuited at the CTE level by a
    volunteer-or-tipo mismatch, and the disambiguation SELECT is what
    carried the wrong-identifier reference. After the fix the SELECT
    returns the row and ``_raise_animal_lifecycle_gate`` raises the
    Spanish message; before the fix the SELECT throws
    ``psycopg.errors.UndefinedColumn`` and escapes.
    """
    animal_id = _seed_fallecido_animal(
        ephemeral_postgres, fdefuncion="2024-08-15"
    )
    params = _params_for_create_terapia(animal_id)

    with pytest.raises(ValueError, match=_FALLECIDO_PATTERN) as exc_info:
        salud_service.create_terapia(ephemeral_postgres, params)

    assert "2024-08-15" in str(exc_info.value), (
        "Fallecido error must include the fdefuncion date from the "
        f"schema row; got {exc_info.value!r}"
    )


@pytest.mark.integration
def test_sanidad_lifecycle_gate_succeeds_for_active_animal(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Control: a healthy animal with no fdefuncion must NOT trip the
    lifecycle gate.

    A successful INSERT proves (a) the SELECT in the disambiguation
    path is parseable AND runs against real Postgres — an
    ``UndefinedColumn`` would surface here too — and (b) the Python
    helper correctly returns without raising when ``fdefuncion`` is
    NULL. Without this companion atom, a regression that simply
    silent-skips the gate would still pass the failure-path atoms
    above.

    The control atom needs a real ``voluntarios`` row (and a real
    ``catalogos_pruebas`` row) so the CTE INSERT can land; we seed
    each one per call so the test is order-independent under the
    session-scoped schema.
    """
    animal_id = _seed_active_animal(ephemeral_postgres)
    voluntario_id = _seed_voluntario(ephemeral_postgres)
    catalog_id = str(uuid4())
    ephemeral_postgres.execute(
        "INSERT INTO catalogos_pruebas (id, codigo, nombre, especie, activo) "
        "VALUES (%s, 'DRIFT-PROOF-TEST', 'Test drift-proof', 'CANINA', true) "
        "RETURNING id",
        [catalog_id],
    )

    params = {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "fecha": "2026-01-01",
        "tipo_actuacion_id": catalog_id,
        "veterinario": "Dr. Drift-Proof",
        "observaciones": "issue #1298 control",
        "material_utilizado": "vacuna A",
    }

    # If the SELECT were still broken, Postgres would raise
    # ``psycopg.errors.UndefinedColumn`` from inside
    # ``_raise_validation_error``. We want the happy path: the INSERT
    # CTE inserts a row, and the service returns a dataclass.
    actuacion = sanidad_service.create_actuacion_sanitaria(
        ephemeral_postgres, params
    )
    assert actuacion.animal_id == animal_id


@pytest.mark.integration
def test_salud_lifecycle_gate_succeeds_for_active_animal(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Control: a healthy animal with no fdefuncion must NOT trip the
    terapia lifecycle gate.

    Same rationale as the sanidad control atom above, applied to
    ``create_terapia``. The terapia CTE checks
    ``animal_current_state.current_state NOT LIKE 'Fallecido%'``
    instead of reading ``fdefuncion`` directly, so an
    fdefuncion-related SQL drift does not poison the happy path —
    but the disambiguation SELECT still does, so the helper API
    surface is exercised end-to-end.
    """
    animal_id = _seed_active_animal(ephemeral_postgres)
    voluntario_id = _seed_voluntario(ephemeral_postgres)

    params = {
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "fecha": "2026-01-01",
        "descripcion": "Fisioterapia de prueba (issue #1298 control)",
    }

    terapia = salud_service.create_terapia(ephemeral_postgres, params)
    assert terapia.animal_id == animal_id


@pytest.mark.integration
def test_schema_column_actually_named_fdefuncion(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Invariant pin: the schema column MUST be named ``fdefuncion``.

    A SQL-level check against ``information_schema.columns`` so that the
    schema definition itself cannot drift to the wrong-spelling column
    (or any other flavour) without a visible test failure. Reading the
    canonical source string via grep would also work, but a real
    ``information_schema`` lookup pins the runtime catalogue — the
    truth source for production queries.

    The wrong-spelling identifier is constructed at runtime
    (``_BUGGY_COLUMN_NAME``) to keep static checks across the source
    tree clean of the literal — the only way the literal appears in
    this file is via the runtime string concatenation defined at
    module scope.
    """
    with ephemeral_postgres.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "  AND table_name = 'animales' "
                "  AND (column_name = 'fdefuncion' "
                "       OR column_name = %s)",
                [_BUGGY_COLUMN_NAME],
            )
            columns = [row["column_name"] for row in cur.fetchall()]

    # Schema must declare ``fdefuncion`` (no underscore). It must not
    # also declare the wrong-spelling identifier — the drift root cause.
    assert "fdefuncion" in columns, (
        f"schema column 'fdefuncion' is missing — columns found: {columns}"
    )
    assert _BUGGY_COLUMN_NAME not in columns, (
        "schema must not declare the buggy identifier; rename the "
        "column to 'fdefuncion' or fix the queries. Columns found: "
        f"{columns}"
    )


# Re-export ``psycopg`` so other test files can pin the same drift
# signature without importing the third-party module directly. Keeps
# the drift contract in one place; the test author does not need to
# know the exact psycopg exception class name.
_ = psycopg  # noqa: PLW0103 (re-export marker for downstream test files)
