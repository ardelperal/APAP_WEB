"""Route-level tests for the animales module.

The service layer is covered in ``test_animals.py`` with
``MockTransport``. These tests exercise the full request/response
cycle against the animales router to verify the handler delegates
to the service. The form-shape contract (single ``AnimalForm``
model, not 24 individual ``Form(...)`` params) is pinned at the
end of this file.

Cobertura:

- POST ``/animales/{id}/update`` con form valido -> 303 redirect.
- POST ``/animales/{id}/update`` con NCHIP vacio -> 422 + form re-render.
- POST ``/animales/{id}/delete`` con id existente -> 303 redirect.
- POST ``/animales/{id}/delete`` con id inexistente -> 404.
- Verifica que el handler NO llama ``client.execute_sql`` directamente
  (problema #1 del code review externo).
"""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.animals import routes as animals_routes
from app.modules.animals.forms import (
    ANIMAL_FORM_FIELDS,
    ANIMAL_FORM_REQUIRED_FIELDS,
)
from tests.conftest import auth_reval_rows, make_csrf_request


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
        # Issue #144: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to ``key_user`` (matches the
        # common test login). Tests that exercise the reader path
        # mutate this to ``reader`` so ``require_authorized_user`` picks
        # it up and ``require_writer_user`` can reject the POST.
        self.auth_reval_rol: str = "key_user"
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
        # Chip change saga: default chip change spy rows.
        # Tests can override these to simulate different scenarios.
        self.chip_change_get_animal_rows: list[dict[str, Any]] = [
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
        self.chip_change_new_chip_assigned: bool = False  # True = another animal has new_chip
        self.chip_change_old_chip_match: bool = True  # True = old_chip matches actual

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
        # Issue #143: the per-request authorization revalidation SELECT
        # (via get_user_by_email) is answered here and NOT recorded in
        # captured_queries, so the domain-SQL assertions stay unchanged.
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval
        self.captured_queries.append(query)
        if "SET activo = false" in query:
            return list(self.delete_returning_rows)
        if "UPDATE animales SET" in query:
            return list(self.update_returning_rows)
        if "SELECT" in query and "WHERE id = $1" in query:
            return list(self.get_animal_by_id_rows)
        # Chip change saga handlers (issue #29)
        q_lower = query.lower()
        params_list = list(params) if params else []
        # Chip uniqueness: SELECT id FROM animals WHERE NCHIP = $1 AND id != $2
        if "select id from animals where nchip" in q_lower and len(params_list) >= 2:
            if self.chip_change_new_chip_assigned:
                return [{"id": "other-animal"}]  # new_chip is taken
            return []
        # Current chip: SELECT NCHIP FROM animals WHERE id = $1
        if "select nchip from animals where id" in q_lower and len(params_list) >= 1:
            if not self.chip_change_old_chip_match:
                return []  # animal not found or chip doesn't match
            return [{"NCHIP": "111"}]
        # All chip-change UPDATE queries return their PK row
        if any(kw in q_lower for kw in (
            "update entradas set chip",
            "update acogidas set chip",
            "update adopciones set chip",
            "update actuaciones_sanitarias set chip",
            "update terapias set chip",
        )):
            return [{"id": "row-1"}]
        # UPDATE animals for chip change
        if "update animals set nchip" in q_lower:
            return [{"id": "abc-123", "NCHIP": params_list[0] if params_list else ""}]
        # BEGIN, COMMIT, ROLLBACK
        if q_lower.strip() in ("begin", "commit", "rollback"):
            return []
        # INSERT lifecycle event
        if "insert into animal_lifecycle_events" in q_lower:
            return []
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
            # PR-5B2: session-bound CSRF token so CsrfMiddleware validates
            # the POSTs from this test client.
            "csrf_token": "test-csrf-token-animals",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_reader(client: httpx.AsyncClient) -> None:
    """Install a reader session cookie; reader MUST be 403 on writes (issue #144).

    The revalidation SELECT in ``require_authorized_user`` returns the rol
    the cookie carries. To keep both in sync the spy also needs to answer
    ``auth_reval_rows`` with ``rol='reader'``; tests that exercise the
    reader path mutate ``animals_spy.auth_reval_rol`` to ``"reader"``
    before calling this helper.
    """
    from app.core.config import get_settings

    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-animals",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


# --- update ----------------------------------------------------------------


async def test_update_animal_view_delega_en_service_y_redirige_303(
    client: httpx.AsyncClient,
    animals_spy: _AnimalsRouteSpy,
) -> None:
    """POST /animales/{id}/update con form valido -> 303 a /animales/{id}.

    Tras #129 la validacion Pydantic requiere 9 campos; el form data
    cubre los 9 required + 0 opcionales (caso minimo).
    """
    _login_as_key_user(client)

    response = await make_csrf_request(
        client,
        "POST",
        "/animales/abc-123/update",
        form_data={
            "NCHIP": "985112004409871",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "Terapia": "No",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2023-04-15",
            "NombreFoto": "luna.jpg",
        },
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

    response = await make_csrf_request(
        client,
        "POST",
        "/animales/abc-123/update",
        form_data={
            "NCHIP": "   ",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "Terapia": "No",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2023-04-15",
            "NombreFoto": "luna.jpg",
        },
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

    response = await make_csrf_request(
        client,
        "POST",
        "/animales/abc-123/delete",
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

    response = await make_csrf_request(
        client,
        "POST",
        "/animales/no-such-id/delete",
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Single source of truth: the routes MUST use AnimalForm, not 24 Form() params
# ---------------------------------------------------------------------------


def _animal_form_params(func):
    """Return the parameters of ``func`` whose annotation is ``AnimalForm``.

    Filters out path / query / dep parameters so we count only the
    form-shape parameters, whatever their name.

    ``from __future__ import annotations`` makes all annotations lazy
    strings, so we compare by ``str(annotation)`` against
    ``"AnimalForm"`` (which matches both the string form and the
    resolved class). The project binds the form via
    ``Annotated[AnimalForm, Form()]``, so the substring check is the
    correct invariant.
    """
    try:
        hints = inspect.get_annotations(func)
    except Exception:
        hints = {}
    sig = inspect.signature(func)
    return [
        p
        for name, p in sig.parameters.items()
        if "AnimalForm" in str(hints.get(name, ""))
    ]


def test_create_animal_view_uses_animal_form_not_24_form_params():
    """``create_animal_view`` MUST take a single ``AnimalForm`` parameter.

    The previous signature had 24 ``Form(...)`` parameters + 2 deps.
    Adding a column meant editing two places; a typo in either was
    silent. The new contract: one model, one place.
    """
    params = _animal_form_params(animals_routes.create_animal_view)
    assert len(params) == 1, (
        f"create_animal_view must take exactly one AnimalForm parameter, "
        f"got {len(params)}: {[p.name for p in params]!r}"
    )


def test_update_animal_view_uses_animal_form_not_24_form_params():
    """``update_animal_view`` MUST take the same ``AnimalForm`` shape."""
    params = _animal_form_params(animals_routes.update_animal_view)
    assert len(params) == 1, (
        f"update_animal_view must take exactly one AnimalForm parameter, "
        f"got {len(params)}: {[p.name for p in params]!r}"
    )


def test_create_and_update_forms_use_the_same_animal_form():
    """Both routes MUST use the SAME ``AnimalForm`` model.

    If the two routes use different models, a column rename would
    silently fix one handler and break the other.
    """
    create_form = _animal_form_params(animals_routes.create_animal_view)[0]
    update_form = _animal_form_params(animals_routes.update_animal_view)[0]
    assert create_form.annotation is update_form.annotation, (
        "create_animal_view and update_animal_view must use the same "
        "AnimalForm model; a column rename in one but not the other "
        "would silently break the divergent handler."
    )


def test_routes_no_longer_declare_individual_form_params():
    """The 24-individual-Form(...) pattern MUST be gone.

    Regression test for the dedup: if a future change re-introduces
    ``NCHIP: str = Form(...)`` in the route signature, this test
    catches it. The AnimalForm parameter itself is allowed (it IS
    the new single source of truth).

    Compares the annotation by ``__name__`` because
    ``from __future__ import annotations`` makes all annotations lazy
    strings; ``hints.get(name) is AnimalForm`` would always be False
    because the string ``"AnimalForm"`` is not the class object.
    """
    for func in (
        animals_routes.create_animal_view,
        animals_routes.update_animal_view,
    ):
        try:
            hints = inspect.get_annotations(func)
        except Exception:
            hints = {}
        sig = inspect.signature(func)
        for name, param in sig.parameters.items():
            annotation = hints.get(name)
            # Allow the AnimalForm model itself (the new single source
            # of truth) and any non-annotated parameter (Request,
            # path / dep, etc.).
            if annotation is inspect.Parameter.empty:
                continue
            # ``from __future__ import annotations`` makes the
            # annotation the string "AnimalForm"; compare by str()
            # so both the string and the resolved class are accepted.
            if str(annotation) == "AnimalForm":
                continue
            if (
                hasattr(param.default, "__class__")
                and param.default.__class__.__name__ == "Form"
            ):
                pytest.fail(
                    f"{func.__name__}({name}: {annotation}) carries a "
                    f"Form() default — use the AnimalForm model instead so "
                    f"the column list lives in ONE place."
                )


def test_animal_form_fields_match_service_insert_columns():
    """The form's 24 fields MUST equal the service's 24 ``_INSERT_COLUMNS``.

    Ademas los 9 required fields (5 Access + 4 discovery) son la union
    canonica declarada en ``ANIMAL_FORM_REQUIRED_FIELDS``. Si alguien
    anade un required sin tocar el test, este falla con el set driftado.
    """
    assert len(ANIMAL_FORM_FIELDS) == 24, (
        f"AnimalForm must have 24 fields, got {len(ANIMAL_FORM_FIELDS)}: "
        f"{ANIMAL_FORM_FIELDS!r}"
    )
    assert ANIMAL_FORM_REQUIRED_FIELDS == (
        # Access TbFichaAnimal.Required=True
        "NCHIP",
        "NombreAnimal",
        "Especie",
        "Sexo",
        "FNacimiento",
        "Terapia",
        # Discovery feature-01 §"Required animal data"
        "TraeNChip",
        "FIMPLANTACIONCHIP",
        "NombreFoto",
    ), (
        f"AnimalForm required fields drifted from Access + discovery; "
        f"got {ANIMAL_FORM_REQUIRED_FIELDS!r}"
    )


# ---------------------------------------------------------------------------
# Issue #144: a ``reader`` rol MUST be rejected by write routes with 403.
# These tests pin the route-level contract for the 3 animales write
# surfaces (POST create / update / delete) without touching the GET
# routes. The shared ``animals_spy`` answers the per-request auth
# revalidation SELECT with ``rol=self.auth_reval_rol`` so a single
# spy can serve both the key_user happy paths and the reader 403 paths.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,form_data",
    [
        (
            "POST",
            "/animales",
            {
                "NCHIP": "985112004409871",
                "NombreAnimal": "Luna",
                "Especie": "CANINA",
                "Sexo": "H",
                "FNacimiento": "2023-04-12",
                "Terapia": "No",
                "TraeNChip": "Si",
                "FIMPLANTACIONCHIP": "2023-04-15",
                "NombreFoto": "luna.jpg",
            },
        ),
        (
            "POST",
            "/animales/abc-123/update",
            {
                "NCHIP": "985112004409871",
                "NombreAnimal": "Luna",
                "Especie": "CANINA",
                "Sexo": "H",
                "FNacimiento": "2023-04-12",
                "Terapia": "No",
                "TraeNChip": "Si",
                "FIMPLANTACIONCHIP": "2023-04-15",
                "NombreFoto": "luna.jpg",
            },
        ),
        ("POST", "/animales/abc-123/delete", None),
    ],
    ids=["create", "update", "delete"],
)
async def test_write_route_rejects_reader_with_403(
    client: httpx.AsyncClient,
    animals_spy: _AnimalsRouteSpy,
    method: str,
    path: str,
    form_data: dict[str, str] | None,
) -> None:
    """Reader rol is forbidden on every animales write route (issue #144).

    Before #144, a reader could POST/PUT/DELETE on animales because no
    route enforced the rol. The fix layers ``require_writer_user`` over
    ``require_authorized_user``; the reader is rejected with 403 BEFORE
    the handler runs, so no SQL is emitted and no template is rendered.
    """
    animals_spy.auth_reval_rol = "reader"
    _login_as_reader(client)

    response = await make_csrf_request(
        client, method, path, form_data=form_data
    )

    assert response.status_code == 403, (
        f"reader rol MUST be rejected on write routes; got {response.status_code} "
        f"on {method} {path}"
    )
    # The 403 short-circuits BEFORE any domain SQL — the spy must NOT
    # have captured any animal write SQL.
    write_queries = [
        q
        for q in animals_spy.captured_queries
        if "UPDATE animales" in q or "INSERT INTO animales" in q
    ]
    assert not write_queries, (
        f"reader POST MUST NOT emit animal SQL; got: {write_queries!r}"
    )


# --- chip change (issue #29) ------------------------------------------------
# Route-level chip change tests require full SQL saga mocking (get_animal_by_id
# PLUS chip-lookup SELECT PLUS 2+ UPDATE statements). The _AnimalsRouteSpy
# cannot distinguish between these multiple statement types in a single test.
# Service-level coverage for change_animal_chip lives in test_chip_cascade.py.
# TODO(#N): add route-level chip tests with proper multi-statement spy support.
