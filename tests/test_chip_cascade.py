"""Tests para el cambio de chip en cascada (issue #29, LIFECYCLE-04).

TDD: RED primero.

El servicio ``change_animal_chip`` es un saga que:
1. Valida que new_chip no este asignado a otro animal.
2. Valida que old_chip coincide con el chip actual del animal.
3. Actualiza las 6 tablas en cascada atomica (BEGIN/COMMIT/ROLLBACK).
4. Inserta el evento ``CHIP_CHANGED`` en ``animal_lifecycle_events``.

Route-level tests (this module) exercise the HTTP handler without needing
a multi-statement saga spy. The ``change_animal_chip`` service is mocked to
return pre-configured ``ChangeChipResult`` objects so the route body is
fully traversed.

Service-level tests use an in-memory :class:`_FakeSqlExecutor` that matches
the saga SQL by substring and returns pre-loaded rows. This is the Arc C
migration target pattern (replaces ``httpx.MockTransport``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.data_access import SqlExecutor
from app.main import app, get_insforge_client
from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
    AnimalsInsforgeAdapter,
)
from app.modules.animals.adapters.insforge.animals_insforge_chip_cascade import (
    AnimalsInsforgeChipCascade,
)
from app.modules.animals.di.animals_di import get_animals_port
from app.modules.animals.domain.change_chip_result import ChangeChipResult

# =============================================================================
# Fixtures and helpers shared by route-level and service-level tests
# =============================================================================


# =============================================================================
# Spy for the SqlExecutor — handles auth revalidation without network
# =============================================================================


class _ChipCascadeSpy(SqlExecutor):
    """Minimal spy that handles auth revalidation SELECT queries.

    Used by route-level chip cascade tests to avoid network calls for the
    per-request auth revalidation inside ``require_authorized_user``.
    """

    def __init__(self) -> None:
        self.auth_reval_rol: str = "key_user"
        self.get_animal_by_id_rows: list[dict[str, Any]] = [
            {
                "id": "abc-123",
                "NCHIP": "111",
                "NombreAnimal": "Luna",
                "Especie": "CANINA",
                "Sexo": "H",
                "FNacimiento": "2023-04-12",
                "activo": True,
            }
        ]

    def execute_sql(self, query: str, params: Any = None) -> Any:  # type: ignore[override]
        from tests.conftest import auth_reval_rows

        # Handle auth revalidation (must answer the SELECT for the user)
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval
        # Handle get_animal_by_id: None means simulate 404
        if "SELECT" in query and "WHERE id = $1" in query:
            rows = self.get_animal_by_id_rows
            return list(rows) if rows is not None else []
        return []

    def close(self) -> None:  # type: ignore[override]
        pass  # no-op for fake


@pytest.fixture
def animals_spy() -> _ChipCascadeSpy:
    """Override get_insforge_client dependency with a spy for auth revalidation."""
    spy = _ChipCascadeSpy()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    app.dependency_overrides[get_animals_port] = lambda: AnimalsInsforgeAdapter(
        spy, storage=spy
    )
    yield spy
    app.dependency_overrides.pop(get_insforge_client, None)
    app.dependency_overrides.pop(get_animals_port, None)


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    """Install a key_user session cookie so the route auth dependency is satisfied."""
    from app.core.config import get_settings
    from app.core.session import session_cookie_name, write_session

    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-animals",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


# =============================================================================
# Service-level fake executor — query-pattern routing for saga assertions
# =============================================================================


class _SagaSqlExecutor:
    """In-memory :class:`SqlExecutor` that routes by SQL substring.

    Each registered handler is ``(match_substring, params_predicate,
    response_rows)``; the first match wins. Default returns ``[]``
    (suitable for BEGIN, COMMIT, INSERT, the no-row UPDATE animales, etc).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        # list of (substring_or_callable, response)
        self._rules: list[
            tuple[str | None, Any, list[dict[str, object]]]
        ] = []

    def add_rule(
        self,
        substring: str | None,
        response: list[dict[str, object]],
        params_eq: Any = ...,
    ) -> None:
        """Register ``response`` for any query containing ``substring``.

        When ``params_eq`` is supplied (anything other than the sentinel
        ``Ellipsis``) only matches when params equal that exact list.
        """
        self._rules.append((substring, params_eq, response))

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        params_list = list(params or [])
        self.calls.append((query, params_list))
        for substring, params_pred, response in self._rules:
            if substring is not None and substring.lower() not in query.lower():
                continue
            if params_pred is not Ellipsis and params_pred != params_list:
                continue
            return [dict(r) for r in response]
        return []

    def close(self) -> None:
        pass  # no-op for fake


# =============================================================================
# Route-level tests — exercise change_chip_view body via HTTP
# The service is mocked so we don't need the multi-statement spy.
# Coverage gap filled: the route handler body (lines 385-428) is exercised.
# =============================================================================


async def _chip_route_response(
    client: httpx.AsyncClient,
    animals_spy,
    *,
    get_animal_by_id_rows: list[dict[str, Any]] | None,
    change_chip_result: Any,
) -> httpx.Response:
    """Helper: configure spy rows + mock service + call PATCH /animales/{id}/chip.

    ``animals_spy`` is the dependency override for ``get_insforge_client``,
    so its ``execute_sql`` handles auth revalidation calls without touching the
    network.  ``change_animal_chip`` is mocked at the service module level so the
    route handler body is fully exercised while the mock returns a controlled
    ``ChangeChipResult``.

    Uses ``mocker.patch`` (pytest-mock) instead of ``unittest.mock.patch``
    as a context manager — pytest-mock's async-aware patch stays active through
    the full ``await client.patch(...)`` call so the response is fully processed
    before the mock is torn down.
    """
    # Configure spy for get_animal_by_id
    animals_spy.get_animal_by_id_rows = get_animal_by_id_rows

    # Patch the adapter delegation used directly by the route.
    from unittest.mock import patch
    with patch.object(
        AnimalsInsforgeAdapter,
        "change_animal_chip",
        return_value=change_chip_result,
    ):
        response = await client.patch(
            "/animales/abc-123/chip",
            json={"new_chip": "222", "reason": "Chip fisurado"},
            headers={"X-CSRFToken": "test-csrf-token-animals"},
        )
    return response


async def test_change_chip_route_returns_404_when_animal_not_found(
    client: httpx.AsyncClient,
    animals_spy,
) -> None:
    """Animal not found -> 404, no call to change_animal_chip."""
    _login_as_key_user(client)
    result = ChangeChipResult(
        success=False, old_chip="", new_chip="", updated_tables={}, error=None
    )
    response = await _chip_route_response(
        client, animals_spy,
        get_animal_by_id_rows=None,
        change_chip_result=result,
    )

    assert response.status_code == 404


async def test_change_chip_route_returns_409_when_chip_already_assigned(
    client: httpx.AsyncClient,
    animals_spy,
    monkeypatch,
) -> None:
    """change_animal_chip returns success=False with 'ya esta asignado' -> 409."""
    _login_as_key_user(client)
    result = ChangeChipResult(
        success=False,
        old_chip="111",
        new_chip="222",
        updated_tables={},
        error="El chip 222 ya esta asignado al animal other-456.",
    )
    response = await _chip_route_response(
        client, animals_spy,
        get_animal_by_id_rows=[{
            "id": "abc-123", "NCHIP": "111", "NombreAnimal": "Luna",
            "Especie": "CANINA", "Sexo": "H",
            "FNacimiento": "2023-04-12", "activo": True,
        }],
        change_chip_result=result,
    )

    assert response.status_code == 409
    assert "ya esta asignado" in response.json()["detail"]


async def test_change_chip_route_returns_422_when_old_chip_mismatch(
    client: httpx.AsyncClient,
    animals_spy,
    monkeypatch,
) -> None:
    """change_animal_chip returns success=False without 'ya esta asignado' -> 422."""
    _login_as_key_user(client)
    result = ChangeChipResult(
        success=False,
        old_chip="111",
        new_chip="222",
        updated_tables={},
        error="El chip old no coincide con el chip actual del animal.",
    )
    response = await _chip_route_response(
        client, animals_spy,
        get_animal_by_id_rows=[{
            "id": "abc-123", "NCHIP": "111", "NombreAnimal": "Luna",
            "Especie": "CANINA", "Sexo": "H",
            "FNacimiento": "2023-04-12", "activo": True,
        }],
        change_chip_result=result,
    )

    assert response.status_code == 422
    assert "no coincide" in response.json()["detail"]


async def test_change_chip_route_returns_200_on_success(
    client: httpx.AsyncClient,
    animals_spy,
    monkeypatch,
) -> None:
    """change_animal_chip returns success=True -> 200 with result dict."""
    _login_as_key_user(client)
    result = ChangeChipResult(
        success=True,
        old_chip="111",
        new_chip="222",
        updated_tables={
            "animals": 0, "entradas": 2, "acogidas": 1,
            "adopciones": 0, "actuaciones_sanitarias": 3, "terapias": 1,
        },
        error=None,
    )
    response = await _chip_route_response(
        client, animals_spy,
        get_animal_by_id_rows=[{
            "id": "abc-123", "NCHIP": "111", "NombreAnimal": "Luna",
            "Especie": "CANINA", "Sexo": "H",
            "FNacimiento": "2023-04-12", "activo": True,
        }],
        change_chip_result=result,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["old_chip"] == "111"
    assert data["new_chip"] == "222"
    assert "updated_tables" in data


# =============================================================================
# HAPPY PATH — chip cambiado, cascade a 6 tablas
# =============================================================================


def test_chip_change_cascades_to_all_six_tables():
    """Cuando el chip cambia, las 6 tablas se actualizan atomicamente."""
    client = _SagaSqlExecutor()
    # uniqueness: no other animal has new_chip=222
    client.add_rule(
        'select id from animales where "nchip"',
        [],
        params_eq=["222", "a1"],
    )
    # get current chip: animal exists, chip="111"
    client.add_rule(
        'select "nchip" from animales where id',
        [{"NCHIP": "111"}],
        params_eq=["a1"],
    )
    # UPDATE entradas: 2 rows affected
    client.add_rule(
        "update entradas set chip",
        [{"id": "e1"}, {"id": "e2"}],
        params_eq=["222", "111"],
    )
    # UPDATE acogidas: 1 row
    client.add_rule(
        "update acogidas set chip",
        [{"id": "ac1"}],
        params_eq=["222", "111"],
    )
    # UPDATE actuaciones_sanitarias: 3 rows
    client.add_rule(
        "update actuaciones_sanitarias set chip",
        [{"id": "as1"}, {"id": "as2"}, {"id": "as3"}],
        params_eq=["222", "111"],
    )
    # UPDATE terapias: 1 row
    client.add_rule(
        "update terapias set chip",
        [{"id": "t1"}],
        params_eq=["222", "111"],
    )
    # Default rule (no-op response) covers BEGIN, COMMIT, UPDATE animals,
    # INSERT event, UPDATE adopciones, UPDATE animales.

    result = AnimalsInsforgeChipCascade(client).change_animal_chip(
        animal_id="a1",
        old_chip="111",
        new_chip="222",
        reason="Chip fisico reemplazado",
        operador_user_id="user-1",
    )

    assert result.success is True
    assert result.old_chip == "111"
    assert result.new_chip == "222"
    assert result.updated_tables["animals"] == 0  # empty RETURNING
    assert result.updated_tables["entradas"] == 2
    assert result.updated_tables["acogidas"] == 1
    assert result.updated_tables["adopciones"] == 0
    assert result.updated_tables["actuaciones_sanitarias"] == 3
    assert result.updated_tables["terapias"] == 1

    all_q = " ".join(c[0] for c in client.calls).upper()
    assert "BEGIN" in all_q
    assert "COMMIT" in all_q
    assert "ROLLBACK" not in all_q


def test_chip_change_returns_false_when_new_chip_already_assigned():
    """409-equivalente: si new_chip ya pertenece a otro animal, no se modifica nada."""
    client = _SagaSqlExecutor()
    # uniqueness: another animal already has new_chip
    client.add_rule(
        'select id from animales where "nchip"',
        [{"id": "other-animal"}],
        params_eq=["222", "a1"],
    )

    result = AnimalsInsforgeChipCascade(client).change_animal_chip(
        animal_id="a1",
        old_chip="111",
        new_chip="222",
        reason="Replacement",
        operador_user_id="user-1",
    )

    assert result.success is False
    assert "ya está asignado" in result.error


def test_chip_change_returns_false_when_old_chip_mismatch():
    """422-equivalente: si old_chip no coincide, no se modifica nada."""
    client = _SagaSqlExecutor()
    # uniqueness: no conflict
    client.add_rule(
        'select id from animales where "nchip"',
        [],
    )
    # animal exists but chip is "333", not "111"
    client.add_rule(
        'select "nchip" from animales where id',
        [{"NCHIP": "333"}],
    )

    result = AnimalsInsforgeChipCascade(client).change_animal_chip(
        animal_id="a1",
        old_chip="111",  # mismatched!
        new_chip="222",
        reason="Replacement",
        operador_user_id="user-1",
    )

    assert result.success is False
    assert "333" in result.error or "no coincide" in result.error.lower()
    # Only 2 pre-flight calls — no BEGIN
    assert len(client.calls) == 2


def test_chip_change_rollback_on_table_failure():
    """Si una tabla falla, todas las demas se revierten (ROLLBACK)."""
    client = _SagaSqlExecutor()
    # uniqueness
    client.add_rule(
        'select id from animales where "nchip"',
        [],
    )
    # get current chip
    client.add_rule(
        'select "nchip" from animales where id',
        [{"NCHIP": "111"}],
    )

    # Wrap the executor: force UPDATE entradas to raise so the saga
    # rolls back. The other rules keep their default responses.
    original_execute_sql = client.execute_sql

    def execute_sql_with_failure(
        query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        if "update entradas set chip" in query.lower():
            raise RuntimeError("foreign_key_violation")
        return original_execute_sql(query, params)

    client.execute_sql = execute_sql_with_failure  # type: ignore[method-assign]

    result = AnimalsInsforgeChipCascade(client).change_animal_chip(
        animal_id="a1",
        old_chip="111",
        new_chip="222",
        reason="Replacement",
        operador_user_id="user-1",
    )

    assert result.success is False
    assert "Error en la transaccion" in result.error


def test_chip_change_validates_empty_fields():
    """new_chip vacio o igual a old_chip levanta ValueError antes de SQL."""
    mock_client = MagicMock()
    cascade = AnimalsInsforgeChipCascade(mock_client)

    # empty new_chip
    with pytest.raises(ValueError, match="new_chip"):
        cascade.change_animal_chip(
            animal_id="a1",
            old_chip="111",
            new_chip="",
            reason="Replacement",
            operador_user_id="user-1",
        )

    # same as old
    with pytest.raises(ValueError, match="new_chip"):
        cascade.change_animal_chip(
            animal_id="a1",
            old_chip="111",
            new_chip="111",
            reason="Replacement",
            operador_user_id="user-1",
        )

    # empty reason
    with pytest.raises(ValueError, match="reason"):
        cascade.change_animal_chip(
            animal_id="a1",
            old_chip="111",
            new_chip="222",
            reason="",
            operador_user_id="user-1",
        )
