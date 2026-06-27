"""Route-level tests for the voluntarios deactivate endpoint
(Slice 7, hardening-2026-q2 — TOCTOU fix).

Covers REQ-1 (single SQL, no SELECT previo redundante) and REQ-2
(404 when the row does not exist OR was already inactive) from
``openspec/changes/hardening-2026-q2/specs/07-toctou-fix/spec.md``.

The concurrent case (REQ-3) lives in
``tests/test_voluntarios_concurrent.py`` because it requires a real
PostgreSQL row lock to exercise faithfully.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client


class _VoluntariosRouteSpy(InsForgeClient):
    """``InsForgeClient`` spy para el route ``deactivate_voluntario_view``.

    ``execute_sql`` no toca la red: matchea el SQL contra la unica
    sentencia esperada (``UPDATE voluntarios SET activo = false``) y
    devuelve las filas configuradas. Tests pueden mutar
    ``deactivate_returning_rows`` para simular los distintos estados
    de la fila (activa vs ya inactiva vs inexistente).

    Captures ``captured_queries`` para que los tests verifiquen que
    el handler emite EXACTAMENTE los SQLs esperados. La pista clave
    es: el deactivate handler NO debe emitir un SELECT previo
    (regresion del patron TOCTOU que esta PR cierra).
    """

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        self.captured_queries: list[str] = []
        self.captured_params: list[Any] = []
        # Default: primer deactivate tiene exito (devuelve una fila).
        # Los tests mutan esta lista para simular el caso "ya estaba
        # inactiva" (lista vacia) o "no existe" (lista vacia).
        self.deactivate_returning_rows: list[dict[str, Any]] = [
            {"id": "v-1"}
        ]
        # Contador de invocaciones: usado para alternar el retorno entre
        # llamadas y simular el caso "doble deactivate concurrente".
        self.call_count = 0
        # Si se configura, los returns se rotan segun el call_count.
        # Por ejemplo: ``rotating_rows = [[{"id": "v-1"}], []]``
        # produce True en la primera llamada y False en la segunda.
        self.rotating_rows: list[list[dict[str, Any]]] | None = None

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
        self.captured_queries.append(query)
        self.captured_params.append(params)
        # Solo nos interesa la sentencia del deactivate (la unica
        # UPDATE contra ``voluntarios SET activo = false``).
        if "UPDATE voluntarios" in query and "SET activo = false" in query:
            if self.rotating_rows is not None:
                idx = min(self.call_count, len(self.rotating_rows) - 1)
                self.call_count += 1
                return list(self.rotating_rows[idx])
            return list(self.deactivate_returning_rows)
        # Cualquier otra SELECT (ej. ``get_voluntario_by_id`` que ya
        # NO deberia aparecer en el deactivate handler) se ignora.
        return []


@pytest.fixture
def voluntarios_spy() -> _VoluntariosRouteSpy:
    spy = _VoluntariosRouteSpy()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_insforge_client, None)


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    """Any authorized user can hit ``/voluntarios/{id}/deactivate``."""
    from app.core.config import get_settings

    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


# --- REQ-1: handler invoca exactamente una SQL ----------------------------


async def test_deactivate_routes_invoca_execute_sql_una_vez(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosRouteSpy,
) -> None:
    """POST ``/voluntarios/{id}/deactivate`` emite UN solo ``execute_sql``.

    Regresion guard contra el patron anterior (SELECT previo + UPDATE).
    El handler DEBE delegar en ``voluntarios_service.deactivate_voluntario``
    y NO emitir una ``get_voluntario_by_id`` previa.
    """
    _login_as_key_user(client)

    response = await client.post(
        "/voluntarios/v-1/deactivate", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/voluntarios"

    # Exactamente UNA llamada a execute_sql (sin SELECT previo).
    update_queries = [
        q
        for q in voluntarios_spy.captured_queries
        if "UPDATE voluntarios" in q and "SET activo = false" in q
    ]
    select_queries = [
        q for q in voluntarios_spy.captured_queries if "SELECT" in q
    ]
    assert len(update_queries) == 1, (
        "se esperaba UN UPDATE via service; "
        f"se emitieron: {voluntarios_spy.captured_queries!r}"
    )
    assert len(select_queries) == 0, (
        "el handler NO debe emitir SELECT previo al UPDATE "
        "(eso era el patron TOCTOU que esta PR cierra); "
        f"se emitieron: {select_queries!r}"
    )


# --- REQ-2: 404 cuando la fila no existe o ya estaba inactiva ------------


async def test_deactivate_routes_404_on_second_call(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosRouteSpy,
) -> None:
    """El segundo POST contra el mismo id retorna 404 (la fila ya esta inactiva).

    Simula el camino real: el primer POST desactiva la fila, el
    segundo la encuentra con ``activo = false`` y el ``WHERE activo = true``
    no matchea. El servicio devuelve ``False`` y el handler responde 404.
    """
    voluntarios_spy.rotating_rows = [[{"id": "v-1"}], []]
    _login_as_key_user(client)

    first = await client.post(
        "/voluntarios/v-1/deactivate", follow_redirects=False
    )
    second = await client.post(
        "/voluntarios/v-1/deactivate", follow_redirects=False
    )

    assert first.status_code == 303
    assert first.headers["location"] == "/voluntarios"
    assert second.status_code == 404


async def test_deactivate_routes_inexistente_retorna_404(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosRouteSpy,
) -> None:
    """Voluntario inexistente -> 404 (no redirect, no 500)."""
    voluntarios_spy.deactivate_returning_rows = []
    _login_as_key_user(client)

    response = await client.post(
        "/voluntarios/no-such-id/deactivate", follow_redirects=False
    )

    assert response.status_code == 404


# --- REQ-1: la SQL emitida tiene la forma exacta esperada ---------------


async def test_deactivate_routes_sql_es_update_con_returning_y_filtro_activo(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosRouteSpy,
) -> None:
    """La SQL emitida incluye ``RETURNING id`` y el filtro ``activo = true``.

    La presencia del filtro ``AND activo = true`` es la pieza que
    cierra la ventana TOCTOU: la condicion de existencia se evalua
    dentro de la propia sentencia, bajo el row lock de PostgreSQL.
    Sin ese filtro, dos requests concurrentes podrian ambas hacer
    UPDATE (un escenario que el test de concurrencia en
    ``test_voluntarios_concurrent.py`` cubre).
    """
    _login_as_key_user(client)

    response = await client.post(
        "/voluntarios/v-1/deactivate", follow_redirects=False
    )
    assert response.status_code == 303

    update_queries = [
        q
        for q in voluntarios_spy.captured_queries
        if "UPDATE voluntarios" in q and "SET activo = false" in q
    ]
    assert len(update_queries) == 1
    sql = update_queries[0]
    assert "RETURNING id" in sql
    assert "WHERE id = $1 AND activo = true" in sql
    # El parametro $1 esta ligado (no interpolado en la SQL).
    assert voluntarios_spy.captured_params[0] == ["v-1"]


# --- Acceptance criteria: grep invariants ---------------------------------


async def test_deactivate_routes_handler_no_tiene_select_previo_para_existencia(
    voluntarios_spy: _VoluntariosRouteSpy,
) -> None:
    """El handler NO llama ``get_voluntario_by_id`` antes del UPDATE.

    Implementado como un test que ejecuta el codigo del handler contra
    el spy y verifica el patron de queries emitidas (acceptance
    criterion del spec: ``grep -n "get_voluntario_by_id"
    app/modules/voluntarios/routes.py`` debe retornar solo la llamada
    del detalle, no la del deactivate).
    """
    import httpx as _httpx

    from app.main import app as _app

    transport = _httpx.ASGITransport(app=_app)
    async with _httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        _login_as_key_user(c)
        response = await c.post(
            "/voluntarios/v-1/deactivate", follow_redirects=False
        )

    assert response.status_code == 303
    # Cualquier SELECT que aparezca aqui es un bug (regresion del TOCTOU).
    select_queries = [
        q for q in voluntarios_spy.captured_queries if "SELECT" in q
    ]
    assert select_queries == [], (
        "el deactivate handler no debe emitir SELECT previo; "
        f"queries capturadas: {voluntarios_spy.captured_queries!r}"
    )
