"""Route tests for ``GET /animales/search`` through ``AnimalsPort``."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.core.session import session_cookie_name, write_session
from app.main import app
from app.modules.animals.di.animals_di import get_animals_port
from app.modules.animals.domain.animal import (
    Animal,
    AnimalSearchResult,
    Especie,
    Sexo,
)
from tests.conftest import auth_reval_rows


class _AuthClient:
    """Answer only the authorization revalidation query."""

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, Any]]:
        return auth_reval_rows(query, params) or []


class _SearchPort:
    """Capture search calls and return an envelope from normalized inputs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.animal = Animal(
            id="animal-1",
            NCHIP="123456789012345",
            NombreAnimal="Luna",
            Especie=Especie.CANINA,
            Sexo=Sexo.H,
            FNacimiento="2023-04-12",
            fecha_alta="2024-01-15",
            estado="albergue",
        )

    def search_animals(self, **kwargs: object) -> AnimalSearchResult:
        self.calls.append(kwargs)
        return AnimalSearchResult(
            data=(self.animal,),
            total=1,
            limit=int(kwargs["limit"]),
            offset=int(kwargs["offset"]),
        )


@pytest.fixture
def search_port(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SearchPort]:
    port = _SearchPort()
    monkeypatch.setattr(app.state, "insforge_client", _AuthClient(), raising=False)
    app.dependency_overrides[get_animals_port] = lambda: port
    yield port
    app.dependency_overrides.pop(get_animals_port, None)


def _login(client: httpx.AsyncClient) -> None:
    from app.core.config import get_settings

    token = write_session(
        {
            "email": "animal-search@example.com",
            "rol": "key_user",
            "user_id": "search-user",
            "is_authorized": True,
            "csrf_token": "animal-search-token",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


async def test_search_animales_uses_port_and_serializes_domain_entity(
    client: httpx.AsyncClient,
    search_port: _SearchPort,
) -> None:
    _login(client)

    response = await client.get(
        "/animales/search",
        params={
            "q": "lun",
            "chip": "123456789012345",
            "especie": "CANINA",
            "sexo": "H",
            "estado": "albergue",
            "fecha_alta_since": "2024-01-01",
            "fecha_alta_until": "2024-12-31",
            "limit": 10,
            "offset": 20,
        },
    )

    assert response.status_code == 200, response.text
    assert search_port.calls == [
        {
            "q": "lun",
            "chip": "123456789012345",
            "especie": Especie.CANINA,
            "sexo": Sexo.H,
            "estado": "albergue",
            "fecha_alta_since": "2024-01-01",
            "fecha_alta_until": "2024-12-31",
            "limit": 10,
            "offset": 20,
        }
    ], "the route must delegate every query filter through the application use case"
    assert response.json() == {
        "data": [
            {
                "id": "animal-1",
                "chip": "123456789012345",
                "nombre": "Luna",
                "especie": "CANINA",
                "sexo": "H",
                "estado": "albergue",
                "fecha_nacimiento": "2023-04-12",
                "fecha_alta": "2024-01-15",
            }
        ],
        "total": 1,
        "limit": 10,
        "offset": 20,
    }, "the response envelope must preserve the legacy search API shape"


async def test_search_animales_preserves_zero_limit_count_only_contract(
    client: httpx.AsyncClient,
    search_port: _SearchPort,
) -> None:
    _login(client)

    response = await client.get("/animales/search", params={"limit": 0})

    assert response.status_code == 200, response.text
    assert search_port.calls[0]["limit"] == 0, (
        "the migrated route must preserve the legacy count-only contract"
    )
    assert response.json()["limit"] == 0, "the envelope must report count-only mode"
