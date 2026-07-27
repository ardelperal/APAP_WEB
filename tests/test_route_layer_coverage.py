"""Behavioral coverage for route-layer HTTP branches (issue #288)."""

from __future__ import annotations

import inspect
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from app.modules.animals import routes as animal_routes
from app.modules.voluntarios import routes as voluntario_routes

ROUTE_MODULES = (
    "app.modules.acogidas.routes",
    "app.modules.adopciones.routes",
    "app.modules.animals.routes",
    "app.modules.cesiones.routes",
    "app.modules.entradas.batch_routes",
    "app.modules.entradas.routes",
    "app.modules.foster.assignment_routes",
    "app.modules.foster.routes",
    "app.modules.materiales.acogida_routes",
    "app.modules.materiales.routes",
    "app.modules.sanidad.routes",
    "app.modules.voluntarios.routes",
)


@pytest.mark.parametrize("module_name", ROUTE_MODULES)
async def test_every_route_returns_dependency_response_without_domain_work(
    module_name: str,
) -> None:
    """Every handler honors the auth dependency's redirect/403 response."""
    route_module = import_module(module_name)
    early = Response(status_code=403)

    for route in route_module.router.routes:
        kwargs: dict[str, object] = {"user": early}
        for parameter in inspect.signature(route.endpoint).parameters.values():
            if parameter.default is not inspect.Parameter.empty:
                continue
            if parameter.name == "request":
                kwargs[parameter.name] = Mock()
            elif parameter.name.endswith("_id"):
                kwargs[parameter.name] = "irrelevant-id"

        result = route.endpoint(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        assert result is early, route.endpoint.__name__


def test_voluntario_form_normalizes_optional_values() -> None:
    """Form conversion strips text and preserves absent/blank optionals."""
    assert voluntario_routes._form_data_to_params(
        {
            "Voluntario": "  Ana  ",
            "Tel1": None,
            "Tel2": " ",
            "Email": " ana@example.com ",
            "DNI": " 123 ",
        }
    ) == {
        "Voluntario": "Ana",
        "Tel1": None,
        "Tel2": None,
        "Email": "ana@example.com",
        "DNI": "123",
    }


def test_create_voluntario_rerenders_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service validation failure remains an observable HTTP 422."""
    monkeypatch.setattr(
        voluntario_routes.voluntarios_service,
        "create_voluntario",
        Mock(side_effect=ValueError("El nombre es obligatorio.")),
    )
    render = Mock(return_value=Response(status_code=422))
    monkeypatch.setattr(voluntario_routes._templates, "TemplateResponse", render)

    response = voluntario_routes.create_voluntario_view(
        request=Mock(),
        Voluntario=" ",
        Tel1=None,
        Tel2=None,
        Email=None,
        DNI=None,
        user={"user_id": "writer-1"},
        client=Mock(),
    )

    assert response.status_code == 422
    assert render.call_args.kwargs["context"]["error"] == "El nombre es obligatorio."
    assert render.call_args.kwargs["context"]["form_data"]["Voluntario"] is None


def test_create_voluntario_redirects_to_created_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful creation redirects to the concrete persisted resource."""
    monkeypatch.setattr(
        voluntario_routes.voluntarios_service,
        "create_voluntario",
        Mock(return_value=SimpleNamespace(id="vol-42")),
    )

    response = voluntario_routes.create_voluntario_view(
        request=Mock(),
        Voluntario="Ana",
        Tel1=None,
        Tel2=None,
        Email=None,
        DNI=None,
        user={"user_id": "writer-1"},
        client=Mock(),
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/voluntarios/vol-42"


def test_voluntario_detail_returns_404_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale voluntario link is translated into HTTP 404."""
    monkeypatch.setattr(
        voluntario_routes.voluntarios_service,
        "get_voluntario_by_id",
        Mock(return_value=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        voluntario_routes.voluntario_detail(
            voluntario_id="missing",
            request=Mock(),
            user={"user_id": "reader-1"},
            client=Mock(),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.parametrize(
    ("handler", "service_name"),
    (
        (animal_routes.animal_detail, "get_animal_by_id"),
        (animal_routes.edit_animal_form, "get_animal_by_id"),
        (animal_routes.delete_animal_view, "delete_animal"),
    ),
)
def test_animal_routes_return_404_for_missing_resource(
    monkeypatch: pytest.MonkeyPatch,
    handler,
    service_name: str,
) -> None:
    """Detail, edit, and delete expose the same missing-resource contract."""
    monkeypatch.setattr(
        animal_routes.animals_service,
        service_name,
        Mock(return_value=None if service_name == "get_animal_by_id" else False),
    )

    with pytest.raises(HTTPException) as exc_info:
        handler(
            animal_id="missing",
            request=Mock(),
            user={"user_id": "writer-1"},
            client=Mock(),
        )

    assert exc_info.value.status_code == 404
