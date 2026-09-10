"""Service-layer tests for FOSTER-02 estancias de acogida.

The ``acogidas.service`` module owns:

- create / list / get / update / close / soft-delete of ``acogidas``
- validation: required fields (animal_id, fecha_inicio), FK validation
  (animal activo, casa activa, voluntario activo x4, entrada exists)
- compute_duracion + is_active pure helpers
- close_acogida vs delete_acogida semantic split (D-EST-04)

Mirror of the ``tests/test_entradas.py`` and ``tests/test_foster.py``
patterns: real LocalPostgresExecutor + httpx.MockTransport for SQL shape
assertion. Each test records the SQL queries captured and asserts the
shape; the assertions fail loudly if a future refactor breaks the
contract.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from app.core.data_access import BackendError
from app.modules.acogidas import service as acogidas_service


class _ErrorResponse:
    """Marker returned by a fake handler to signal a backend error."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for unit tests.

    Records every ``execute_sql`` call (query + params) so callers can
    assert on the SQL shape without standing up a Postgres instance.
    Configured handlers let CTE + disambiguation tests run
    deterministically. Returns ``[]`` when the handler returns ``None``
    so the fake never accidentally short-circuits a "row missing" branch.
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


def _make_client(
    handler: Callable[[str, list[object]], Any],
) -> tuple[_FakeSqlExecutor, list[tuple[str, list[object]]]]:
    """Build a fake executor that delegates every ``execute_sql`` to ``handler``.

    The handler signature mirrors what ``_make_handler`` produces:
    it inspects ``(query, params)`` and returns a list of dicts or an
    ``_ErrorResponse``. Returned ``calls`` is captured by reference so
    tests can assert SQL + positional params without monkey-patching.
    """
    fake = _FakeSqlExecutor()
    fake.set_handler(handler)
    return fake, fake.calls


def _params_minimal() -> dict[str, Any]:
    return {
        "animal_id": "11111111-1111-1111-1111-111111111111",
        "casa_acogida_id": None,
        "voluntario_acogida_id": None,
        "voluntario_seguimiento1_id": None,
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": None,
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12, Alcalá de Henares",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo, sin medicación",
    }


def _row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "22222222-2222-2222-2222-222222222222",
        "animal_id": "11111111-1111-1111-1111-111111111111",
        "casa_acogida_id": None,
        "voluntario_acogida_id": None,
        "voluntario_seguimiento1_id": None,
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": None,
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12, Alcalá de Henares",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo, sin medicación",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "fecha_baja": None,
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


def _animal_row(
    animal_id: str = "11111111-1111-1111-1111-111111111111",
    activo: bool = True,
) -> dict[str, Any]:
    return {"id": animal_id, "activo": activo}


def _casa_row(
    casa_id: str = "33333333-3333-3333-3333-333333333333",
    activo: bool = True,
) -> dict[str, Any]:
    return {"id": casa_id, "activo": activo}


def _voluntario_row(
    vol_id: str = "44444444-4444-4444-4444-444444444444",
    activo: bool = True,
) -> dict[str, Any]:
    return {"id": vol_id, "activo": activo}


def _make_handler(insert_row: dict[str, Any] | None = None):
    """Default handler that returns a valid animal and lets the INSERT through."""

    def _handler(query: str, params: list[object]) -> Any:
        # Animal existence check: SELECT FROM animales WHERE id = $1
        # (FK validation in create_acogida -- issue #32 acceptance).
        if "FROM animales" in query and "WHERE id = $1" in query:
            return [_animal_row(params[0])]
        # LIFECYCLE-02 (issue #32): the cascade's ficha SELECT
        # (``LEFT JOIN animal_current_state WHERE animales.id = $1``)
        # does NOT carry the substring ``"WHERE id = $1"`` -- the column
        # is qualified with the table alias. Match it separately so the
        # cascade's ``build_select_ficha`` call returns a valid ficha
        # row and the state derivation does not crash on missing keys.
        if (
            "FROM animales" in query
            and "LEFT JOIN animal_current_state" in query
        ):
            return [_animal_row(params[0])]
        # Casa existence check: SELECT FROM casas_acogida
        if "FROM casas_acogida" in query and "WHERE id = $1" in query:
            return [_casa_row(params[0])]
        # Voluntario existence check: SELECT FROM voluntarios WHERE activo=true
        if (
            "FROM voluntarios" in query
            and "WHERE id = $1" in query
            and "activo = true" in query
        ):
            return [_voluntario_row(params[0])]
        # Entrada existence check: SELECT FROM entradas
        if "FROM entradas" in query and "WHERE id = $1" in query:
            return [{"id": params[0]}]
        # LIFECYCLE-02 (issue #32): create_acogida / close_acogida
        # emit lifecycle events into ``animal_lifecycle_events`` and
        # refresh ``animal_current_state`` via
        # ``actualizar_estado_animal``. Those writes hit:
        #   * ``INSERT INTO animal_lifecycle_events`` (event log)
        #   * ``FROM entradas/acogidas/adopciones`` active-collection
        #     SELECTs (the cascade inputs)
        #   * ``INSERT INTO animal_current_state`` (cache UPSERT)
        # Returning empty lists keeps the cascade happy ("no other
        # active placements") without coupling the CRUD tests to the
        # lifecycle SQL shape -- that's pinned by
        # ``tests/test_acogidas_lifecycle_events.py``.
        if "INSERT INTO animal_lifecycle_events" in query:
            return []
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
        if "INSERT INTO animal_current_state" in query:
            return []
        if "INSERT INTO acogidas" in query:
            return [insert_row or _row()]
        if "UPDATE acogidas SET" in query:
            return [insert_row or _row()]
        # LIFECYCLE-02 (issue #32): let cascade-driven SQL through with
        # an empty response so the cascade does not crash. The SQL shape
        # is pinned by ``tests/test_acogidas_lifecycle_events.py``.
        lifecycle_resp = _lifecycle_query_response(query)
        if lifecycle_resp is not None:
            return lifecycle_resp
        raise AssertionError(f"Unexpected SQL: {query}")

    return _handler


def _lifecycle_query_response(query: str) -> list[dict[str, object]] | None:
    """Return a 200/[] response for any lifecycle SQL query the cascade issues.

    LIFECYCLE-02 (issue #32) makes ``create_acogida`` / ``close_acogida``
    fire extra SQL: ``INSERT INTO animal_lifecycle_events`` (event log),
    the cascade's ficha + active-placements SELECTs, and the
    ``INSERT INTO animal_current_state`` cache UPSERT. Pre-existing
    CRUD tests use custom inline handlers that only know about the
    ``INSERT/UPDATE acogidas`` shape; this helper lets those tests
    accept the new lifecycle SQL without coupling to its exact
    parameter list. The lifecycle SQL shape is pinned by
    ``tests/test_acogidas_lifecycle_events.py``.
    """
    if "INSERT INTO animal_lifecycle_events" in query:
        return []
    if "INSERT INTO animal_current_state" in query:
        return []
    if "LEFT JOIN animal_current_state" in query and "FROM animales" in query:
        return [_animal_row()]
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


def test_create_acogida_inserts_with_all_columns() -> None:
    """Happy path: all valid FKs + required fields -> row inserted."""
    client, captured = _make_client(_make_handler())

    result = acogidas_service.create_acogida(client, _params_minimal())

    assert isinstance(result, acogidas_service.Acogida)
    assert result.id == "22222222-2222-2222-2222-222222222222"
    assert result.animal_id == "11111111-1111-1111-1111-111111111111"
    assert result.fecha_inicio == "2026-07-04"
    assert result.activo is True
    assert result.casa_acogida_id is None
    assert result.fecha_final is None

    # The captured SQL must include: existence checks for animal + the
    # INSERT into acogidas (no voluntario checks because all are null).
    insert_call = next(c for c in captured if "INSERT INTO acogidas" in c[0])
    assert insert_call[0].startswith("INSERT INTO acogidas")
    insert_params = insert_call[1]
    assert insert_params[0] == "11111111-1111-1111-1111-111111111111"  # animal_id
    assert "2026-07-04" in insert_params  # fecha_inicio


def test_create_acogida_with_all_voluntarios_valid() -> None:
    """All 4 voluntario FKs valid -> row inserted with all FKs populated."""
    params = {
        **_params_minimal(),
        "voluntario_acogida_id": "vol-acog",
        "voluntario_seguimiento1_id": "vol-seg1",
        "voluntario_seguimiento2_id": "vol-seg2",
        "voluntario_sanitario_id": "vol-san",
    }
    inserted = _row({
        "voluntario_acogida_id": "vol-acog",
        "voluntario_seguimiento1_id": "vol-seg1",
        "voluntario_seguimiento2_id": "vol-seg2",
        "voluntario_sanitario_id": "vol-san",
    })
    client, captured = _make_client(_make_handler(inserted))

    result = acogidas_service.create_acogida(client, params)

    assert result.voluntario_acogida_id == "vol-acog"
    assert result.voluntario_seguimiento1_id == "vol-seg1"
    assert result.voluntario_seguimiento2_id == "vol-seg2"
    assert result.voluntario_sanitario_id == "vol-san"

    # Four voluntario existence checks + one for animal.
    vol_checks = [
        c for c in captured
        if "FROM voluntarios" in c[0] and "activo = true" in c[0]
    ]
    assert len(vol_checks) == 4


def test_create_acogida_with_casa_acogida_valid() -> None:
    """casa_acogida_id valid -> row inserted with FK populated."""
    params = {**_params_minimal(), "casa_acogida_id": "casa-1"}
    inserted = _row({"casa_acogida_id": "casa-1"})
    client, captured = _make_client(_make_handler(inserted))

    result = acogidas_service.create_acogida(client, params)

    assert result.casa_acogida_id == "casa-1"
    # Casa check + animal check + insert.
    casa_check = next(c for c in captured if "FROM casas_acogida" in c[0])
    assert casa_check[1] == ["casa-1"]


def test_create_acogida_with_null_casa_acogida_skips_casa_check() -> None:
    """When casa_acogida_id is None, the FK existence check is skipped."""
    client, captured = _make_client(_make_handler())

    acogidas_service.create_acogida(client, _params_minimal())

    # No ``FROM casas_acogida`` SELECT should have run.
    casa_checks = [c for c in captured if "FROM casas_acogida" in c[0]]
    assert casa_checks == []


def test_create_acogida_with_entrada_origen_valid() -> None:
    """entrada_origen_id valid -> row inserted with FK populated."""
    params = {**_params_minimal(), "entrada_origen_id": "ent-1"}
    inserted = _row({"entrada_origen_id": "ent-1"})
    client, captured = _make_client(_make_handler(inserted))

    result = acogidas_service.create_acogida(client, params)

    assert result.entrada_origen_id == "ent-1"
    entrada_check = next(c for c in captured if "FROM entradas" in c[0] and "WHERE id = $1" in c[0])
    assert entrada_check[1] == ["ent-1"]


# --- create: required-field validation ------------------------------------


def test_create_acogida_rejects_empty_animal_id() -> None:
    """animal_id empty raises ValueError BEFORE any DB call."""
    client, captured = _make_client(_make_handler())

    with pytest.raises(ValueError, match="animal_id es obligatorio"):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), "animal_id": ""}
        )
    assert captured == []


def test_create_acogida_rejects_empty_fecha_inicio() -> None:
    """fecha_inicio empty raises ValueError BEFORE any DB call."""
    client, captured = _make_client(_make_handler())

    with pytest.raises(ValueError, match="fecha_inicio es obligatorio"):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), "fecha_inicio": ""}
        )
    assert captured == []


def test_create_acogida_accepts_malformed_fecha_inicio() -> None:
    """fecha_inicio is not validated for format at the service layer.

    The builder does NOT validate ``fecha_inicio`` for ISO format --
    the DB layer enforces it. We accept any string here; the test pins
    the contract so a future refactor that adds strict format
    validation knows the previous behaviour.
    """
    client, captured = _make_client(_make_handler())

    # Use a malformed fecha -- the service passes through.
    acogidas_service.create_acogida(
        client, {**_params_minimal(), "fecha_inicio": "ayer"}
    )
    insert_call = next(c for c in captured if "INSERT INTO acogidas" in c[0])
    assert "ayer" in insert_call[1]


# --- create: FK validation (animal / casa / voluntario / entrada) ---------


def test_create_acogida_rejects_inactive_animal() -> None:
    """animal_id inactive -> ValueError; no INSERT runs."""

    def _handler(query: str, params: list[object]) -> Any:
        if "FROM animales" in query:
            return [_animal_row(activo=False)]
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)

    with pytest.raises(ValueError, match="animal_id debe apuntar"):
        acogidas_service.create_acogida(client, _params_minimal())
    # No INSERT runs.
    insert_calls = [c for c in captured if "INSERT INTO acogidas" in c[0]]
    assert insert_calls == []


def test_create_acogida_rejects_inactive_casa() -> None:
    """casa_acogida_id inactive -> ValueError; no INSERT runs."""

    def _handler(query: str, params: list[object]) -> Any:
        if "FROM animales" in query and "WHERE id = $1" in query:
            return [_animal_row()]
        if "FROM casas_acogida" in query:
            return [_casa_row(activo=False)]
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)

    with pytest.raises(ValueError, match="casa_acogida_id debe apuntar"):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), "casa_acogida_id": "casa-1"}
        )
    insert_calls = [c for c in captured if "INSERT INTO acogidas" in c[0]]
    assert insert_calls == []


def test_create_acogida_rejects_inactive_voluntario() -> None:
    """Any voluntario FK inactive -> ValueError (VOL-05)."""

    def _handler(query: str, params: list[object]) -> Any:
        if "FROM animales" in query and "WHERE id = $1" in query:
            return [_animal_row()]
        if (
            "FROM voluntarios" in query
            and "WHERE id = $1" in query
            and "activo = true" in query
        ):
            return [_voluntario_row(activo=False)]
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)

    with pytest.raises(ValueError, match="voluntario.*debe apuntar"):
        acogidas_service.create_acogida(
            client, {**_params_minimal(), "voluntario_acogida_id": "vol-1"}
        )
    insert_calls = [c for c in captured if "INSERT INTO acogidas" in c[0]]
    assert insert_calls == []


# --- update ---------------------------------------------------------------


def test_update_acogida_modifies_record() -> None:
    """update_acogida writes new fields and bumps updated_at."""
    inserted = _row({"direccion": "Nueva direccion"})
    client, captured = _make_client(_make_handler(inserted))

    result = acogidas_service.update_acogida(
        client, "22222222-2222-2222-2222-222222222222",
        {**_params_minimal(), "direccion": "Nueva direccion"},
    )

    assert result is not None
    assert result.direccion == "Nueva direccion"
    update_call = next(c for c in captured if "UPDATE acogidas SET" in c[0])
    assert update_call[1][0] == "22222222-2222-2222-2222-222222222222"


def test_update_acogida_returns_none_when_id_missing() -> None:
    """update_acogida returns None when the UPDATE matches no row."""

    def _handler(query: str, params: list[object]) -> Any:
        # FK revalidation checks come first.
        if "FROM animales" in query and "WHERE id = $1" in query:
            return [_animal_row(params[0])]
        if (
            "FROM voluntarios" in query
            and "WHERE id = $1" in query
            and "activo = true" in query
        ):
            return [_voluntario_row(params[0])]
        if (
            "FROM acogidas" in query
            and "fecha_final IS NULL" in query
            and "activo = true" in query
        ):
            return []
        if (
            "FROM entradas" in query
            and "fecha_salida IS NULL" in query
            and "activo = true" in query
        ):
            return []
        if (
            "FROM adopciones" in query
            and "fecha_devolucion IS NULL" in query
            and "activo = true" in query
        ):
            return []
        if "FROM animales" in query and "LEFT JOIN animal_current_state" in query:
            return [_animal_row()]
        if "INSERT INTO animal_lifecycle_events" in query:
            return []
        if "INSERT INTO animal_current_state" in query:
            return []
        if "UPDATE acogidas SET" in query:
            return []
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    result = acogidas_service.update_acogida(
        client, "missing-id", _params_minimal()
    )

    assert result is None


# --- close / soft delete ---------------------------------------------------


def test_close_acogida_sets_fecha_final() -> None:
    """close_acogida sets fecha_final = today and keeps activo=true."""
    today = date.today().isoformat()
    inserted = _row({"fecha_final": today})
    client, captured = _make_client(_make_handler(inserted))

    result = acogidas_service.close_acogida(
        client, "22222222-2222-2222-2222-222222222222"
    )

    assert result is not None
    assert result.fecha_final == today
    update_call = next(c for c in captured if "UPDATE acogidas SET" in c[0])
    assert "fecha_final" in update_call[0]


def test_close_acogida_returns_none_when_id_missing() -> None:
    """close_acogida returns None when the id does not exist."""

    def _handler(query: str, params: list[object]) -> Any:
        if "UPDATE acogidas SET" in query:
            return []
        raise AssertionError(f"Unexpected SQL: {query}")

    client, _ = _make_client(_handler)
    result = acogidas_service.close_acogida(
        client, "missing-id"
    )

    assert result is None


def test_delete_acogida_soft_deletes() -> None:
    """delete_acogida soft-deletes the row (activo=false)."""
    client, captured = _make_client(
        lambda q, p: [{"id": "a-1"}]
    )

    result = acogidas_service.delete_acogida(
        client, "22222222-2222-2222-2222-222222222222"
    )

    assert result is True
    delete_call = captured[0]
    assert "UPDATE acogidas SET" in delete_call[0] or "UPDATE acogidas" in delete_call[0]
    assert "activo = false" in delete_call[0]


def test_delete_acogida_returns_false_when_id_missing() -> None:
    """delete_acogida returns False when the row does not exist or is already inactive."""
    client, _ = _make_client(lambda q, p: [])

    result = acogidas_service.delete_acogida(
        client, "missing-id"
    )

    assert result is False


# --- get by id ------------------------------------------------------------


def test_get_acogida_by_id_returns_row_or_none() -> None:
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if params == ["missing"]:
            return []
        return [_row({"id": params[0]})]

    client, captured = _make_client(_handler)
    found = acogidas_service.get_acogida_by_id(client, "found")
    missing = acogidas_service.get_acogida_by_id(client, "missing")

    assert found is not None and found.id == "found"
    assert missing is None
    assert [c[1] for c in captured] == [["found"], ["missing"]]


# --- list -----------------------------------------------------------------


def test_list_acogidas_returns_rows_ordered() -> None:
    rows = [
        _row({"id": "acog-2", "fecha_inicio": "2026-07-05"}),
        _row({"id": "acog-1", "fecha_inicio": "2026-07-04"}),
    ]
    client, captured = _make_client(lambda q, p: rows)

    result = acogidas_service.list_acogidas(client)

    assert [a.id for a in result] == ["acog-2", "acog-1"]
    query = captured[0][0]
    assert "FROM acogidas" in query
    assert "ORDER BY fecha_inicio DESC" in query


def test_list_acogidas_activas_solo_filter() -> None:
    """activas_solo=True (explicit) emits the fecha_final IS NULL filter."""
    client, captured = _make_client(lambda q, p: [_row()])

    acogidas_service.list_acogidas(client, activas_solo=True)

    query = captured[0][0]
    assert "FROM acogidas" in query
    assert "fecha_final IS NULL" in query


def test_list_acogidas_activas_only_returns_active() -> None:
    """When activas_solo=True, only active rows are returned by service."""
    rows = [_row({"id": "acog-1", "activo": True})]
    client, _ = _make_client(lambda q, p: rows)

    result = acogidas_service.list_acogidas(client, activas_solo=True)

    assert [a.id for a in result] == ["acog-1"]


def test_list_acogidas_includes_inactive_when_flag_false() -> None:
    """When activas_solo=False, inactive rows are returned too."""
    rows = [
        _row({"id": "acog-1", "activo": True}),
        _row({"id": "acog-2", "activo": False}),
    ]
    client, _ = _make_client(lambda q, p: rows)

    result = acogidas_service.list_acogidas(client, activas_solo=False)

    assert {a.id for a in result} == {"acog-1", "acog-2"}


# --- pure helpers ---------------------------------------------------------


def test_compute_duracion_open_ended() -> None:
    """compute_duracion returns None when fecha_final is None (open-ended)."""
    row = _row({"fecha_final": None})
    acogida = acogidas_service._row_to_acogida(row)

    assert acogidas_service.compute_duracion(acogida) is None


def test_compute_duracion_known_range() -> None:
    """compute_duracion returns days between fecha_inicio and fecha_final."""
    row = _row({"fecha_inicio": "2026-07-01", "fecha_final": "2026-07-10"})
    acogida = acogidas_service._row_to_acogida(row)

    assert acogidas_service.compute_duracion(acogida) == 9


def test_is_active_true_when_fecha_final_is_null() -> None:
    row = _row({"fecha_final": None})
    acogida = acogidas_service._row_to_acogida(row)

    assert acogidas_service.is_active(acogida) is True


def test_is_active_false_when_fecha_final_is_set() -> None:
    row = _row({"fecha_final": "2026-08-15"})
    acogida = acogidas_service._row_to_acogida(row)

    assert acogidas_service.is_active(acogida) is False


# --- update with FK checks revalidation -----------------------------------


def test_update_acogida_revalidates_fk() -> None:
    """update_acogida re-runs FK checks on the new values."""

    def _handler(query: str, params: list[object]) -> Any:
        # Animal check returns an inactive row → update must reject.
        if "FROM animales" in query and "WHERE id = $1" in query:
            return [_animal_row(activo=False)]
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)

    with pytest.raises(ValueError, match="animal_id"):
        acogidas_service.update_acogida(
            client, "22222222-2222-2222-2222-222222222222",
            _params_minimal(),
        )
    update_calls = [c for c in captured if "UPDATE acogidas SET" in c[0]]
    assert update_calls == []
