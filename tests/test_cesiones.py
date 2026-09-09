"""Service tests for ``app.modules.cesiones.service``.

Mirrors ``tests/test_entradas.py``-style: pure service unit tests with
``httpx.MockTransport`` so every SQL the service emits is captured and
asserted, no live LocalBackend client. Covers issue #41 (INTAKE-03) end to
end at the service layer:

- Required-field validation.
- Foreign-key validation (entrada_id must reference an existing entrada).
- Happy path that persists one cesion row and one contrato row.
- Unique-conflict (entrada_id already has a cesion) → ``CesionConflictError``.
- Lookup helpers: ``get_cesion_by_entrada_id`` (1:1, UNIQUE FK).
- Lookup helpers: ``list_cesiones`` (chronological).

The ``contrato`` row is created in the SAME path as the cesion — every
cesión carries its own type="Cesión" contract row, matching the legacy
``TbContratosAnexos`` linked via ``IDEntrada`` for ``TbCesionPorPropietario``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.core.data_access import BackendError
from app.modules.cesiones import service as cesiones_service
from tests.sql_executor_fake import HandlerSqlExecutor as LocalPostgresExecutor


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
                raise BackendError(result.status_code, result.body)
            if result is not None:
                return result  # type: ignore[no-any-return]
        if self._responses:
            return self._responses.pop(0)
        return []

    def close(self) -> None:
        pass  # no-op for fake


def _build_handler(
    *,
    entradas_row: dict[str, Any] | None = None,
    tipo_contrato_row: dict[str, Any] | None = None,
    insert_cesion_rows: list[dict[str, Any]] | None = None,
    insert_contrato_rows: list[dict[str, Any]] | None = None,
    select_cesion_rows: list[dict[str, Any]] | None = None,
    list_rows: list[dict[str, Any]] | None = None,
    error_409: bool = False,
) -> Callable[[str, list[object]], Any]:
    """Build a fake handler that responds to the expected SQL.

    The captured queries are stored on ``client.calls`` (FakeSqlExecutor
    records them automatically) so tests can assert what SQL the service
    emitted.
    """
    def handler(query: str, _params: list[object]) -> Any:
        normalized = " ".join(query.split())

        if error_409 and (
            normalized.startswith("INSERT INTO cesiones_propietario")
            or normalized.startswith("INSERT INTO contratos")
        ):
            return _ErrorResponse(
                409,
                {
                    "error": "duplicate key value violates unique constraint",
                    "constraint": "cesiones_propietario_entrada_id_key",
                },
            )

        if normalized.startswith("SELECT id FROM entradas WHERE id = $1"):
            if entradas_row is None:
                return []
            return [entradas_row]

        if normalized.startswith(
            "SELECT id FROM catalogos_tipos_contrato WHERE codigo = $1"
        ):
            if tipo_contrato_row is None:
                return []
            return [tipo_contrato_row]

        if normalized.startswith("INSERT INTO cesiones_propietario"):
            return insert_cesion_rows or []

        if normalized.startswith("INSERT INTO contratos"):
            return insert_contrato_rows or []

        # SELECT ... FROM cesiones_propietario WHERE entrada_id = $1
        if (
            normalized.startswith("SELECT")
            and "FROM cesiones_propietario" in normalized
            and "WHERE entrada_id = $1" in normalized
        ):
            return select_cesion_rows or []

        # SELECT ... FROM cesiones_propietario (no WHERE entrance clause)
        if (
            normalized.startswith("SELECT")
            and "FROM cesiones_propietario" in normalized
            and "WHERE entrada_id" not in normalized
        ):
            return list_rows or []

        # Default: benign empty for anything unexpected (helps tests
        # catch missing handlers via the captured list).
        return []

    return handler


def _client(handler) -> LocalPostgresExecutor:
    return LocalPostgresExecutor(
        base_url="https://example.local_backend.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )


def _full_cesion_row(**overrides) -> dict[str, Any]:
    """A complete cesion DB row with ALL the columns ``_row_to_cesion``
    consumes. Tests that mock the INSERT response use this fixture so
    the service can round-trip the result without raising KeyError on
    a sparse mock row.
    """
    row = {
        "id": "ces-abc",
        "entrada_id": "ent-abc",
        "numero_contrato": "CP0672",
        "nombre_representante": "Maria Lopez Garcia",
        "cartilla_sanitaria": "Sí",
        "certificado_veterinario": "Sí",
        "autorizacion_recogida": "Sí",
        "fecha_vacuna_rabia": None,
        "numero_colegiado": "9999",
        "numero_colaborador": "5555",
        "dni_representante": "12345678Z",
        "calle_representante": "Calle Mayor",
        "numero_calle_representante": "1",
        "piso_representante": "2",
        "letra_representante": "A",
        "localidad_representante": "Alcala de Henares",
        "provincia_representante": "Madrid",
        "cp_representante": "28801",
        "telefono_representante": "600000000",
        "email_representante": "maria@example.com",
        "hora_cesion": None,
        "fecha_alta": "2026-07-03 00:00:00",
        "updated_at": "2026-07-03 00:00:00",
    }
    row.update(overrides)
    return row


def _full_contrato_row(**overrides) -> dict[str, Any]:
    row = {
        "id": "ctr-abc",
        "tipo_contrato_id": "tip-ces",
        "numero_contrato": "CP0672",
        "fecha": "2026-07-03",
        "cesion_id": "ces-abc",
        "fecha_alta": "2026-07-03 00:00:00",
    }
    row.update(overrides)
    return row


def _valid_params() -> dict[str, Any]:
    return {
        "entrada_id": "ent-abc",
        "numero_contrato": "CP0672",
        "nombre_representante": "Maria Lopez Garcia",
        "dni_representante": "12345678Z",
        "fecha_cesion": "2026-07-03",
        "calle_representante": "Calle Mayor",
        "numero_calle_representante": "1",
        "piso_representante": "2",
        "letra_representante": "A",
        "localidad_representante": "Alcala de Henares",
        "provincia_representante": "Madrid",
        "cp_representante": "28801",
        "telefono_representante": "600000000",
        "email_representante": "maria@example.com",
        "cartilla_sanitaria": "Sí",
        "certificado_veterinario": "Sí",
        "autorizacion_recogida": "Sí",
        "fecha_vacuna_rabia": "2026-05-15",
        "numero_colegiado": "9999",
        "numero_colaborador": "5555",
        "hora_cesion": "2026-07-03T11:30:00",
        "motivo": "Cambio de domicilio",
        "observaciones": "Llegada tranquila",
    }


# --- required-field validation -------------------------------------------


def test_create_cesion_missing_entrada_id_raises_value_error() -> None:
    client, _ = _make_client(_build_handler())

    params = _valid_params()
    params["entrada_id"] = ""

    with pytest.raises(ValueError, match="entrada_id"):
        cesiones_service.create_cesion(client, params)


def test_create_cesion_missing_numero_contrato_raises_value_error() -> None:
    client, _ = _make_client(_build_handler())

    params = _valid_params()
    params["numero_contrato"] = ""

    with pytest.raises(ValueError, match="numero_contrato"):
        cesiones_service.create_cesion(client, params)


def test_create_cesion_missing_nombre_representante_raises_value_error() -> None:
    """Product-level required field (legacy nullable but enforced on web)."""
    client, _ = _make_client(_build_handler())

    params = _valid_params()
    params["nombre_representante"] = "   "

    with pytest.raises(ValueError, match="nombre_representante"):
        cesiones_service.create_cesion(client, params)


# --- FK validation --------------------------------------------------------


def test_create_cesion_entrada_id_not_found_raises_value_error() -> None:
    """When the entrada does not exist, the service raises ValueError
    BEFORE any INSERT — the legacy FK guarantees integrity, the web
    equivalent is explicit pre-validation.
    """
    client, captured = _make_client(_build_handler(entradas_row=None))

    with pytest.raises(ValueError, match="entrada_id does not reference"):
        cesiones_service.create_cesion(client, _valid_params())

    # Only the SELECT for entradas ran; no INSERT into cesiones_propietario.
    select_queries = [
        c for c in captured if "SELECT id FROM entradas" in c[0]
    ]
    insert_queries = [
        c for c in captured if "INSERT INTO cesiones_propietario" in c[0]
    ]
    assert len(select_queries) == 1
    assert not insert_queries, (
        "create_cesion must NOT insert anything when entrada FK fails; "
        f"got captured queries: {[c[0][:60] for c in captured]}"
    )


def test_create_cesion_tipo_contrato_codigo_must_exist() -> None:
    """Without the type=Cesión catalog row, the contrato INSERT has no FK
    target. The service must short-circuit if the catalog is missing.
    """
    client, captured = _make_client(
        _build_handler(
            entradas_row={"id": "ent-abc"},
            tipo_contrato_row=None,  # catalog miss
        )
    )

    with pytest.raises(ValueError, match="catalogos_tipos_contrato"):
        cesiones_service.create_cesion(client, _valid_params())

    # The entradas SELECT succeeded; the catalog SELECT failed; no INSERT.
    select_queries = [c[0] for c in captured if c[0].lstrip().upper().startswith("SELECT")]
    assert any("FROM catalogos_tipos_contrato" in q for q in select_queries)
    insert_queries = [c[0] for c in captured if "INSERT INTO" in c[0]]
    assert not insert_queries, (
        "create_cesion must NOT insert anything when the tipo_contrato catalog miss; "
        f"got captured queries: {[c[0][:60] for c in captured]}"
    )


# --- happy path -----------------------------------------------------------


def test_create_cesion_emits_two_inserts_in_expected_order() -> None:
    """create_cesion must INSERT the cesion FIRST (to satisfy FK UNIQUE on
    entrada_id) and the contrato SECOND (cesion_id FK).
    """
    cesion_row = _full_cesion_row(id="ces-xyz")
    contrato_row = _full_contrato_row(id="ctr-abc", cesion_id="ces-xyz")
    client, captured = _make_client(
        _build_handler(
            entradas_row={"id": "ent-abc"},
            tipo_contrato_row={"id": "tip-ces"},
            insert_cesion_rows=[cesion_row],
            insert_contrato_rows=[contrato_row],
        )
    )

    cesion, contrato = cesiones_service.create_cesion(client, _valid_params())

    assert cesion.id == "ces-xyz"
    assert cesion.entrada_id == "ent-abc"
    assert cesion.numero_contrato == "CP0672"
    assert contrato.id == "ctr-abc"
    assert contrato.cesion_id == "ces-xyz"

    queries = [c[0].strip() for c in captured]
    inserts = [q for q in queries if q.startswith("INSERT INTO")]
    assert len(inserts) == 2
    assert inserts[0].startswith("INSERT INTO cesiones_propietario")
    assert inserts[1].startswith("INSERT INTO contratos"), (
        f"contrato INSERT must come AFTER cesion INSERT for FK; "
        f"got: {inserts}"
    )


def test_create_cesion_passes_full_param_set_to_insert() -> None:
    """Sanity check: every parameter the form submits is forwarded to the
    INSERT in the order the SQL template expects (defends against silent
    param-loss regressions).
    """
    cesion_row = _full_cesion_row(id="ces-1")
    contrato_row = _full_contrato_row(id="ctr-1", cesion_id="ces-1")
    client, captured = _make_client(
        _build_handler(
            entradas_row={"id": "ent-abc"},
            tipo_contrato_row={"id": "tip-ces"},
            insert_cesion_rows=[cesion_row],
            insert_contrato_rows=[contrato_row],
        )
    )

    cesiones_service.create_cesion(client, _valid_params())

    cesion_insert = next(
        c for c in captured
        if c[0].lstrip().startswith("INSERT INTO cesiones_propietario")
    )
    params = cesion_insert[1]
    # The 20 cesion columns in INSERT order — see service._INSERT_CESION_COLUMNS.
    assert len(params) >= 20, (
        f"expected at least 20 params for the full cesion form; got {len(params)}"
    )
    # Spot-check the canonical required values (entrada_id, numero_contrato,
    # nombre_representante are the first three NOT NULL columns).
    assert params[0] == "ent-abc"  # entrada_id (1st column)
    assert params[1] == "CP0672"   # numero_contrato (2nd)
    assert params[2] == "Maria Lopez Garcia"  # nombre_representante (3rd)


# --- conflict detection ---------------------------------------------------


def test_create_cesion_maps_unique_violation_to_conflict_error() -> None:
    """LocalBackend returns 409 when the UNIQUE on entrada_id is violated
    (a cesion already exists for this entrada). The service translates
    the 409 into ``CesionConflictError`` so the route layer can render a
    user-friendly form error without coupling to the LocalBackend envelope.
    """
    client, captured = _make_client(
        _build_handler(
            entradas_row={"id": "ent-abc"},
            tipo_contrato_row={"id": "tip-ces"},
            error_409=True,
        )
    )

    with pytest.raises(cesiones_service.CesionConflictError):
        cesiones_service.create_cesion(client, _valid_params())

    # Sanity: the cesion INSERT was the one that 409'd.
    assert any(
        "INSERT INTO cesiones_propietario" in c[0]
        for c in captured
    )


def test_create_cesion_propagates_unexpected_backend_errors() -> None:
    """Only duplicate-key 409s are translated to ``CesionConflictError``.
    Other LocalBackend errors (500, etc.) must propagate so the route layer
    can convert them to 5xx instead of pretending success.
    """
    def handler(query: str, _params: list[object]) -> Any:
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT id FROM entradas WHERE id = $1"):
            return [{"id": "ent-abc"}]
        if normalized.startswith("SELECT id FROM catalogos_tipos_contrato"):
            return [{"id": "tip-ces"}]
        if normalized.startswith("INSERT INTO cesiones_propietario"):
            return _ErrorResponse(500, {"error": "boom"})
        return []

    client, _ = _make_client(handler)

    with pytest.raises(BackendError):
        cesiones_service.create_cesion(client, _valid_params())


# --- get_cesion_by_entrada_id (1:1 lookup) -------------------------------


def test_get_cesion_by_entrada_id_returns_persisted_row() -> None:
    row = _full_cesion_row(id="ces-abc", numero_contrato="CP0671")
    client, _ = _make_client(_build_handler(select_cesion_rows=[row]))

    cesion = cesiones_service.get_cesion_by_entrada_id(client, "ent-abc")

    assert cesion is not None
    assert cesion.id == "ces-abc"
    assert cesion.entrada_id == "ent-abc"
    assert cesion.numero_contrato == "CP0671"


def test_get_cesion_by_entrada_id_returns_none_when_missing() -> None:
    client, _ = _make_client(_build_handler(select_cesion_rows=[]))

    cesion = cesiones_service.get_cesion_by_entrada_id(client, "ent-zzz")
    assert cesion is None


# --- list_cesiones --------------------------------------------------------
def test_list_cesiones_returns_all_rows() -> None:
    rows = [
        _full_cesion_row(id="ces-1", numero_contrato="CP0001"),
        _full_cesion_row(id="ces-2", numero_contrato="CP0002"),
    ]
    client, _ = _make_client(_build_handler(list_rows=rows))

    cesiones = cesiones_service.list_cesiones(client)
    assert [c.id for c in cesiones] == ["ces-1", "ces-2"]
    assert [c.numero_contrato for c in cesiones] == ["CP0001", "CP0002"]


# --- end-to-end + contrato creation fidelity ------------------------------


def test_create_cesion_links_contrato_to_cesion_via_cesion_id() -> None:
    """The contrato row's cesion_id column must equal the just-created
    cesion.id (P1 fidelity: contratos FK replaces the legacy
    ``TbContratosAnexos.IDEntrada`` join + manual template lookup).
    """
    cesion_row = _full_cesion_row(id="ces-link-test")
    contrato_row = _full_contrato_row(id="ctr-link-test", cesion_id="ces-link-test")
    client, captured = _make_client(
        _build_handler(
            entradas_row={"id": "ent-abc"},
            tipo_contrato_row={"id": "tip-ces"},
            insert_cesion_rows=[cesion_row],
            insert_contrato_rows=[contrato_row],
        )
    )

    cesiones_service.create_cesion(client, _valid_params())

    contrato_insert = next(
        c for c in captured
        if c[0].lstrip().startswith("INSERT INTO contratos")
    )
    params = contrato_insert[1]
    # Find cesion_id param — its position depends on the contrato columns;
    # rather than pin the index, assert that the row's cesion_id is in the
    # params (one of them must equal the just-created cesion id).
    assert "ces-link-test" in params, (
        f"contrato INSERT must carry cesion_id='ces-link-test'; got {params}"
    )
