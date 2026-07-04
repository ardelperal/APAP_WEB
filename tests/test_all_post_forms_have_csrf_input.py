"""Tests verifying every POST form renders a CSRF token input (PR-5B2, T-5B.14).

Spec coverage: REQ-AH-7 — every ``<form method="post">`` in the
application MUST include ``<input type="hidden" name="csrf_token">``
whose value matches the session's CSRF token. If a future PR adds a
new POST form without the input, this test fails with a clear message
that points at the missing template.

Per round-2 fix REG-S-2, the test iterates over the 10 POST HANDLERS
(not the 8 distinct form tags — animals/form.html and
entradas/form.html are reused for both create and update). The
runtime enumeration in test_csrf_form_enumeration.py covers the
"JS-submitted forms" gap (REQ-AH-7 misses fetch/onclick submissions
that bypass the rendered HTML).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.adopciones import service as adopciones_service
from app.modules.animals import service as animals_service
from app.modules.animals.service import Especie as EspecieEnum
from app.modules.animals.service import Sexo as SexoEnum
from app.modules.entradas import service as entradas_service
from app.modules.voluntarios import service as voluntarios_service


class _InsForgeSpy:
    """In-process InsForge stand-in. Routes use the service modules,
    so we override the SERVICES directly rather than mocking SQL."""

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[no-untyped-def]
        # We don't actually need SQL here because the services are
        # monkey-patched in the fixture. This stub exists only to
        # satisfy InsForgeClient's interface.
        from tests.conftest import auth_reval_rows

        _reval = auth_reval_rows(query, params, rol="developer")
        if _reval is not None:
            return _reval
        return [{"id": "stub-1"}]

    def __getattr__(self, name: str) -> Any:  # type: ignore[no-untyped-def]
        # Strict mode: unmocked methods surface as test failures. The
        # previous ``return lambda *a, **kw: None`` silently swallowed
        # every call and let bugs hide (a future OAuth method or SQL
        # call would just no-op and the test would stay green).
        raise NotImplementedError(
            f"_InsForgeSpy.{name} is not mocked. Add an explicit method "
            f"to the spy in this test instead of relying on no-op fallback."
        )


@pytest.fixture
def spy_insforge(monkeypatch: pytest.MonkeyPatch) -> _InsForgeSpy:
    spy = _InsForgeSpy()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    monkeypatch.setattr(
        "app.modules.animals.routes.get_insforge_client_dep", lambda: spy
    )
    monkeypatch.setattr(
        "app.modules.entradas.routes.get_insforge_client_dep", lambda: spy
    )
    monkeypatch.setattr(
        "app.modules.voluntarios.routes.get_insforge_client_dep", lambda: spy
    )
    monkeypatch.setattr(
        "app.modules.adopciones.routes.get_insforge_client_dep", lambda: spy
    )

    # Stub the services so they return plausible objects without
    # hitting InsForge SQL. The route handlers call into these
    # services; the service layer is what actually executes SQL.
    monkeypatch.setattr(
        animals_service, "get_animal_by_id",
        lambda _c, _id: animals_service.Animal(
            id="abc-123",
            NCHIP="985112004409871",
            NombreAnimal="Luna",
            Especie=EspecieEnum.CANINA,
            Sexo=SexoEnum.H,
            FNacimiento="2023-04-12",
            Raza=None,
            Color=None,
            Pelo=None,
            Tamano=None,
            Caracter=None,
            TraeNChip=None,
            FIMPLANTACIONCHIP=None,
            FDefuncion=None,
            Terapia=None,
            Eutanasia=None,
            Mestizo=None,
            RazaPPP=None,
            Cartilla=None,
            NombreFoto=None,
            ComunicacionARIAC=None,
            Observaciones=None,
            activo=True,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        animals_service, "list_animales",
        lambda _c: [animals_service.Animal(
            id="abc-123",
            NCHIP="985112004409871",
            NombreAnimal="Luna",
            Especie=EspecieEnum.CANINA,
            Sexo=SexoEnum.H,
            FNacimiento="2023-04-12",
            Raza=None, Color=None, Pelo=None, Tamano=None,
            Caracter=None, TraeNChip=None, FIMPLANTACIONCHIP=None,
            FDefuncion=None, Terapia=None, Eutanasia=None,
            Mestizo=None, RazaPPP=None, Cartilla=None, NombreFoto=None,
            ComunicacionARIAC=None, Observaciones=None,
            activo=True,
        )],
        raising=False,
    )
    monkeypatch.setattr(
        entradas_service, "get_entrada_by_id",
        lambda _c, _id: entradas_service.Entrada(
            id="ent-1",
            animal_id="abc-123",
            voluntario_entrada_id=None,
            fecha_entrada="2026-06-25",
            origen="Rescate",
            motivo="Abandono",
            observaciones="Tranquila",
        ),
        raising=False,
    )
    monkeypatch.setattr(
        entradas_service, "list_entradas",
        lambda _c: [entradas_service.Entrada(
            id="ent-1",
            animal_id="abc-123",
            voluntario_entrada_id=None,
            fecha_entrada="2026-06-25",
            origen="Rescate",
            motivo="Abandono",
            observaciones="Tranquila",
        )],
        raising=False,
    )
    monkeypatch.setattr(
        voluntarios_service, "get_voluntario_by_id",
        lambda _c, _id: voluntarios_service.Voluntario(
            id="v-1",
            Voluntario="Ana",
            Email="ana@example.com",
            DNI="12345678A",
            Tel1="600000000",
            Tel2=None,
            fecha_alta="2026-06-01",
            activo=True,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        voluntarios_service, "list_voluntarios",
        lambda _c: [voluntarios_service.Voluntario(
            id="v-1",
            Voluntario="Ana",
            Email="ana@example.com",
            DNI="12345678A",
            Tel1="600000000",
            Tel2=None,
            fecha_alta="2026-06-01",
            activo=True,
        )],
        raising=False,
    )
    monkeypatch.setattr(
        voluntarios_service, "list_roles",
        lambda _c, _id: ["paseador"],
        raising=False,
    )
    monkeypatch.setattr(
        adopciones_service, "get_adopcion_by_id",
        lambda _c, _id: adopciones_service.Adopcion(
            id="adop-1",
            animal_id="abc-123",
            voluntario_seguimiento_id=None,
            fecha_adopcion="2026-07-04",
            fecha_devolucion=None,
            donativo_preadopcion=None,
            donativo_adopcion=None,
            nombre_adoptante="María García López",
            dni_adoptante=None,
            telefono_adoptante=None,
            email_adoptante=None,
            entrada_origen_id=None,
            observaciones=None,
            tipo_adopcion="regular",
        ),
        raising=False,
    )

    yield spy
    app.dependency_overrides.pop(get_insforge_client, None)


_TEST_CSRF_TOKEN = "audit-token-1234567890"


@pytest.fixture
def logged_in_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """A client pre-loaded with a developer session + CSRF token."""
    settings = get_settings()
    token = write_session(
        {
            "email": "audit@example.com",
            "rol": "developer",
            "user_id": "u-audit",
            "is_authorized": True,
            "csrf_token": _TEST_CSRF_TOKEN,
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)
    return client


def _assert_csrf_input_in_html(html: str, *, url_path: str) -> None:
    marker = f'name="csrf_token" value="{_TEST_CSRF_TOKEN}"'
    assert marker in html, (
        f"{url_path} rendered HTML without the CSRF hidden input. "
        f"Expected to find {marker!r}. "
        "Either the form is missing the input, the template's csrf_token "
        "context binding is broken, or the middleware did not populate "
        "request.state.csrf_token. See app/templates/<file> and "
        "app/main.py::Jinja2Templates(context_processors=...)."
    )


# --- 10 POST handlers enumerated -----------------------------------------

# Each entry is (URL path to GET, description of the form being audited).
# Update this table when a new POST form is added; the test will fail
# until the form template is updated to include the CSRF hidden input.

_FORM_ROUTES: list[tuple[str, str]] = [
    ("/admin", "add-user form (action=/admin/users)"),
    ("/admin", "deactivate-user form (action=/admin/users/{id}/deactivate)"),
    ("/animales/new", "create-animal form (action=/animales)"),
    ("/animales/abc-123/edit", "update-animal form (action=/animales/{id}/update)"),
    ("/animales/abc-123", "delete-animal form (action=/animales/{id}/delete)"),
    ("/entradas/new", "create-entrada form (action=/entradas)"),
    ("/entradas/ent-1/edit", "update-entrada form (action=/entradas/{id}/update)"),
    ("/entradas/ent-1", "delete-entrada form (action=/entradas/{id}/delete)"),
    ("/voluntarios/new", "create-voluntario form (action=/voluntarios)"),
    ("/voluntarios/v-1", "deactivate-voluntario form (action=/voluntarios/{id}/deactivate)"),
    # ADOPT-01 (#47) — adopciones CRUD adds 3 more POST forms.
    ("/adopciones/new", "create-adopcion form (action=/adopciones)"),
    ("/adopciones/adop-1/edit", "update-adopcion form (action=/adopciones/{id}/update)"),
    ("/adopciones/adop-1", "delete-adopcion form (action=/adopciones/{id}/delete)"),
]


@pytest.mark.parametrize("url_path,form_description", _FORM_ROUTES)
async def test_post_form_renders_csrf_token_input(
    logged_in_client: httpx.AsyncClient,
    spy_insforge: _InsForgeSpy,
    url_path: str,
    form_description: str,
) -> None:
    """Every POST form in the application MUST include the csrf_token hidden input.

    Iterates over the 10 handlers enumerated in the audit doc's
    "Pre-slice form audit" table. The same HTML snippet
    ``<input type=\"hidden\" name=\"csrf_token\" value=\"...\"/>``
    must appear inside every form tag.
    """
    response = await logged_in_client.get(url_path, follow_redirects=False)

    assert response.status_code == 200, (
        f"GET {url_path} returned {response.status_code} for {form_description}; "
        "cannot audit the form's CSRF input without a 200 response."
    )
    _assert_csrf_input_in_html(response.text, url_path=url_path)
