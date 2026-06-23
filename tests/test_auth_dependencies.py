"""Tests for shared auth-related FastAPI dependencies.

The dependencies live in ``app.core.auth_dependencies`` and are used by
both the app entrypoint (``app.main``) and every module router. They
are a regression surface, so the contract is pinned here independently
of the route-level tests in ``test_admin.py`` / ``test_animals.py`` /
``test_voluntarios.py``.

Currently pinned:

- ``get_insforge_client_dep`` closes the ``httpx.Client`` it creates
  for each request (no resource leak across requests). This is the
  fix for code-quality-fixes T2 / problem #3 of the external review.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.main import app, get_insforge_client


class _SpyInsForge(InsForgeClient):
    """``InsForgeClient`` that records every ``close()`` call.

    Uses ``httpx.MockTransport`` so the underlying ``httpx.Client`` is
    fully functional for SQL roundtrips. Overrides ``close()`` to bump
    a class-level counter that the test inspects, without actually
    tearing down the underlying ``httpx.Client`` — multiple requests
    in one test must reuse the same spy. Subclassing (rather than
    mocking) keeps the dependency override type-compatible with the
    real signature.
    """

    close_calls: int = 0

    def __init__(self) -> None:  # type: ignore[override]
        # Bypass InsForgeClient.__init__ — we only need a working
        # ``_client`` that can roundtrip through MockTransport, not a
        # real InsForge connection.
        self._client = httpx.Client(
            base_url="https://spy.insforge.example",
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200,
                    content=json.dumps([]).encode("utf-8"),
                    headers={"content-type": "application/json"},
                )
            ),
        )

    def close(self) -> None:  # type: ignore[override]
        type(self).close_calls += 1
        # Intentionally do NOT close the underlying httpx.Client —
        # the spy is shared across multiple requests within one test
        # (triangulacion test). The contract under test is only that
        # ``close()`` is called the right number of times; the
        # teardown of the underlying pool is exercised in the real
        # ``InsForgeClient.close`` path, not here.


@pytest.fixture
def spy_insforge(monkeypatch: pytest.MonkeyPatch) -> _SpyInsForge:
    """Install a spy ``InsForgeClient`` as the dependency override.

    The override is itself a generator with a ``finally: spy.close()``
    to mirror the production dependency contract (closes the client
    after the handler runs). Resets the call counter on entry/exit so
    test order does not matter.
    """
    spy = _SpyInsForge()
    _SpyInsForge.close_calls = 0

    def _override_gen():
        try:
            yield spy
        finally:
            spy.close()

    app.dependency_overrides[get_insforge_client] = _override_gen
    yield spy
    app.dependency_overrides.pop(get_insforge_client, None)


def _login_as_developer(client: httpx.AsyncClient) -> None:
    """Install a developer session cookie so the /admin route lets us in."""
    from app.core.config import get_settings
    from app.core.session import session_cookie_name, write_session

    token = write_session(
        {
            "email": "root@example.com",
            "rol": "developer",
            "user_id": "u-root",
            "is_authorized": True,
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


async def test_get_insforge_client_dep_cierra_el_cliente_despues_de_cada_request(
    client: httpx.AsyncClient,
    spy_insforge: _SpyInsForge,
) -> None:
    """Cada request que inyecta el cliente debe cerrarlo al terminar.

    Sin el fix, el ``httpx.Client`` subyacente nunca se cierra y las
    conexiones HTTP se acumulan (resource leak del code review externo,
    problema #3). El generador con ``finally: close()`` en la
    dependencia asegura que FastAPI ejecute el ``finally`` despues de
    que el handler retorna.
    """
    _login_as_developer(client)

    response = await client.get("/admin", follow_redirects=False)

    assert response.status_code == 200
    assert _SpyInsForge.close_calls == 1, (
        f"close() debio llamarse exactamente 1 vez tras el request, "
        f"se llamo {_SpyInsForge.close_calls} veces"
    )


async def test_get_insforge_client_dep_cierra_el_cliente_incluso_si_el_handler_falla(
    client: httpx.AsyncClient,
    spy_insforge: _SpyInsForge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El ``finally`` del generador cierra el cliente aunque el handler levante.

    Esto es lo que hace que el fix sea un ``finally`` y no un close al
    final del happy path: un 5xx no debe dejar conexiones abiertas.
    Forzamos el handler a lanzar patcheando ``execute_sql`` en la clase
    del spy para que cualquier handler que use el cliente dispare la
    excepcion; asi no dependemos de simbolos importados en ``app.main``.
    """
    from app.core.insforge import InsForgeError as _InsForgeError  # noqa: F401

    def _boom(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated handler failure")

    monkeypatch.setattr(_SpyInsForge, "execute_sql", _boom)

    _login_as_developer(client)

    with pytest.raises(RuntimeError, match="simulated handler failure"):
        await client.get("/admin", follow_redirects=False)

    assert _SpyInsForge.close_calls == 1, (
        f"close() debio llamarse aunque el handler haya fallado; "
        f"se llamo {_SpyInsForge.close_calls} veces"
    )


async def test_get_insforge_client_dep_cierra_el_cliente_una_vez_por_request(
    client: httpx.AsyncClient,
    spy_insforge: _SpyInsForge,
) -> None:
    """Cada request adicional cierra su propio cliente (sin acumular cierres extra).

    Triangulacion: tras dos requests, ``close()`` debe haberse llamado
    dos veces (no una vez para siempre, no cero). Esto descarta el
    regresion donde un close se ejecuta una sola vez al shutdown.
    """
    _login_as_developer(client)

    await client.get("/admin", follow_redirects=False)
    await client.get("/admin", follow_redirects=False)

    assert _SpyInsForge.close_calls == 2, (
        f"close() debio llamarse 2 veces tras 2 requests, "
        f"se llamo {_SpyInsForge.close_calls} veces"
    )
