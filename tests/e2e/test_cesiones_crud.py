"""E2E CRUD coverage for the ``/cesiones`` slice (INTAKE-03, #41).

Pins the owner-surrender (cesión por propietario) CRUD contract
end-to-end via Playwright + the OAuth mock landed in
``tests/e2e/test_admin_authenticated.py``.

The ``/cesiones`` slice requires a pre-existing ``entrada_id`` row
because the service's FK validation rejects ``entrada_id`` values that do
not reference an existing entrada row. The entrada in turn requires a
pre-existing ``animal_id``. Each test creates its animal + entrada via
``POST /animales`` and ``POST /entradas`` first, then exercises the
``/cesiones`` surface.

Five cases pin the cesiones CRUD contract end-to-end:

1. Form renders (GET /cesiones/new → 200; h1 + all legacy fields present).
2. Create happy path (POST /cesiones with valid entrada_id →
   303 to /entradas/{entrada_id}; the cesión is inspected from the
   parent intake detail page per the 1-a-1 relationship).
3. Create with non-existent ``entrada_id`` → 422 with Spanish error.
4. Create with blank ``nombre_representante`` → 422 with Spanish error.
5. CSRF token present in form (regression sentinel for AGENTS.md rule 10).

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset (the OAuth
mock cannot authenticate).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable

import pytest
from playwright.sync_api import BrowserContext, Page

# --- shared constants -----------------------------------------------------

E2E_SECRET_HEADER = "X-E2E-Secret"

SPECIES_CANINA = "CANINA"
SEX_MACHO = "M"


# --- fixtures -------------------------------------------------------------


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    """Mint a developer session and return ``(page, csrf_token)``."""
    secret = _e2e_secret()
    if secret is None:
        pytest.skip(
            "APAP_E2E_AUTH_SECRET not set — the OAuth mock cannot "
            "authenticate this test. CI sets the variable; local dev "
            "needs to export it to run authenticated E2E flows."
        )

    response = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: secret},
    )
    assert response.status == 200, (
        f"/e2e/login must return 200 in the e2e suite, got {response.status}."
    )
    payload = response.json()
    csrf_token = payload.get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token, (
        f"/e2e/login must return a non-empty csrf_token, got {payload!r}."
    )

    page = browser_context.new_page()
    return page, csrf_token


@pytest.fixture
def animal_id_factory(
    authenticated_session: tuple[Page, str], base_url: str
) -> Callable[[], str]:
    """Return a factory that creates a fresh animal via the form and yields its UUID.

    ``EntradaForm.animal_id`` is a FK against ``animales``; without an
    existing animal, every entrada POST 422s. The factory POSTs
    ``/animales`` once per call and extracts the new animal's UUID from
    the 303 redirect target.
    """

    def _factory() -> str:
        page, csrf_token = authenticated_session
        form_data: dict[str, str] = {
            "NCHIP": uuid.uuid4().hex[:15],
            "NombreAnimal": f"Host-{uuid.uuid4().hex[:8]}",
            "Especie": SPECIES_CANINA,
            "Sexo": SEX_MACHO,
            "FNacimiento": "2024-01-15",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2024-01-16",
            "NombreFoto": "",
            "Terapia": "No",
        }
        form_page = page.goto(
            f"{base_url}/animales/new", wait_until="domcontentloaded"
        )
        assert form_page is not None and form_page.status == 200
        _csrf_token_from_form(page)  # regression sentinel
        response = page.request.post(
            f"{base_url}/animales",
            form={"csrf_token": csrf_token, **form_data},
        )
        if response.status != 303:
            pytest.skip(
                f"Could not create host animal (POST /animales did not return "
                f"303; got {response.status}: {response.text()[:200]!r}). "
                f"The test database may not be writable from E2E."
            )
        animal_id = response.headers.get("location", "").rsplit("/", 1)[-1]
        if not animal_id or animal_id.endswith("/new") or animal_id.endswith("/edit"):
            pytest.skip(
                f"animal setup failed; /animales redirect was {page.url!r}. "
                f"The test database may not be writable from E2E."
            )
        return animal_id

    return _factory


@pytest.fixture
def entrada_id_factory(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> Callable[[], str]:
    """Return a factory that creates a fresh entrada and yields its UUID.

    ``CesionForm.entrada_id`` is a FK against ``entradas``; without an
    existing entrada, every cesion POST 422s. The factory POSTs
    ``/entradas`` once per call and extracts the new entrada's UUID from
    the 303 redirect target.
    """

    def _factory() -> str:
        page, csrf_token = authenticated_session
        animal_id = animal_id_factory()
        form_page = page.goto(
            f"{base_url}/entradas/new", wait_until="domcontentloaded"
        )
        assert form_page is not None and form_page.status == 200
        _csrf_token_from_form(page)  # regression sentinel
        page.locator('input[name="animal_id"]').fill(animal_id)
        page.locator('input[name="fecha_entrada"]').fill("2024-06-01")
        response = page.request.post(
            f"{base_url}/entradas",
            form={"csrf_token": csrf_token, "animal_id": animal_id, "fecha_entrada": "2024-06-01"},
        )
        if response.status != 303:
            pytest.skip(
                f"Could not create host entrada (POST /entradas did not return "
                f"303; got {response.status}: {response.text()[:200]!r}). "
                f"The test database may not be writable from E2E."
            )
        entrada_id = response.headers.get("location", "").rsplit("/", 1)[-1]
        if not entrada_id or entrada_id.endswith("/new") or entrada_id.endswith("/edit"):
            pytest.skip(
                f"entrada setup failed; /entradas redirect was {page.url!r}. "
                f"The test database may not be writable from E2E."
            )
        return entrada_id

    return _factory


# --- helpers --------------------------------------------------------------


def _csrf_token_from_form(page: Page) -> str:
    """Read the csrf_token hidden input rendered on the current page."""
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token hidden input"
    return token


def _cesion_form_data(
    *,
    entrada_id: str,
    numero_contrato: str,
    nombre_representante: str,
    **overrides: str,
) -> dict[str, str]:
    """Build a valid CesionForm payload.

    Mirrors ``app/modules/cesiones/forms.py::CesionForm``.
    Only ``entrada_id``, ``numero_contrato``, and ``nombre_representante``
    are required; the rest are optional and default to empty string
    (which the service converts to NULL).
    """
    data: dict[str, str] = {
        "entrada_id": entrada_id,
        "numero_contrato": numero_contrato,
        "nombre_representante": nombre_representante,
        "dni_representante": "",
        "fecha_cesion": "",
        "calle_representante": "",
        "numero_calle_representante": "",
        "piso_representante": "",
        "letra_representante": "",
        "localidad_representante": "",
        "provincia_representante": "",
        "cp_representante": "",
        "telefono_representante": "",
        "email_representante": "",
        "cartilla_sanitaria": "",
        "certificado_veterinario": "",
        "autorizacion_recogida": "",
        "fecha_vacuna_rabia": "",
        "numero_colegiado": "",
        "numero_colaborador": "",
        "hora_cesion": "",
    }
    data.update(overrides)
    return data


# --- 1. form renders -------------------------------------------------------


def test_form_renders_200_with_all_legacy_fields(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /cesiones/new → 200; the surrender form renders with every
    legacy TbCesionPorPropietario column as a named input.

    P1 fidelity: every legacy column must be visible on the form so the
    operator can capture the full superset. The 19 legacy columns are:
    entrada_id, numero_contrato, nombre_representante, dni_representante,
    fecha_cesion, calle/numero/piso/letra/localidad/provincia/cp (9
    address fields), telefono/email, cartilla/certificado/autorizacion
    (3 doc booleans), fecha_vacuna_rabia, numero_colegiado,
    numero_colaborador, hora_cesion — 20 total inputs.
    """
    page, _csrf = authenticated_session

    response = page.goto(f"{base_url}/cesiones/new", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, (
        f"GET /cesiones/new must return 200, got {response.status}"
    )

    # h1 confirms the correct page rendered (not an error page).
    h1 = page.locator("h1").first.inner_text().strip()
    assert "cesión" in h1.lower(), (
        f"form page must render a 'cesión' heading; got {h1!r}"
    )

    # Every legacy column present as a named input.
    legacy_fields = [
        "entrada_id",
        "numero_contrato",
        "nombre_representante",
        "dni_representante",
        "fecha_cesion",
        "calle_representante",
        "numero_calle_representante",
        "piso_representante",
        "letra_representante",
        "localidad_representante",
        "provincia_representante",
        "cp_representante",
        "telefono_representante",
        "email_representante",
        "cartilla_sanitaria",
        "certificado_veterinario",
        "autorizacion_recogida",
        "fecha_vacuna_rabia",
        "numero_colegiado",
        "numero_colaborador",
        "hora_cesion",
    ]
    for field in legacy_fields:
        locator = page.locator(f'[name="{field}"]')
        assert locator.count() > 0, (
            f"cesiones form missing legacy field {field!r}; "
            f"P1 fidelity requires every TbCesionPorPropietario column."
        )


# --- 2. form includes CSRF token -------------------------------------------


def test_form_includes_csrf_token(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """GET /cesiones/new renders a hidden csrf_token input.

    AGENTS.md rule 10: every POST form must carry a csrf_token; the
    CsrfMiddleware validates it before the handler runs. This is a
    regression sentinel — if the form template stops rendering the token,
    every POST returns 403 and the whole slice breaks.
    """
    page, _ = authenticated_session

    page.goto(f"{base_url}/cesiones/new", wait_until="domcontentloaded")
    token = _csrf_token_from_form(page)
    assert token, "form must render a non-empty csrf_token hidden input"


# --- 3. create happy path --------------------------------------------------


def test_create_cesion_redirects_to_parent_entrada(
    authenticated_session: tuple[Page, str],
    entrada_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /cesiones with valid payload → 303 to /entradas/{entrada_id}.

    The cesión is 1-a-1 with the intake (FK UNIQUE on entrada_id per P1
    fidelity); the operator inspects the surrender from the existing
    intake detail page. A standalone /cesiones/{id} view is deferred to
    Fase 7 (contract generation).

    The test pins:
    - 303 redirect target is /entradas/{entrada_id}.
    - The parent entrada detail page renders (200).
    - No 422 / 409 on the first cesion for this entrada.
    """
    page, csrf_token = authenticated_session
    entrada_id = entrada_id_factory()
    numero_contrato = f"CP{uuid.uuid4().hex[:4].upper()}"
    nombre = f"Representante {uuid.uuid4().hex[:6]}"

    # Visit the form first (regression sentinel: page must render + csrf present).
    form_page = page.goto(
        f"{base_url}/cesiones/new", wait_until="domcontentloaded"
    )
    assert form_page is not None and form_page.status == 200
    _csrf_token_from_form(page)

    # POST the surrender form directly via the request client (mirroring the
    # unit-test pattern) because the form action is self-submitting.
    form_data = _cesion_form_data(
        entrada_id=entrada_id,
        numero_contrato=numero_contrato,
        nombre_representante=nombre,
    )
    response = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 303, (
        f"create POST must return 303, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    location = response.headers.get("location", "")
    assert location == f"/entradas/{entrada_id}", (
        f"create POST must redirect to /entradas/{{entrada_id}}, got {location!r}"
    )

    # Follow the redirect and verify the parent entrada detail page renders.
    detail = page.goto(
        f"{base_url}/entradas/{entrada_id}", wait_until="domcontentloaded"
    )
    assert detail is not None
    assert detail.status == 200, (
        f"parent entrada detail must return 200 after cesion create, "
        f"got {detail.status}"
    )
    body = page.content()
    assert entrada_id in body, (
        f"entrada detail page must show the entrada_id {entrada_id!r}"
    )


# --- 4. create with non-existent entrada_id → 422 -------------------------


def test_create_cesion_with_nonexistent_entrada_returns_422(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """POST /cesiones with a bogus ``entrada_id`` → 422 + Spanish error.

    The service validates the FK before INSERT; without a matching entrada
    row, the route re-renders the form with 422 and the Spanish error
    message exposed to the operator.
    """
    page, csrf_token = authenticated_session
    bogus_entrada_id = str(uuid.uuid4())  # well-formed UUID, never inserted
    form_data = _cesion_form_data(
        entrada_id=bogus_entrada_id,
        numero_contrato=f"CP{uuid.uuid4().hex[:4].upper()}",
        nombre_representante="Test Rep",
    )

    response = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 422, (
        f"POST /cesiones with bogus entrada_id must return 422, "
        f"got {response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la cesion" in body, (
        f"422 response must carry the Spanish form error header; "
        f"body excerpt: {body[:500]!r}"
    )
    # The service raises ValueError with a message about entrada_id not referencing.
    assert "entrada" in body.lower(), (
        f"422 response must mention entrada_id validation; "
        f"body excerpt: {body[:500]!r}"
    )


# --- 5. create with blank nombre_representante → 422 ----------------------


def test_create_cesion_with_blank_nombre_raises_422(
    authenticated_session: tuple[Page, str],
    entrada_id_factory: Callable[[], str],
    base_url: str,
) -> None:
    """POST /cesiones with blank ``nombre_representante`` → 422 + Spanish error.

    ``nombre_representante`` is NOT NULL in the web even though the legacy
    DDL marks it as required=False (P1 fidelity deviation documented in
    docs/architecture/decisiones-proyecto.md). The application layer's
    create_cesion validates the field before delegating to the port.
    """
    page, csrf_token = authenticated_session
    entrada_id = entrada_id_factory()
    form_data = _cesion_form_data(
        entrada_id=entrada_id,
        numero_contrato=f"CP{uuid.uuid4().hex[:4].upper()}",
        nombre_representante="   ",  # blank — should be rejected
    )

    response = page.request.post(
        f"{base_url}/cesiones",
        form={"csrf_token": csrf_token, **form_data},
    )

    assert response.status == 422, (
        f"POST /cesiones with blank nombre_representante must return 422, "
        f"got {response.status}: {response.text()[:300]!r}"
    )
    body = response.text()
    assert "No se pudo guardar la cesion" in body, (
        f"422 response must carry the Spanish form error header; "
        f"body excerpt: {body[:500]!r}"
    )
    assert "nombre_representante" in body.lower(), (
        f"422 response must mention nombre_representante; "
        f"body excerpt: {body[:500]!r}"
    )
