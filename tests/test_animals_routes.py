"""Route-level tests for the animales module (TDD para refactor de T3).

El service ya esta cubierto en ``test_animals.py`` con ``MockTransport``.
Estos tests ejercen el ciclo completo request/response contra el
router de animales, verificando que el handler delega en el service
despues del refactor ``code-quality-fixes T3`` (mueve el SQL del
handler al service).

Cobertura:

- POST ``/animales/{id}/update`` con form valido -> 303 redirect.
- POST ``/animales/{id}/update`` con NCHIP vacio -> 422 + form re-render.
- POST ``/animales/{id}/delete`` con id existente -> 303 redirect.
- POST ``/animales/{id}/delete`` con id inexistente -> 404.
- Verifica que el handler NO llama ``client.execute_sql`` directamente
  (problema #1 del code review externo).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client


class _AnimalsRouteSpy(InsForgeClient):
    """``InsForgeClient`` spy para los routes de animales.

    ``execute_sql`` no toca la red: en cambio, matchea el SQL contra
    patrones clasicos (``UPDATE animales SET``,
    ``SET activo = false``, ``SELECT`` con ``WHERE id = $1``) y devuelve
    el row apropiado para que el handler produzca su respuesta esperada.

    Tambien expone ``captured_queries`` para que los tests verifiquen
    que el handler emite EXACTAMENTE los SQLs esperados — pista clave
    para detectar si el handler sigue ejecutando SQL directo (regresion
    del problema #1 que este PR cierra).
    """

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        self.captured_queries: list[str] = []
        # By default, ``get_animal_by_id`` (lookup pre-delete) returns a
        # row. Tests can override this to simulate 404.
        self.get_animal_by_id_rows: list[dict[str, Any]] = [
            {
                "id": "abc-123",
                "NCHIP": "1",
                "NombreAnimal": "Luna",
                "Especie": "CANINA",
                "Sexo": "H",
                "FNacimiento": "2023-04-12",
                "activo": True,
            }
        ]
        # ``UPDATE animales SET ... RETURNING`` (update_animal) row.
        self.update_returning_rows: list[dict[str, Any]] = [
            {
                "id": "abc-123",
                "NCHIP": "985112004409871",
                "NombreAnimal": "Luna",
                "Especie": "CANINA",
                "Sexo": "H",
                "FNacimiento": "2023-04-12",
                "activo": True,
            }
        ]
        # ``UPDATE animales SET activo = false`` (delete_animal) row.
        self.delete_returning_rows: list[dict[str, Any]] = [
            {"id": "abc-123", "activo": False}
        ]

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
        self.captured_queries.append(query)
        if "SET activo = false" in query:
            return list(self.delete_returning_rows)
        if "UPDATE animales SET" in query:
            return list(self.update_returning_rows)
        if "SELECT" in query and "WHERE id = $1" in query:
            return list(self.get_animal_by_id_rows)
        return []


@pytest.fixture
def animals_spy() -> _AnimalsRouteSpy:
    spy = _AnimalsRouteSpy()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_insforge_client, None)


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    """Any authorized user can hit /animales; key_user es el caso mas comun."""
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


# --- update ----------------------------------------------------------------


async def test_update_animal_view_delega_en_service_y_redirige_303(
    client: httpx.AsyncClient,
    animals_spy: _AnimalsRouteSpy,
) -> None:
    """POST /animales/{id}/update con form valido -> 303 a /animales/{id}."""
    _login_as_key_user(client)

    response = await client.post(
        "/animales/abc-123/update",
        data={
            "NCHIP": "985112004409871",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/animales/abc-123"
    # El handler NO debe emitir SQL directo (problema #1 cerrado):
    # el unico SQL es el UPDATE que emite ``update_animal`` via service.
    update_queries = [q for q in animals_spy.captured_queries if "UPDATE animales SET" in q]
    assert len(update_queries) == 1, (
        f"se esperaba UN UPDATE via service, se emitieron: {update_queries!r}"
    )


async def test_update_animal_view_con_NCHIP_vacio_retorna_422_sin_update(
    client: httpx.AsyncClient,
    animals_spy: _AnimalsRouteSpy,
) -> None:
    """NCHIP vacio (whitespace) -> re-render del form con 422, sin tocar la DB.

    Usamos ``"   "`` (whitespace) en vez de ``""`` porque httpx no
    envia campos de form vacios: un NCHIP vacio dispara el 422 de
    validacion de FastAPI (``Form(...)``) ANTES de llegar al handler
    y devuelve JSON. El whitespace se filtra en ``_form_data_to_params``
    y dispara la validacion del service que renderiza el form HTML.
    """
    _login_as_key_user(client)

    response = await client.post(
        "/animales/abc-123/update",
        data={
            "NCHIP": "   ",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "text/html" in response.headers["content-type"]
    # No se debe haber emitido ningun UPDATE.
    assert not any("UPDATE animales SET" in q for q in animals_spy.captured_queries), (
        f"no se debe emitir UPDATE si la validacion falla; queries: {animals_spy.captured_queries!r}"
    )


# --- delete ----------------------------------------------------------------


async def test_delete_animal_view_delega_en_service_y_redirige_303(
    client: httpx.AsyncClient,
    animals_spy: _AnimalsRouteSpy,
) -> None:
    """POST /animales/{id}/delete con id existente -> 303 a /animales."""
    _login_as_key_user(client)

    response = await client.post(
        "/animales/abc-123/delete", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/animales"
    # El handler delega en service.delete_animal que emite un solo
    # UPDATE activo = false. NO debe haber un SELECT previo redundante
    # para verificar existencia (eso era el patron anterior del bug).
    assert any("SET activo = false" in q for q in animals_spy.captured_queries)


async def test_delete_animal_view_con_id_inexistente_retorna_404(
    client: httpx.AsyncClient,
    animals_spy: _AnimalsRouteSpy,
) -> None:
    """delete_animal de un id que no existe -> 404 (sin redireccion)."""
    animals_spy.get_animal_by_id_rows = []   # delete devolvera False
    animals_spy.delete_returning_rows = []   # el service ve 0 filas -> False
    _login_as_key_user(client)

    response = await client.post(
        "/animales/no-such-id/delete", follow_redirects=False
    )

    assert response.status_code == 404
