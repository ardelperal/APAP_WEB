"""Service-layer tests for ADOPT-01 adopciones.

The ``adopciones.service`` module owns:
- create / list / get / update / soft-delete of ``adopciones``
- validation: required fields (animal_id, fecha_adopcion, nombre_adoptante)
- FK checks: animal activo, voluntario_seguimiento_id activo per VOL-05,
  entrada_origen_id exists (optional)
- search by nombre_adoptante (ILIKE case-insensitive with wildcard
  escaping, D-ADOPT-04)
- ``is_active`` derived from fecha_devolucion (D-ADOPT-05)

Mirror of the ``tests/test_entradas.py`` and ``tests/test_foster.py``
patterns: real LocalPostgresExecutor + httpx.MockTransport for SQL shape
assertion.

CRITICAL-1 (review 2026-07-04): create / update run validation + write
in a single CTE statement. The fake here answers those CTE queries
with a single round-trip; on a 0-row CTE the service runs targeted
disambiguation SELECTs which the fake also answers (so the failure
paths are still end-to-end observable).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pytest

from app.core.data_access import BackendError
from app.modules.adopciones import service as adopciones_service


class _ErrorResponse:
    """Marker returned by a fake handler to signal a backend error.

    The ``_FakeSqlExecutor`` translates this into a ``BackendError``
    raise, mirroring what the InsForge adapter used to do for a
    non-2xx HTTP response.
    """

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for unit tests.

    Supports two response strategies:

    * ``set_response`` / ``set_responses`` — queue rows consumed in order
      (used by tests that want straight-line behaviour).
    * ``set_handler`` — a per-call callable that inspects the SQL +
      params and returns rows OR an ``_ErrorResponse`` (used by CTE +
      disambiguation tests where the response depends on which CTE
      was hit).

    Returns ``[]`` when neither strategy matches so the fake never
    accidentally short-circuits a "row missing" branch.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self._responses: list[list[dict[str, object]]] = []
        self._handler: Callable[[str, list[object]], Any] | None = None

    def set_response(self, rows: list[dict[str, object]]) -> None:
        self._responses = [rows]

    def set_responses(self, *responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)

    def set_handler(
        self, handler: Callable[[str, list[object]], Any]
    ) -> None:
        self._handler = handler

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        bound_params = list(params or [])
        if self._handler is not None:
            result = self._handler(query, bound_params)
            if isinstance(result, _ErrorResponse):
                raise BackendError(result.status_code, result.body)
            if result is not None:
                return result  # type: ignore[no-any-return]
        if self._responses:
            return self._responses.pop(0)
        return []

    def close(self) -> None:
        pass  # no-op for fake


def _params_minimal() -> dict[str, Any]:
    return {
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_seguimiento_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha_adopcion": "2026-07-04",
        "fecha_devolucion": None,
        "donativo_preadopcion": None,
        "donativo_adopcion": None,
        "nombre_adoptante": "María García López",
        "dni_adoptante": "12345678A",
        "telefono_adoptante": "600123456",
        "email_adoptante": "maria@example.com",
        "entrada_origen_id": None,
        "observaciones": "Adopción responsable",
        "tipo_adopcion": "regular",
    }


def _row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_seguimiento_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha_adopcion": "2026-07-04",
        "fecha_devolucion": None,
        "donativo_preadopcion": None,
        "donativo_adopcion": None,
        "nombre_adoptante": "María García López",
        "dni_adoptante": "12345678A",
        "telefono_adoptante": "600123456",
        "email_adoptante": "maria@example.com",
        "entrada_origen_id": None,
        "observaciones": "Adopción responsable",
        "tipo_adopcion": "regular",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


def _validation_handler(
    *,
    animal_exists: bool = True,
    voluntario_exists: bool = True,
    entrada_exists: bool = True,
    insert_row: dict[str, Any] | None = None,
    update_row: dict[str, Any] | None = None,
):
    """Build a handler that answers the CTE-shaped create / update SQL.

    The CTE bundles FK checks + INSERT / UPDATE in one statement, so the
    handler answers ONE round-trip on the happy path. On the failure
    paths (CTE returns 0 rows because an FK check failed), the service
    runs targeted disambiguation SELECTs which the same handler also
    answers, so the failure paths stay end-to-end observable.

    Placeholder layout:
      INSERT CTE  $1..$13 (animal, vol, fecha_adopc, fecha_dev,
                            donativo_pre, donativo_adopc, nombre, dni,
                            tel, email, entrada, observaciones,
                            tipo_adopc)
      UPDATE CTE  $1 id, $2..$14 same as INSERT but shifted by one

    ``fail_on`` is detected from the params at query time: if the
    optional FK was provided (non-None) and the corresponding flag is
    False, the CTE returns 0 rows to simulate the failure.
    """

    def _handler(query: str, params: list[object]) -> Any:
        # CREATE CTE: WITH checked_animal AS ... INSERT INTO adopciones ...
        if (
            "INSERT INTO adopciones" in query
            and "WITH checked_animal" in query
        ):
            if not animal_exists:
                return []
            # voluntario_seguimiento_id is $2; non-empty string means the
            # operator set it.
            if params[1] and not voluntario_exists:
                return []
            # entrada_origen_id is $11; non-empty string means set.
            if params[10] and not entrada_exists:
                return []
            return [insert_row or _row()]

        # UPDATE CTE: WITH checked_animal AS ... UPDATE adopciones SET ...
        if (
            "UPDATE adopciones SET" in query
            and "WITH checked_animal" in query
        ):
            if not animal_exists:
                return []
            if params[2] and not voluntario_exists:
                return []
            if params[11] and not entrada_exists:
                return []
            # If the id is the test sentinel "missing", the UPDATE returns
            # 0 rows (no row matched id="missing"); otherwise return the
            # configured update_row (or the default _row()).
            if params[0] == "missing":
                return []
            return [update_row or _row()]

        # Disambiguation SELECTs (after a 0-row CTE). The service runs
        # these to identify WHICH FK failed for a clean error message.
        if "FROM animales" in query:
            return [{"id": params[0]}] if animal_exists else []
        if "FROM voluntarios" in query:
            return [{"id": params[0]}] if voluntario_exists else []
        if "FROM entradas" in query:
            return [{"id": params[0]}] if entrada_exists else []

        # get_adopcion_by_id (update path's 404 disambiguation)
        if "FROM adopciones" in query and "WHERE id = $1" in query:
            return [update_row or _row()] if params[0] != "missing" else []

        # LIFECYCLE-02 (issue #32): create_adopcion / update_adopcion
        # emit lifecycle events into ``animal_lifecycle_events`` and
        # refresh ``animal_current_state`` via
        # ``actualizar_estado_animal``. Those writes hit:
        #   * ``INSERT INTO animal_lifecycle_events`` (event log)
        #   * the cascade's active-collection SELECTs
        #   * ``INSERT INTO animal_current_state`` (cache UPSERT)
        # Returning empty lists keeps the cascade happy ("no other
        # active placements") without coupling the CRUD tests to the
        # lifecycle SQL shape -- that's pinned by
        # ``tests/test_adopciones_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(query)
        if lifecycle_resp is not None:
            return lifecycle_resp

        raise AssertionError(f"Unexpected SQL: {query!r}")

    return _handler


def _lifecycle_query_response(query: str) -> list[dict[str, object]] | None:
    """Return a 200/[] response for any lifecycle SQL query the cascade issues.

    LIFECYCLE-02 (issue #32) makes ``create_adopcion`` / ``update_adopcion``
    fire extra SQL: ``INSERT INTO animal_lifecycle_events`` (event log),
    the cascade's ficha + active-placements SELECTs, and the
    ``INSERT INTO animal_current_state`` cache UPSERT. Pre-existing
    CRUD tests use custom inline handlers that only know about the
    ``INSERT/UPDATE adopciones`` shape; this helper lets those tests
    accept the new lifecycle SQL without coupling to its exact
    parameter list. The lifecycle SQL shape is pinned by
    ``tests/test_adopciones_lifecycle_events.py``.
    """
    if "INSERT INTO animal_lifecycle_events" in query:
        return []
    if "INSERT INTO animal_current_state" in query:
        return []
    if "LEFT JOIN animal_current_state" in query and "FROM animales" in query:
        # Cascade's ``build_select_ficha`` SELECT — return a minimal
        # ficha row so the cascade's P1/P2/P3 branches don't crash on
        # missing keys. ``fdefuncion`` null keeps the cascade on the
        # non-terminal path.
        return [
            {
                "FDefuncion": None,
                "UltimoEstadoAntesDeFallecido": None,
                "Situacion": "",
            }
        ]
    if (
        "FROM entradas" in query
        and "fecha_salida IS NULL" in query
        and "activo = true" in query
    ):
        return []
    if (
        "FROM acogidas" in query
        and "fecha_final IS NULL" in query
        and "activo = true" in query
    ):
        return []
    if (
        "FROM adopciones" in query
        and "fecha_devolucion IS NULL" in query
        and "activo = true" in query
    ):
        return []
    return None


# --- create: happy path ---------------------------------------------------


def test_create_adopcion_inserts_with_all_columns() -> None:
    """Single CTE round-trip: FK checks + INSERT under one snapshot.

    CRITICAL-1 review 2026-07-04: the old design issued separate
    animales + voluntarios SELECTs and then the INSERT. The CTE design
    folds all three into one statement, so the test now sees exactly
    one captured SQL with the INSERT keywords inside it.
    """
    client, captured = _make_client(_validation_handler())

    result = adopciones_service.create_adopcion(client, _params_minimal())

    assert isinstance(result, adopciones_service.Adopcion)
    assert result.id == "11111111-1111-1111-1111-111111111111"
    assert result.animal_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert result.nombre_adoptante == "María García López"
    assert result.tipo_adopcion == "regular"
    assert result.activo is True
    assert result.is_active is True  # fecha_devolucion is None → vigente

    # LIFECYCLE-02 (issue #32): the service now emits ADOPTION_STARTED,
    # the FOSTER_CLOSED_BY_ADOPTION closing event, and refreshes the
    # animal_current_state cache in the same DB transaction as the
    # INSERT. That fires several extra SQL calls on top of the CTE;
    # we assert the CTE was issued (and its shape) rather than the
    # total call count. The lifecycle SQL shape is pinned by
    # ``tests/test_adopciones_lifecycle_events.py``.
    cte = next(c for c in captured if "INSERT INTO adopciones" in c[0])
    # All three FK-check CTEs share one WITH clause (PostgreSQL syntax
    # only requires WITH before the first one).
    assert "checked_animal" in cte[0]
    assert "checked_voluntario" in cte[0]
    assert "checked_entrada" in cte[0]
    # The first INSERT param is animal_id (per _WRITE_COLUMNS order).
    assert cte[1][0] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    # nombre_adoptante is the 7th param per _WRITE_COLUMNS order.
    assert cte[1][6] == "María García López"
    # tipo_adopcion is the 13th param.
    assert cte[1][12] == "regular"


def test_create_adopcion_with_null_voluntario_skips_voluntario_fk_check() -> None:
    """When ``voluntario_seguimiento_id`` is None, the CTE's vol-check
    is bypassed (``($2::text IS NULL OR EXISTS ...)``).

    The CTE still runs (one round-trip); the INSERT succeeds because the
    optional vol/entry checks short-circuit on NULL.
    """
    params = {**_params_minimal(), "voluntario_seguimiento_id": None}
    client, captured = _make_client(_validation_handler())

    adopciones_service.create_adopcion(client, params)

    # LIFECYCLE-02 (issue #32): the service fires extra lifecycle SQL
    # calls in the same transaction. We assert the CTE was issued
    # rather than the total call count -- the lifecycle SQL shape is
    # pinned by ``tests/test_adopciones_lifecycle_events.py``.
    cte = next(c for c in captured if "INSERT INTO adopciones" in c[0])
    assert "WITH checked_animal" in cte[0]
    assert "checked_voluntario" in cte[0]


def test_create_adopcion_with_donativos_numeric_coerces_to_float() -> None:
    params = {
        **_params_minimal(),
        "donativo_preadopcion": "50.00",
        "donativo_adopcion": "150.50",
    }
    insert_row = _row(
        {"donativo_preadopcion": 50.0, "donativo_adopcion": 150.5}
    )
    client, captured = _make_client(_validation_handler(insert_row=insert_row))

    result = adopciones_service.create_adopcion(client, params)

    assert result.donativo_preadopcion == 50.0
    assert result.donativo_adopcion == 150.5
    # LIFECYCLE-02 (issue #32): the service fires extra lifecycle SQL
    # calls in the same transaction. We assert the CTE was issued
    # (and its param list) rather than the total call count.
    cte = next(c for c in captured if "INSERT INTO adopciones" in c[0])
    # donativo_preadopcion is the 5th param (per _WRITE_COLUMNS order).
    assert cte[1][4] == 50.0
    assert cte[1][5] == 150.5


def test_create_adopcion_default_tipo_adopcion_is_regular() -> None:
    """Omitting ``tipo_adopcion`` defaults to 'regular'."""
    params = {k: v for k, v in _params_minimal().items() if k != "tipo_adopcion"}
    client, captured = _make_client(_validation_handler())

    result = adopciones_service.create_adopcion(client, params)

    assert result.tipo_adopcion == "regular"
    # LIFECYCLE-02 (issue #32): the service fires extra lifecycle SQL
    # calls in the same transaction. We assert the CTE was issued
    # (and its param at index 12) rather than the total call count.
    cte = next(c for c in captured if "INSERT INTO adopciones" in c[0])
    # tipo_adopcion is the 13th param.
    assert cte[1][12] == "regular"


# --- create: required-field validation ------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("animal_id", ""),
        ("animal_id", "   "),
        ("fecha_adopcion", ""),
        ("fecha_adopcion", None),
        ("nombre_adoptante", ""),
        ("nombre_adoptante", "   "),
    ],
)
def test_create_adopcion_rejects_empty_required_field_before_sql(
    field: str, value: Any
) -> None:
    client, captured = _make_client(_validation_handler())

    with pytest.raises(ValueError, match=field):
        adopciones_service.create_adopcion(
            client, {**_params_minimal(), field: value}
        )

    assert captured == []


# --- create: FK validation (VOL-05, D-ADOPT-02 + entrada) -----------------


def test_create_adopcion_rejects_inactive_animal() -> None:
    """animal_id that exists but activo=false → CTE returns 0 rows.

    The CTE returns 0 (animal FK fails), then the service runs the
    animales disambiguation SELECT which also returns 0, then raises
    ``ValueError("animal_id does not reference an active animal")``.
    """
    client, captured = _make_client(_validation_handler(animal_exists=False))

    with pytest.raises(ValueError, match="animal_id"):
        adopciones_service.create_adopcion(client, _params_minimal())

    # 1 CTE + 1 disambiguation animales SELECT = 2 calls; the disambig
    # for vol/entry never runs (animal check short-circuits).
    assert len(captured) == 2
    assert "INSERT INTO adopciones" in captured[0][0]
    assert "FROM animales" in captured[1][0]
    assert "FROM voluntarios" not in captured[1][0]


def test_create_adopcion_rejects_inactive_voluntario_per_vol_05() -> None:
    """VOL-05: animal check passes, voluntario check fails -> ValueError.

    The CTE runs and returns 0 (vol FK fails). The service then runs
    the animales disambig (passes) + voluntarios disambig (fails) and
    raises.
    """
    client, captured = _make_client(
        _validation_handler(voluntario_exists=False)
    )

    with pytest.raises(ValueError, match="voluntario_seguimiento_id"):
        adopciones_service.create_adopcion(client, _params_minimal())

    # 1 CTE + 2 disambiguation SELECTs (animales, voluntarios).
    assert len(captured) == 3
    assert "INSERT INTO adopciones" in captured[0][0]
    assert "FROM animales" in captured[1][0]
    assert "FROM voluntarios" in captured[2][0]


def test_create_adopcion_rejects_missing_entrada_origen() -> None:
    """P1 (risk review 2026-07-04): missing entrada_origen_id -> 422.

    Prior to the helper, a bad UUID slipped past the service and
    surfaced as an LocalBackend FK violation (500). Now the CTE returns 0
    rows, the disambiguation SELECTs run, and the service raises a
    clean ``ValueError`` with the bad id in the message.
    """
    params = {**_params_minimal(), "entrada_origen_id": "cccccccc-cccc-cccc-cccc-cccccccccccc"}
    client, captured = _make_client(_validation_handler(entrada_exists=False))

    with pytest.raises(ValueError, match="entrada_origen_id"):
        adopciones_service.create_adopcion(client, params)

    # 1 CTE + 3 disambiguation SELECTs (animal pass, vol pass, entrada fail).
    assert len(captured) == 4
    assert "INSERT INTO adopciones" in captured[0][0]
    assert "FROM animales" in captured[1][0]
    assert "FROM voluntarios" in captured[2][0]
    assert "FROM entradas" in captured[3][0]


def test_create_adopcion_accepts_soft_deleted_entrada() -> None:
    """A soft-deleted entrada (existente, activo=false) still resolves.

    Mirrors the ``acogidas`` pattern: we only check existence, not
    ``activo``. The CTE's ``checked_entrada`` returns the row, the
    INSERT proceeds, no 422.
    """
    params = {**_params_minimal(), "entrada_origen_id": "cccccccc-cccc-cccc-cccc-cccccccccccc"}
    client, captured = _make_client(_validation_handler(entrada_exists=True))

    adopciones_service.create_adopcion(client, params)

    # LIFECYCLE-02 (issue #32): the service fires extra lifecycle SQL
    # calls in the same transaction. We assert the CTE was issued
    # rather than the total call count -- the lifecycle SQL shape is
    # pinned by ``tests/test_adopciones_lifecycle_events.py``.
    assert any(
        "INSERT INTO adopciones" in c[0] for c in captured
    ), "create_adopcion MUST issue the CTE-shaped INSERT"


def test_create_adopcion_with_soft_deleted_animal_returns_422() -> None:
    """CRITICAL-1 (review 2026-07-04): TOCTOU-safe CTE.

    If the animal is deactivated between the form load and the submit,
    the CTE returns 0 rows (animal FK check fails) and the service
    raises ``ValueError``. The previous design had the SELECT + INSERT
    in separate statements; here they're one CTE so there is no
    window for the animal to slip from activo=true to activo=false
    between the check and the write.
    """
    client, captured = _make_client(_validation_handler(animal_exists=False))

    with pytest.raises(ValueError, match="animal_id"):
        adopciones_service.create_adopcion(client, _params_minimal())

    # CTE returned 0, disambiguation animales SELECT also returned 0,
    # service raised. 2 round-trips, no INSERT actually happened.
    assert len(captured) == 2
    insert_calls = [c for c in captured if "INSERT INTO adopciones" in c[0]]
    assert len(insert_calls) == 1  # the CTE tried once, returned 0 rows
    # The handler didn't return any INSERT data — disambiguation took over.


# --- create: numeric validation -------------------------------------------


def test_create_adopcion_rejects_non_numeric_donativo() -> None:
    params = {**_params_minimal(), "donativo_preadopcion": "no-es-numero"}
    client, captured = _make_client(_validation_handler())

    with pytest.raises(ValueError, match="donativo_preadopcion"):
        adopciones_service.create_adopcion(client, params)

    assert captured == []


def test_create_adopcion_rejects_boolean_donativo() -> None:
    """bool is a subclass of int in Python; reject it explicitly."""
    params = {**_params_minimal(), "donativo_adopcion": True}
    client, captured = _make_client(_validation_handler())

    with pytest.raises(ValueError, match="donativo_adopcion"):
        adopciones_service.create_adopcion(client, params)

    assert captured == []


# --- create: conflict (UNIQUE (animal_id, fecha_adopcion)) -----------------


def test_create_adopcion_translates_409_to_adopcion_conflict_error() -> None:
    """P1-1 (readability review): AdopcionConflictError on UNIQUE clash.

    An LocalBackend 409 envelope with the natural-key substring in the
    body is translated into ``AdopcionConflictError`` (a
    ``ValueError`` subclass) so the route can render a 409 form
    instead of a generic 422.
    """

    def _handler(query: str, _params: list[object]) -> Any:
        if "INSERT INTO adopciones" in query:
            return _ErrorResponse(
                409,
                {"error": "duplicate key value violates unique constraint "
                 "adopciones_natural_key"},
            )
        raise AssertionError(f"Unexpected SQL: {query!r}")

    client, _ = _make_client(_handler)

    with pytest.raises(adopciones_service.AdopcionConflictError):
        adopciones_service.create_adopcion(client, _params_minimal())


# --- list -----------------------------------------------------------------


def test_list_adopciones_returns_active_rows_ordered_by_fecha_alta() -> None:
    rows = [
        _row({"id": "adop-2", "fecha_alta": "2026-07-04T12:00:00Z"}),
        _row({"id": "adop-1", "fecha_alta": "2026-07-04T10:00:00Z"}),
    ]
    client, captured = _make_client(lambda q, p: rows)

    result = adopciones_service.list_adopciones(client)

    assert [a.id for a in result] == ["adop-2", "adop-1"]
    query = captured[0][0]
    assert "FROM adopciones" in query
    assert "WHERE activo = true" in query
    assert "ORDER BY fecha_alta DESC" in query
    # CRITICAL-2 (review 2026-07-04): hard LIMIT 100 cap.
    assert "LIMIT 100" in query


# --- get by id ------------------------------------------------------------


def test_get_adopcion_by_id_returns_row_or_none() -> None:
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if params == ["missing"]:
            return []
        return [_row({"id": params[0]})]

    client, captured = _make_client(_handler)
    found = adopciones_service.get_adopcion_by_id(client, "found")
    missing = adopciones_service.get_adopcion_by_id(client, "missing")

    assert found is not None and found.id == "found"
    assert missing is None
    assert [call[1] for call in captured] == [["found"], ["missing"]]


# --- update ---------------------------------------------------------------


def test_update_adopcion_validates_and_updates_minimal_fields() -> None:
    """Single CTE round-trip on update: FK checks + UPDATE.

    CRITICAL-1: the CTE design issues one UPDATE statement with the FK
    checks inlined as CTEs (rather than separate SELECTs). The test
    asserts exactly one captured SQL.
    """
    client, captured = _make_client(
        _validation_handler(update_row=_row({"nombre_adoptante": "María Editada"}))
    )

    result = adopciones_service.update_adopcion(
        client,
        "11111111-1111-1111-1111-111111111111",
        {**_params_minimal(), "nombre_adoptante": "María Editada"},
    )

    assert result is not None
    assert result.nombre_adoptante == "María Editada"
    # LIFECYCLE-02 (issue #32): update_adopcion now issues a
    # ``get_adopcion_by_id`` BEFORE the UPDATE to capture the previous
    # ``fecha_devolucion`` for the ADOPTION_RETURNED transition. We
    # assert the UPDATE CTE was issued rather than the total call count.
    cte = next(c for c in captured if "UPDATE adopciones SET" in c[0])
    assert "WITH checked_animal" in cte[0]
    assert "updated_at = now()" in cte[0]
    # First param is the adopcion_id.
    assert cte[1][0] == "11111111-1111-1111-1111-111111111111"
    # FK placeholders shifted by one in the UPDATE CTE.
    assert cte[1][1] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # animal
    assert cte[1][2] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # vol


def test_update_adopcion_returns_none_when_id_missing() -> None:
    """Update returns ``None`` (not ValueError) when the id does not exist.

    The CTE returns 0 (id not found); the service runs the
    ``get_adopcion_by_id`` disambiguation; that also returns 0; the
    service returns ``None``.
    """
    client, captured = _make_client(_validation_handler())

    result = adopciones_service.update_adopcion(client, "missing", _params_minimal())

    assert result is None
    # 1 CTE (0 rows) + 1 disambiguation get_adopcion_by_id (0 rows).
    assert len(captured) == 2


def test_update_adopcion_revalidates_voluntario_activo() -> None:
    """VOL-05: editing a row to an inactive voluntario must be rejected."""
    client, captured = _make_client(
        _validation_handler(voluntario_exists=False)
    )

    with pytest.raises(ValueError, match="voluntario_seguimiento_id"):
        adopciones_service.update_adopcion(
            client,
            "11111111-1111-1111-1111-111111111111",
            _params_minimal(),
        )

    # LIFECYCLE-02 (issue #32): update_adopcion now issues a
    # ``get_adopcion_by_id`` BEFORE the UPDATE so we can detect the
    # active -> returned transition. On the validation-failure path
    # the captured list grows by one (the prior SELECT) and
    # ``captured[0]`` is the prior SELECT rather than the UPDATE CTE.
    # We assert the UPDATE CTE was issued rather than the total
    # call count.
    assert any("UPDATE adopciones SET" in c[0] for c in captured)


def test_update_adopcion_translates_409_to_adopcion_conflict_error() -> None:
    """P2-1 (risk review 2026-07-04): UNIQUE clash on update -> 409.

    Previously only ``create_adopcion`` translated the 409 to
    ``AdopcionConflictError``. Now ``update_adopcion`` does the same so
    editing a row to clash with another adoption renders as a friendly
    409 form, not a 500.
    """

    def _handler(query: str, _params: list[object]) -> Any:
        # LIFECYCLE-02 (issue #32): update_adopcion issues a
        # ``get_adopcion_by_id`` BEFORE the UPDATE; answer it with
        # the standard ``_row()`` so the prior-state lookup does not
        # blow up.
        if "FROM adopciones" in query and "WHERE id = $1" in query:
            return [_row()]
        if "UPDATE adopciones SET" in query:
            return _ErrorResponse(
                409,
                {"error": "duplicate key value violates unique constraint "
                 "adopciones_natural_key"},
            )
        raise AssertionError(f"Unexpected SQL: {query!r}")

    client, _ = _make_client(_handler)

    with pytest.raises(adopciones_service.AdopcionConflictError):
        adopciones_service.update_adopcion(
            client,
            "11111111-1111-1111-1111-111111111111",
            _params_minimal(),
        )


# --- soft delete ---------------------------------------------------------


def test_delete_adopcion_soft_deletes_without_physical_delete() -> None:
    client, captured = _make_client(
        lambda q, p: [{"id": "adop-1"}]
    )
    result = adopciones_service.delete_adopcion(client, "adop-1")

    assert result is True
    assert len(captured) == 1
    query = captured[0][0]
    assert "UPDATE adopciones" in query
    assert "SET activo = false" in query
    assert "WHERE id = $1 AND activo = true" in query
    assert "DELETE FROM" not in query


def test_delete_adopcion_returns_false_when_already_inactive() -> None:
    """The ``WHERE activo = true`` filter returns 0 rows → service False."""
    client, captured = _make_client(
        lambda q, p: []
    )
    result = adopciones_service.delete_adopcion(client, "missing")

    assert result is False
    assert len(captured) == 1


# --- search by adoptante (D-ADOPT-04) -------------------------------------


def test_search_adopciones_by_adoptante_uses_ilike() -> None:
    client, captured = _make_client(
        lambda q, p: [_row()]
    )

    result = adopciones_service.search_adopciones_by_adoptante(client, "garcia")

    assert len(result) == 1
    query = captured[0][0]
    assert "ILIKE" in query
    assert "nombre_adoptante ILIKE" in query
    assert "ESCAPE '\\'" in query
    assert "LIMIT 100" in query
    assert captured[0][1] == ["garcia"]


def test_search_adopciones_by_adoptante_empty_returns_empty_list() -> None:
    """Empty / whitespace filters skip the SQL roundtrip (D-ADOPT-04)."""
    client, captured = _make_client(
        lambda q, p: [_row()]
    )

    result = adopciones_service.search_adopciones_by_adoptante(client, "   ")

    assert result == []
    assert captured == []


def test_search_adopciones_by_adoptante_trims_whitespace() -> None:
    client, captured = _make_client(
        lambda q, p: []
    )

    adopciones_service.search_adopciones_by_adoptante(client, "  Maria  ")

    assert captured[0][1] == ["Maria"]


def test_search_by_adoptante_escapes_wildcards() -> None:
    """CRITICAL-2 + P2-2 (risk review 2026-07-04): literal `%` and `_`
    do not act as wildcards after escaping.

    A malicious or accidental `?adoptante=%` (which would normally match
    every row) must instead match only literal `%` characters. We
    assert that the bound param is the escaped form (``\\%`` not `%``).
    """
    client, captured = _make_client(
        lambda q, p: []
    )

    adopciones_service.search_adopciones_by_adoptante(client, "%")

    # ``%`` → ``\%`` so the literal % in the input does NOT become a
    # wildcard. The SQL uses ``ESCAPE '\\'`` to honor the backslash.
    assert captured[0][1] == ["\\%"]


def test_search_by_adoptante_escapes_underscore_and_backslash() -> None:
    """Same protection for ``_`` (single-char wildcard) and ``\\``."""
    client, captured = _make_client(
        lambda q, p: []
    )

    adopciones_service.search_adopciones_by_adoptante(client, "_a\\b")

    # Order matters: backslash FIRST so the new ``\\`` introduced for
    # ``%`` / ``_`` are not themselves escaped on a second pass.
    # Input "_a\b" becomes: "_" → "\_", "a" → "a", "\" → "\\",
    # "b" → "b" → final "\\\_a\\\\b".
    assert captured[0][1] == ["\\_a\\\\b"]


def test_search_by_adoptante_returns_max_limit_results() -> None:
    """Hard ``LIMIT 100`` cap on the search SQL.

    Mirrors ``test_list_adopciones_returns_active_rows_ordered_by_fecha_alta``
    for the list endpoint — both bounded by the same constant.
    """
    client, captured = _make_client(
        lambda q, p: []
    )

    adopciones_service.search_adopciones_by_adoptante(client, "garcia")

    assert "LIMIT 100" in captured[0][0]


# --- is_active derived (D-ADOPT-05) ---------------------------------------


def test_is_active_true_when_fecha_devolucion_is_null() -> None:
    row = _row({"fecha_devolucion": None})
    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.is_active is True


def test_is_active_false_when_fecha_devolucion_is_set() -> None:
    row = _row({"fecha_devolucion": "2026-08-15"})
    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.is_active is False


def test_is_active_survives_soft_delete_independently() -> None:
    """A row with activo=false AND fecha_devolucion set is still !is_active.

    The operator can read both signals: ``activo`` is the DB-level
    soft-delete (filter lists); ``is_active`` is the domain semantic
    (is the animal still with the family?). They can diverge when a
    family returns the animal AND the operator later soft-deletes the
    adoption row. Both correctly read False from the perspective the
    caller cares about.
    """
    row = _row({"activo": False, "fecha_devolucion": "2026-08-15"})
    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.is_active is False
    assert adopcion.activo is False


# --- default tipo_adopcion via row mapping --------------------------------


def test_row_to_adopcion_defaults_tipo_adopcion_to_regular() -> None:
    """A row that predates the migration has no ``tipo_adopcion`` col."""
    row = _row()
    row.pop("tipo_adopcion")

    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.tipo_adopcion == "regular"


def test_row_to_adopcion_coerces_donativos_to_float() -> None:
    """Decimal/numeric values come back as strings in some responses."""
    row = _row({"donativo_preadopcion": "50.00", "donativo_adopcion": "150.50"})

    adopcion = adopciones_service._row_to_adopcion(row)

    assert adopcion.donativo_preadopcion == 50.0
    assert adopcion.donativo_adopcion == 150.5


# --- actor_user_id audit (P2-3) --------------------------------------------


def test_create_adopcion_includes_actor_user_id_in_log_safe() -> None:
    """P2-3 (risk review 2026-07-04): audit logs carry ``actor_user_id``.

    The ``adopciones.created`` event MUST include ``actor_user_id``
    so audit pipelines can attribute the change.
    """
    captured_logs: list[logging.LogRecord] = []

    class _CapturingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_logs.append(record)

    logger = logging.getLogger("app")
    # The default level for a named logger is WARNING; lower it to INFO so
    # the INFO records emitted by ``log_safe`` reach our handler. The
    # level is restored in the ``finally`` so this test never leaks
    # state into siblings.
    saved_level = logger.level
    logger.setLevel(logging.INFO)
    handler = _CapturingHandler(level=logging.INFO)
    logger.addHandler(handler)
    try:
        client, _ = _make_client(_validation_handler())
        adopciones_service.create_adopcion(
            client, _params_minimal(), actor_user_id="u-ana"
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved_level)

    created_records = [
        r
        for r in captured_logs
        if r._caller_fields.get("event") == "adopciones.created"
    ]
    assert len(created_records) == 1
    assert created_records[0]._caller_fields["actor_user_id"] == "u-ana"


# --- helpers --------------------------------------------------------------


def _make_client(
    handler: Callable[[str, list[object]], Any],
) -> tuple[_FakeSqlExecutor, list[tuple[str, list[object]]]]:
    """Build a fake executor that delegates every ``execute_sql`` to ``handler``.

    The handler signature mirrors what the old ``_validation_handler``
    produced for httpx, minus the request/response envelopes: it
    inspects ``(query, params)`` and returns a list of dicts, an
    ``_ErrorResponse``, or ``None`` to fall through to the empty-list
    default.
    """
    fake = _FakeSqlExecutor()
    fake.set_handler(handler)
    return fake, fake.calls
