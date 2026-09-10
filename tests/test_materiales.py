"""Service-layer tests for FOSTER-04 materiales catalog + junction.

The ``materiales.service`` module owns:

- create / list / get / update / soft-delete of ``materiales`` (catalog)
- create / list / remove of ``estancia_materiales`` junction rows
- validation: required text fields (material / tamano / color), FK checks
  on assignment (estancia activa AND sin fecha_final, material activo)
- atomic cascade: ``deactivate_material`` soft-deletes the catalog row
  AND every active junction row pointing at it

Mirror of the ``tests/test_foster.py`` and ``tests/test_acogidas.py``
patterns: real LocalPostgresExecutor + httpx.MockTransport so we exercise the
SQL strings, params, and response parsing without hitting the network.

FOSTER-04 (#46) PR A — only the service layer is tested here. Routes
land in PR B; the per-stay material list endpoint lands in PR C.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.modules.materiales import estancia_material_service
from app.modules.materiales import service as materiales_service


class _ErrorResponse:
    """Marker returned by a fake handler to signal a backend error."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for unit tests."""

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
                from app.core.data_access import BackendError

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
    fake = _FakeSqlExecutor()
    fake.set_handler(handler)
    return fake, fake.calls


# --- helpers --------------------------------------------------------------

def _params_minimal() -> dict[str, Any]:
    """Minimal valid params for create_material."""
    return {
        "material": "Cama",
        "tamano": "Grande",
        "color": "Azul",
        "observaciones": "Para gato grande",
    }


def _material_row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "material": "Cama",
        "tamano": "Grande",
        "color": "Azul",
        "observaciones": "Para gato grande",
        "activo": True,
        "fecha_alta": "2026-07-05T10:00:00Z",
        "updated_at": "2026-07-05T10:00:00Z",
        "fecha_baja": None,
    }
    if overrides:
        row.update(overrides)
    return row


def _estancia_row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """An active, open (fecha_final IS NULL) estancia de acogida row."""
    row: dict[str, Any] = {
        "id": "22222222-2222-2222-2222-222222222222",
        "activo": True,
        "fecha_final": None,
    }
    if overrides:
        row.update(overrides)
    return row


def _junction_row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "33333333-3333-3333-3333-333333333333",
        "estancia_id": "22222222-2222-2222-2222-222222222222",
        "material_id": "11111111-1111-1111-1111-111111111111",
        "cantidad": 1,
        "notas": None,
        "fecha_alta": "2026-07-05T10:00:00Z",
        "activo": True,
    }
    if overrides:
        row.update(overrides)
    return row


# --- create: happy path ---------------------------------------------------


def test_create_material_happy_path() -> None:
    """create_material inserts a row with all 4 user-supplied fields +
    the system defaults and returns the persisted Material dataclass."""
    client, captured = _make_client(lambda q, p: [_material_row()])

    result = materiales_service.create_material(client, _params_minimal())

    assert isinstance(result, materiales_service.Material)
    assert result.id == "11111111-1111-1111-1111-111111111111"
    assert result.material == "Cama"
    assert result.tamano == "Grande"
    assert result.color == "Azul"
    assert result.observaciones == "Para gato grande"
    assert result.activo is True
    assert result.fecha_alta == "2026-07-05T10:00:00Z"
    assert result.fecha_baja is None

    assert len(captured) == 1
    insert = captured[0]
    assert "INSERT INTO materiales" in insert[0]
    # Required-text fields are the first 3 params, observaciones last.
    assert insert[1][:4] == ["Cama", "Grande", "Azul", "Para gato grande"]


# --- create: required-field validation ------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("material", ""),
        ("material", "   "),
        ("material", None),
        ("tamano", ""),
        ("tamano", "   "),
        ("color", ""),
        ("color", None),
    ],
)
def test_create_material_rejects_blank_material_tamano_or_color(
    field: str, value: Any
) -> None:
    """material / tamano / color are required and non-empty after .strip().

    Each rejection raises ValueError BEFORE any SQL is executed (the
    captured list stays empty) so a typo in the form path cannot leave
    a half-written row.
    """
    client, captured = _make_client(lambda q, p: [_material_row()])

    with pytest.raises(ValueError, match=field):
        materiales_service.create_material(
            client, {**_params_minimal(), field: value}
        )

    assert captured == [], (
        f"validation must reject blank {field!r} BEFORE SQL; "
        f"got captured SQL: {captured!r}"
    )


def test_create_material_rejects_blank_observaciones() -> None:
    """observaciones is OPTIONAL — blank string is normalized to None
    and the row is inserted with observaciones = NULL.
    """
    client, captured = _make_client(
        lambda q, p: [_material_row({"observaciones": None})]
    )

    result = materiales_service.create_material(
        client, {**_params_minimal(), "observaciones": ""}
    )

    assert result.observaciones is None
    # None → NULL parameter in the INSERT.
    assert captured[0][1][3] is None


# --- create: UNIQUE-violation -> MaterialConflictError (race-condition 409)


def test_create_material_unique_constraint_raises_conflict() -> None:
    """When the DB rejects a duplicate ``(material, tamano, color)``
    active row with PostgreSQL 23505, the service translates the
    BackendError into MaterialConflictError so the route can map it
    to HTTP 409. This is the race-condition path (two writers submitting
    the same triple simultaneously) — Scenario 2 in spec #15894.
    """
    def _handler(query: str, params: list[object]) -> Any:
        return _ErrorResponse(
            409,
            {
                "code": "23505",
                "message": 'duplicate key value violates unique constraint "materiales_material_tamano_color_key"',
            },
        )

    client, _captured = _make_client(_handler)

    with pytest.raises(materiales_service.MaterialConflictError, match="combinaci"):
        materiales_service.create_material(client, _params_minimal())


# --- get by id ------------------------------------------------------------


def test_get_material_by_id_returns_row_or_none() -> None:
    """get_material_by_id returns the Material dataclass when the row
    exists, or None when it does not."""
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if params == ["missing"]:
            return []
        return [_material_row({"id": params[0]})]

    client, captured = _make_client(_handler)
    found = materiales_service.get_material_by_id(client, "found")
    missing = materiales_service.get_material_by_id(client, "missing")

    assert found is not None and found.id == "found"
    assert missing is None
    assert [call[1] for call in captured] == [["found"], ["missing"]]


# --- list -----------------------------------------------------------------


def test_list_materials_returns_all_ordered() -> None:
    """list_materials(activos_solo=False) returns every row (active +
    inactive) ordered by fecha_alta DESC — the detail audit view.
    """
    rows = [
        _material_row({"id": "mat-2", "fecha_alta": "2026-07-05T12:00:00Z"}),
        _material_row({"id": "mat-1", "fecha_alta": "2026-07-05T10:00:00Z"}),
        _material_row(
            {"id": "mat-3", "fecha_alta": "2026-07-04T10:00:00Z", "activo": False}
        ),
    ]
    client, captured = _make_client(lambda q, p: rows)

    result = materiales_service.list_materials(client, activos_solo=False)

    assert [m.id for m in result] == ["mat-2", "mat-1", "mat-3"]
    query = captured[0][0]
    assert "FROM materiales" in query
    assert "ORDER BY fecha_alta DESC" in query
    # No active filter — the inactive row must show up.
    assert "WHERE activo = true" not in query


def test_list_materials_activos_solo_filter() -> None:
    """list_materials(activos_solo=True) — the default — emits
    ``WHERE activo = true`` so the inactive rows are filtered out.
    """
    client, captured = _make_client(lambda q, p: [_material_row()])

    materiales_service.list_materials(client)  # default activos_solo=True

    query = captured[0][0]
    assert "FROM materiales" in query
    assert "WHERE activo = true" in query
    assert "ORDER BY fecha_alta DESC" in query


# --- update ---------------------------------------------------------------


def test_update_material_modifies_record() -> None:
    """update_material writes the new text fields + bumps updated_at."""
    client, captured = _make_client(lambda q, p: [_material_row({"color": "Verde"})])

    result = materiales_service.update_material(
        client,
        "11111111-1111-1111-1111-111111111111",
        {**_params_minimal(), "color": "Verde"},
    )

    assert result is not None
    assert result.color == "Verde"
    update_call = captured[0]
    assert "UPDATE materiales SET" in update_call[0]
    assert "updated_at = now()" in update_call[0]
    assert update_call[1][0] == "11111111-1111-1111-1111-111111111111"


def test_update_material_returns_none_when_id_missing() -> None:
    """update_material returns None when the UPDATE matches no row."""
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "UPDATE materiales SET" in query:
            return []
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    result = materiales_service.update_material(
        client, "missing", _params_minimal()
    )

    assert result is None


# --- soft delete + cascade -----------------------------------------------


def test_deactivate_material_soft_deletes_and_cascades_junction() -> None:
    """deactivate_material emits the catalog UPDATE (activo=false +
    fecha_baja=now()) AND the junction cascade UPDATE in one
    transactional sequence (Scenario 6 in spec #15894).

    The cascade UPDATE flips ``estancia_materiales.activo = false``
    for every row pointing at the deactivated material so it stops
    showing up in any estancia's material list.
    """
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        # Multi-line SQL — substring matches must avoid the
        # ``UPDATE materiales``/``SET`` newline boundary.
        if "UPDATE materiales" in query and "activo = false" in query:
            return [{"id": params[0]}]
        if "UPDATE estancia_materiales" in query and "activo = false" in query:
            return [{"id": "junction-1"}, {"id": "junction-2"}]
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    result = materiales_service.deactivate_material(
        client, "11111111-1111-1111-1111-111111111111"
    )

    assert result is True
    assert len(captured) == 2
    catalog_call, cascade_call = captured
    # Catalog UPDATE — soft-delete the material row.
    assert "UPDATE materiales" in catalog_call[0]
    assert "activo = false" in catalog_call[0]
    assert "fecha_baja = now()" in catalog_call[0]
    # Junction cascade UPDATE — soft-delete every active junction for this material.
    assert "UPDATE estancia_materiales" in cascade_call[0]
    assert "activo = false" in cascade_call[0]
    # The cascade targets the same material_id.
    assert cascade_call[1][0] == "11111111-1111-1111-1111-111111111111"


def test_deactivate_material_returns_false_when_id_missing() -> None:
    """deactivate_material returns False when no row matches (id
    doesn't exist OR was already inactive).
    """
    client, captured = _make_client(lambda q, p: [])
    result = materiales_service.deactivate_material(client, "missing")

    assert result is False
    assert len(captured) == 1


def test_deactivate_material_returns_false_when_already_inactive() -> None:
    """Refs jd-judge-a WARNING #2 on PR #166: explicitly distinguish
    "id doesn't exist" from "id exists but activo=false". The current
    UPDATE only matches `activo = true`, so an already-inactive row
    returns no rows. The cascade SQL is NOT emitted (it was contingent
    on the catalog UPDATE having a positive RETURNING count).
    """
    client, captured = _make_client(lambda q, p: [])
    result = materiales_service.deactivate_material(
        client, "already-inactive-uuid"
    )

    assert result is False
    # Only the catalog UPDATE was emitted; the cascade was NOT
    # because the catalog UPDATE returned 0 rows (already inactive).
    assert len(captured) == 1
    assert "_CASCADE" not in captured[0][0]


def test_assign_material_to_estancia_concurrent_race_returns_conflict() -> None:
    """Refs jd-judge-b CRITICAL #1 on PR #166: two concurrent operators
    racing to assign the same material to the same estancia produce a
    PostgreSQL 23505 unique violation, which the service translates to
    MaterialConflictError. This atom simulates the race end-to-end by
    having the mocked LocalBackend return 409 with the canonical conflict
    body on the junction INSERT.
    """
    def _handler(query: str, params: list[object]) -> Any:
        # FK checks for estancia + material (each SELECT returns a row).
        if "FROM acogidas" in query:
            return [_estancia_row()]
        if "FROM materiales" in query:
            return [_material_row()]
        # The junction INSERT collides with the partial unique index.
        if "INSERT INTO estancia_materiales" in query:
            return _ErrorResponse(
                409,
                {
                    "code": "23505",
                    "message": 'duplicate key value violates unique constraint "estancia_materiales_active_unique"',
                },
            )
        return []

    client, _captured = _make_client(_handler)
    with pytest.raises(materiales_service.MaterialConflictError) as exc_info:
        estancia_material_service.assign_material_to_estancia(
            client,
            estancia_id="22222222-2222-2222-2222-222222222222",
            material_id="11111111-1111-1111-1111-111111111111",
            cantidad=1,
        )

    assert isinstance(exc_info.value, materiales_service.MaterialConflictError)
    # The service's translated message names the offending resource
    # in Spanish; we only assert the type, not the literal string.
    assert str(exc_info.value)


# --- junction: assign -----------------------------------------------------


def test_assign_material_to_estancia_happy_path() -> None:
    """assign_material_to_estancia validates the estancia is active AND
    sin fecha_final AND the material is active, then inserts the
    junction row. The returned EstanciaMaterial dataclass carries the
    persisted id + timestamp.
    """
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        # FK checks for estancia + material (each SELECT returns a row).
        # The service does the activo + fecha_final check in Python so
        # the SQL is just an existence query.
        if "FROM acogidas" in query:
            return [_estancia_row()]
        if "FROM materiales" in query:
            return [_material_row()]
        if "INSERT INTO estancia_materiales" in query:
            # Return the junction row with the cantidad + notas echoed
            # back from the INSERT params so the dataclass assertions
            # match the actual request.
            return [
                _junction_row(
                    {"cantidad": params[2], "notas": params[3]}
                )
            ]
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    result = estancia_material_service.assign_material_to_estancia(
        client,
        estancia_id="22222222-2222-2222-2222-222222222222",
        material_id="11111111-1111-1111-1111-111111111111",
        cantidad=2,
        notas="Para el gato nuevo",
    )

    assert isinstance(result, materiales_service.EstanciaMaterial)
    assert result.estancia_id == "22222222-2222-2222-2222-222222222222"
    assert result.material_id == "11111111-1111-1111-1111-111111111111"
    assert result.cantidad == 2
    assert result.notas == "Para el gato nuevo"
    assert result.activo is True
    # Three SQL calls: FK check on estancia, FK check on material, INSERT.
    assert len(captured) == 3
    insert = captured[2]
    assert "INSERT INTO estancia_materiales" in insert[0]
    assert insert[1][:3] == [
        "22222222-2222-2222-2222-222222222222",
        "11111111-1111-1111-1111-111111111111",
        2,
    ]


def test_assign_material_to_estancia_rejects_inactive_material() -> None:
    """If the material is activo=false (soft-deleted), raise ValueError
    BEFORE the INSERT. Scenario 8 in spec #15894.

    The estancia FK check runs FIRST in ``assign_material_to_estancia``,
    so this test mocks both the estancia check (returns a healthy row)
    AND the material check (returns an inactive row). The validator
    chain stops at the material step with ValueError before the INSERT.
    """
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "FROM acogidas" in query:
            # Estancia is healthy — pass the FK check.
            return [_estancia_row()]
        if "FROM materiales" in query:
            # Material is soft-deleted — must reject.
            return [_material_row({"activo": False})]
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    with pytest.raises(ValueError, match=r"material.*activo.*inactivo"):
        estancia_material_service.assign_material_to_estancia(
            client,
            estancia_id="22222222-2222-2222-2222-222222222222",
            material_id="11111111-1111-1111-1111-111111111111",
        )

    # Two SQL calls: estancia FK check (passed) + material FK check (rejected).
    # No INSERT runs.
    assert len(captured) == 2


def test_assign_material_to_estancia_rejects_closed_or_soft_deleted_estancia() -> None:
    """If the estancia is activo=false OR fecha_final IS NOT NULL
    (i.e. closed), raise ValueError BEFORE the INSERT. Q5 in spec
    #15894 + data-model-completeness.md §4 invariant.
    """
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "FROM acogidas" in query:
            # Simulate a closed (fecha_final populated) AND soft-deleted
            # estancia — either condition must reject.
            return []
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    with pytest.raises(ValueError, match="estancia"):
        estancia_material_service.assign_material_to_estancia(
            client,
            estancia_id="closed-estancia",
            material_id="11111111-1111-1111-1111-111111111111",
        )

    # Only the estancia FK check ran; no material check, no INSERT.
    assert len(captured) == 1


# --- junction: list -------------------------------------------------------


def test_list_materials_for_estancia_returns_active_only() -> None:
    """list_materials_for_estancia(activos_solo=True) — the default —
    returns ONLY the active junction rows ordered by fecha_alta DESC
    (Scenario 5 in spec #15894). The SELECT must include an active
    filter and the date-ordering clause.
    """
    rows = [
        _junction_row({"id": "jun-2", "fecha_alta": "2026-07-05T12:00:00Z"}),
        _junction_row({"id": "jun-1", "fecha_alta": "2026-07-05T10:00:00Z"}),
    ]
    client, captured = _make_client(lambda q, p: rows)

    result = estancia_material_service.list_materials_for_estancia(
        client, "22222222-2222-2222-2222-222222222222"
    )

    assert [j.id for j in result] == ["jun-2", "jun-1"]
    query = captured[0][0]
    assert "FROM estancia_materiales" in query
    assert "WHERE estancia_id = $1" in query
    assert "activo = true" in query
    assert "ORDER BY fecha_alta DESC" in query


# --- junction: remove (soft-delete) ---------------------------------------


def test_remove_material_from_estancia_soft_deletes() -> None:
    """remove_material_from_estancia soft-deletes the junction row
    (Scenario 11 / AC8 in spec #15894): activo=false on the row, NOT
    a physical DELETE.
    """
    client, captured = _make_client(lambda q, p: [{"id": p[0]}] if p else [{"id": "x"}])
    result = estancia_material_service.remove_material_from_estancia(
        client, "33333333-3333-3333-3333-333333333333"
    )

    assert result is True
    query = captured[0][0]
    # Multi-line SQL — substring avoids the
    # ``UPDATE estancia_materiales``/``SET`` newline boundary.
    assert "UPDATE estancia_materiales" in query
    assert "activo = false" in query
    assert "WHERE id = $1" in query
    assert "activo = true" in query
    assert "DELETE FROM" not in query


def test_remove_material_from_estancia_returns_false_when_id_missing() -> None:
    """remove_material_from_estancia returns False when the row does
    not exist OR was already inactive (idempotent — same shape as
    deactivate_material on the catalog).
    """
    client, captured = _make_client(lambda q, p: [])
    result = estancia_material_service.remove_material_from_estancia(
        client, "missing"
    )

    assert result is False
    assert len(captured) == 1


# --- junction: cascade ---------------------------------------------------


def test_cascade_deactivate_by_material_soft_deletes_all_assignments() -> None:
    """The cascade UPDATE emitted by deactivate_material flips every
    active junction row for the deactivated material in a single
    statement — confirmed by the WHERE material_id = $1 filter
    targeting the catalog id.
    """
    def _handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "UPDATE materiales" in query and "activo = false" in query:
            return [{"id": params[0]}]
        if "UPDATE estancia_materiales" in query and "activo = false" in query:
            # Return 3 affected junction rows — proves the WHERE filter
            # catches multiple assignments (same material, different
            # estancias).
            return [
                {"id": "j-1"},
                {"id": "j-2"},
                {"id": "j-3"},
            ]
        raise AssertionError(f"Unexpected SQL: {query}")

    client, captured = _make_client(_handler)
    result = materiales_service.deactivate_material(
        client, "11111111-1111-1111-1111-111111111111"
    )

    assert result is True
    assert len(captured) == 2
    cascade_call = captured[1]
    # WHERE material_id = $1 — the cascade targets ONLY rows for this material.
    assert "WHERE material_id = $1" in cascade_call[0]
    assert "activo = true" in cascade_call[0]
    # The cascade also filters by activo=true so soft-deleted junction
    # rows are not re-touched.
    assert cascade_call[1][0] == "11111111-1111-1111-1111-111111111111"
