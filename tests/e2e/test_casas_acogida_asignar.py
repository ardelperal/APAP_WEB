"""E2E coverage for the FOSTER-03 foster assignment gate (#45).

Pins the foster assignment gate contract end-to-end via Playwright + the
OAuth mock landed in ``tests/e2e/test_admin_authenticated.py``. The
``authenticated_session`` fixture mints a developer session (the mock's
default rol — see ``app/core/e2e_auth.py::MOCK_USER_ROL``) which
satisfies every gate the assignment routes install: ``require_writer_user``
on POST ``/asignar``, ``require_developer_user`` on GET ``/overrides``.
The fixture returns a ``(Page, csrf_token)`` tuple so the csrf_token
can be threaded into the form-encoded POSTs (the form template
``casas_acogida/asignar.html`` renders ``<input type="hidden"
name="csrf_token" value="...">``; we POST via the request client to
capture status codes, so the token must be supplied explicitly).

Six cases:

1. GET /casas-acogida/{id}/asignar → 200 with the casa's header
   subtitle (``Capacidad:`` + ``Especie preferente:``) + form action
   targeting ``/casas-acogida/{id}/asignar`` + ``animal_id`` input.
2. POST /casas-acogida/{id}/asignar with incompatible especie → 422
   with the gate's reason (``"la casa solo admite FELINA, no CANINA"``)
   visible in the ``"No se puede asignar"`` alert.
3. POST /casas-acogida/{id}/asignar with compatible especie → 303 to
   ``/acogidas/new?animal_id=X&casa_acogida_id=Y`` (NO override_id —
   only the ``admit_with_warning`` branch threads that for #142
   atomicity).
4. POST with capacidad excedida (admit_with_warning) + empty motivo →
   422 with the warning visible. SKIPPED — see docstring below.
5. POST with capacidad excedida + motivo filled → 303 with
   ``override_id`` in URL. SKIPPED — see docstring below.
6. GET /casas-acogida/{id}/overrides → 200, lists overrides (the
   empty-state ``"Sin overrides registrados"`` message OR the table
   of overrides, depending on whether the casa has any).

Cases 4 and 5 require the gate to evaluate as ``admit_with_warning``,
which in turn requires at least one active ``acogidas`` row at the
target casa meeting ``count >= capacidad``. Creating that active stay
requires the FOSTER-02 ``POST /acogidas`` flow (its own end-to-end
setup with the animal state-machine + ``fecha_inicio``). Per the task
instructions ("Skip tests that need complex setup with descriptive
skip reason"), both skip rather than reproduce that flow inline. The
unit-level coverage of ``admit_with_warning`` lives in
``tests/test_foster_assignment.py`` (decision matrix) and
``tests/test_foster_assignment_routes.py::test_post_asignar_admit_with_warning_*``
(HTTP + SQL shape) and pins the contract directly.

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

# Species enum values (per app/modules/animals/domain/animal.py::Especie).
# The /casas-acogida?especie= filter and the foster assignment gate both
# compare against these uppercase legacy values.
SPECIES_CANINA = "CANINA"
SPECIES_FELINA = "FELINA"
SEX_MACHO = "M"


# --- fixtures -------------------------------------------------------------


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or ``None`` if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    """Mint a developer session and return ``(page, csrf_token)``.

    The developer rol (the OAuth mock's default) satisfies every
    gate the assignment routes install: ``require_authorized_user`` on
    GET ``/asignar``, ``require_writer_user`` on POST ``/asignar``
    (developer >= writer), ``require_developer_user`` on GET
    ``/overrides`` (the override list is developer-only per the P1
    risk-review fix — the ``motivo`` column may carry PII).
    """
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


# --- helpers --------------------------------------------------------------


def _csrf_token_from_form(page: Page) -> str:
    """Read the csrf_token hidden input rendered on the current page."""
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    assert token, "every form page must render a non-empty csrf_token hidden input"
    return token


def _casa_form_data(name_suffix: str, *, especie_preferente: str = "") -> dict[str, str]:
    """Build a valid CasaAcogidaForm payload with a unique suffix."""
    return {
        "nombre": f"Casa-{name_suffix}",
        "apellidos": f"Apellido-{name_suffix}",
        "dni_acogedor": "",
        "calle": f"Calle-{name_suffix}",
        "numero": "12",
        "piso": "",
        "letra": "",
        "localidad": "Madrid",
        "provincia": "Madrid",
        "cp": "28001",
        "telefono": "600123456",
        "telefono2": "",
        "email": "",
        "vinculacion": "",
        "caracteristicas": "",
        "coche": "Sí",
        "especie_preferente": especie_preferente,
        "observaciones": "",
        "capacidad": "3",
    }


def _create_casa(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    name_suffix: str,
    especie_preferente: str = "",
    capacidad: str = "3",
) -> str:
    """POST /casas-acogida and return the new casa's UUID. Skips on failure."""
    data = _casa_form_data(name_suffix, especie_preferente=especie_preferente)
    data["capacidad"] = capacidad
    response = page.request.post(
        f"{base_url}/casas-acogida",
        form={"csrf_token": csrf_token, **data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create casa (POST /casas-acogida did not return 303; "
            f"got {response.status}: {response.text()[:200]!r}). The test "
            f"database may not be writable from E2E."
        )
    location = response.headers.get("location", "")
    casa_id = location.rsplit("/", 1)[-1]
    if not casa_id or "/new" in casa_id or "/edit" in casa_id:
        pytest.skip(
            f"casa setup failed; /casas-acogida redirect was {location!r}."
        )
    return casa_id


@pytest.fixture
def casa_factory(
    authenticated_session: tuple[Page, str], base_url: str
) -> Callable[..., str]:
    """Return a factory that creates a fresh casa and yields its UUID."""

    def _factory(*, especie_preferente: str = "", capacidad: str = "3") -> str:
        page, csrf_token = authenticated_session
        suffix = f"{uuid.uuid4().hex[:8]}"
        return _create_casa(
            page,
            csrf_token,
            base_url,
            name_suffix=suffix,
            especie_preferente=especie_preferente,
            capacidad=capacidad,
        )

    return _factory


def _animal_form_data(name_suffix: str, *, especie: str) -> dict[str, str]:
    """Build a valid AnimalForm payload with a unique chip + name suffix.

    Mirrors the factory in ``tests/e2e/test_animales_crud.py``
    (9 required fields + a couple of optional ones so Pydantic does
    not complain).
    """
    return {
        "NCHIP": uuid.uuid4().hex[:15],
        "NombreAnimal": f"Animal-{name_suffix}",
        "Especie": especie,
        "Sexo": SEX_MACHO,
        "FNacimiento": "2024-01-15",
        "TraeNChip": "Si",
        "FIMPLANTACIONCHIP": "2024-01-16",
        "NombreFoto": "",
        "Terapia": "No",
        "Raza": "Mestizo",
        "Color": "Negro",
    }


def _create_animal(
    page: Page,
    csrf_token: str,
    base_url: str,
    *,
    especie: str,
) -> str:
    """POST /animales and return the new animal's UUID. Skips on failure.

    The foster assignment gate calls ``get_animal_by_id`` (FOSTER-03
    Paso 1) to load the animal; without an existing animales row,
    the gate raises ``ValueError("el animal no existe o no está
    activo")`` and the handler returns 422. To exercise the
    species-match path of the gate, we need a real animal whose
    ``Especie`` matches (or mismatches) the casa's
    ``especie_preferente``.
    """
    suffix = f"{uuid.uuid4().hex[:8]}"
    form_data = _animal_form_data(suffix, especie=especie)

    form_page = page.goto(f"{base_url}/animales/new", wait_until="domcontentloaded")
    assert form_page is not None
    assert form_page.status == 200
    _csrf_token_from_form(page)  # regression sentinel

    response = page.request.post(
        f"{base_url}/animales",
        form={"csrf_token": csrf_token, **form_data},
    )
    if response.status != 303:
        pytest.skip(
            f"Could not create host animal (POST /animales did not return 303; "
            f"got {response.status}: {response.text()[:200]!r}). The test "
            f"database may not be writable from E2E."
        )
    animal_id = response.headers.get("location", "").rsplit("/", 1)[-1]
    if not animal_id or animal_id.endswith("/new") or animal_id.endswith("/edit"):
        pytest.skip(
            f"animal setup failed; /animales redirect was "
            f"{response.headers.get('location')!r}."
        )
    return animal_id


# --- 1. GET asignar form ---------------------------------------------------


def test_get_asignar_renders_form_with_casa_info(
    authenticated_session: tuple[Page, str],
    base_url: str,
    casa_factory: Callable[..., str],
) -> None:
    """GET /casas-acogida/{id}/asignar → 200 with the casa info + form fields.

    Pins the GET surface: the route loads the casa (404 if missing)
    and renders ``casas_acogida/asignar.html`` with the casa's header
    subtitle (``Especie preferente:`` + ``Capacidad:``), the form
    posting back to ``/casas-acogida/{id}/asignar``, and the
    ``animal_id`` input + csrf_token hidden field.

    ``motivo`` is NOT in the initial render — the textarea only
    appears after a warning fires (per the template's
    ``{% if warning %}`` block).
    """
    page, _ = authenticated_session
    casa_id = casa_factory()

    response = page.goto(
        f"{base_url}/casas-acogida/{casa_id}/asignar", wait_until="domcontentloaded"
    )

    assert response is not None
    assert response.status == 200, (
        f"/casas-acogida/{{id}}/asignar must return 200, got {response.status}"
    )
    body = page.content()
    assert "Asignar animal" in body, (
        f"asignar page must show the 'Asignar animal' h1; body excerpt: {body[:500]!r}"
    )
    assert "Capacidad:" in body, (
        f"asignar page must show the casa's 'Capacidad:' in the subtitle; "
        f"body excerpt: {body[:500]!r}"
    )
    assert f'action="/casas-acogida/{casa_id}/asignar"' in body, (
        f"asignar form must POST to /casas-acogida/{{id}}/asignar; "
        f"body excerpt: {body[:500]!r}"
    )
    assert 'name="animal_id"' in body, (
        f"asignar form must render an animal_id input; body excerpt: {body[:500]!r}"
    )
    assert 'name="csrf_token"' in body, (
        f"asignar form must render a csrf_token hidden input; body excerpt: {body[:500]!r}"
    )


# --- 2. POST incompatible especie → 422 -----------------------------------


def test_post_asignar_block_returns_422_with_reason(
    authenticated_session: tuple[Page, str],
    base_url: str,
    casa_factory: Callable[..., str],
) -> None:
    """POST with incompatible especie → 422 with the gate's block reason.

    Setup: a casa with ``especie_preferente=FELINA`` + an animal with
    ``Especie=CANINA``. The gate evaluates the species check (Paso 3)
    and returns ``AssignmentDecision(decision="block",
    reason="la casa solo admite FELINA, no CANINA")``. The handler
    re-renders the form with status 422 and the reason visible in the
    ``"No se puede asignar"`` alert.
    """
    page, csrf_token = authenticated_session
    casa_id = casa_factory(especie_preferente=SPECIES_FELINA)
    animal_id = _create_animal(page, csrf_token, base_url, especie=SPECIES_CANINA)

    # Visit the form first so the test mirrors the operator flow (and
    # the csrf_token we submit is the one currently bound to the
    # session).
    form_page = page.goto(
        f"{base_url}/casas-acogida/{casa_id}/asignar", wait_until="domcontentloaded"
    )
    assert form_page is not None
    assert form_page.status == 200
    asignar_csrf = _csrf_token_from_form(page)

    # POST directly to the action URL (the form template's
    # ``action="/casas-acogida/{{ casa.id }}/asignar"`` matches).
    response = page.request.post(
        f"{base_url}/casas-acogida/{casa_id}/asignar",
        form={"csrf_token": asignar_csrf, "animal_id": animal_id, "motivo": ""},
    )

    assert response.status == 422, (
        f"POST with incompatible especie must return 422, got {response.status}"
    )
    body = response.text()
    # Gate's block reason (per app/modules/foster/assignment.py::
    # evaluate_assignment Paso 3): "la casa solo admite {especie}, no
    # {animal.especie}". The route renders it via the
    # ``"No se puede asignar"`` alert in ``casas_acogida/asignar.html``.
    assert "la casa solo admite FELINA, no CANINA" in body, (
        f"422 response must surface the gate's block reason; "
        f"body excerpt: {body[:500]!r}"
    )
    assert "No se puede asignar" in body, (
        f"422 response must carry the Spanish alert header; "
        f"body excerpt: {body[:500]!r}"
    )


# --- 3. POST compatible especie → 303 -------------------------------------


def test_post_asignar_admit_redirects_to_acogidas_new(
    authenticated_session: tuple[Page, str],
    base_url: str,
    casa_factory: Callable[..., str],
) -> None:
    """POST with compatible especie → 303 to /acogidas/new with query params.

    Setup: a casa with ``especie_preferente=CANINA`` + an animal with
    ``Especie=CANINA`` + ``capacidad=3`` (no active stays yet, so the
    capacity check passes with ``count=0 < capacidad=3``). The gate
    returns ``AssignmentDecision(decision="admit")``; the handler
    redirects to ``/acogidas/new?animal_id=X&casa_acogida_id=Y`` so
    the operator can complete the estancia create (FOSTER-02 flow).

    The admit path MUST NOT carry ``override_id`` — only the
    ``admit_with_warning`` branch threads that for #142 atomicity
    (linking the foster_capacity_overrides row to the new estancia).
    """
    page, csrf_token = authenticated_session
    casa_id = casa_factory(especie_preferente=SPECIES_CANINA)
    animal_id = _create_animal(page, csrf_token, base_url, especie=SPECIES_CANINA)

    form_page = page.goto(
        f"{base_url}/casas-acogida/{casa_id}/asignar", wait_until="domcontentloaded"
    )
    assert form_page is not None
    assert form_page.status == 200
    asignar_csrf = _csrf_token_from_form(page)

    response = page.request.post(
        f"{base_url}/casas-acogida/{casa_id}/asignar",
        form={"csrf_token": asignar_csrf, "animal_id": animal_id, "motivo": ""},
    )

    assert response.status == 303, (
        f"POST with compatible especie must return 303, got {response.status}"
    )
    location = response.headers.get("location", "")
    assert location.startswith("/acogidas/new?"), (
        f"admit must redirect to /acogidas/new, got {location!r}"
    )
    assert f"animal_id={animal_id}" in location, (
        f"redirect URL must carry animal_id={animal_id!r}, got {location!r}"
    )
    assert f"casa_acogida_id={casa_id}" in location, (
        f"redirect URL must carry casa_acogida_id={casa_id!r}, got {location!r}"
    )
    assert "override_id=" not in location, (
        f"admit redirect must NOT carry override_id "
        f"(only admit_with_warning does for #142 atomicity); got {location!r}"
    )


# --- 4. POST condicionada + empty motivo → 422 ----------------------------


def test_post_asignar_admit_with_warning_empty_motivo_returns_422() -> None:
    """SKIPPED — admit_with_warning requires an active stay at the casa.

    The ``admit_with_warning`` branch of the gate requires the count
    of active stays at the target casa to be ``>= capacidad``
    (``app/modules/foster/assignment.py::_ACTIVE_COUNT_PREFERRED_SQL``).
    Without an active ``acogidas`` row, the gate evaluates ``admit``
    (case 3) and never enters the warning branch — so this test
    cannot exercise the empty-motivo contract without first
    pre-populating an active estancia, which is the FOSTER-02 flow
    (``POST /acogidas``, its own E2E setup with state-machine +
    ``fecha_inicio``).

    The unit-level coverage in
    ``tests/test_foster_assignment_routes.py::test_post_asignar_admit_with_warning_con_motivo_vacio``
    pins the 422 + warning-visible contract directly (mocked
    ``evaluate_assignment`` returns ``admit_with_warning`` regardless
    of the underlying SQL count).
    """
    pytest.skip(
        "admit_with_warning requires an active stay at the target casa "
        "exceeding capacidad; that setup belongs to the FOSTER-02 E2E "
        "flow (POST /acogidas), not this foster-gate file. Unit-level "
        "coverage in "
        "tests/test_foster_assignment_routes.py::test_post_asignar_admit_with_warning_con_motivo_vacio "
        "pins the 422 + warning-visible contract."
    )


# --- 5. POST condicionada + motivo filled → 303 ----------------------------


def test_post_asignar_admit_with_warning_motivo_filled_redirects_with_override_id() -> None:
    """SKIPPED — same setup constraint as test 4.

    The ``admit_with_warning`` branch threads ``override_id=<uuid>``
    into the redirect URL for #142 atomicity (linking the
    foster_capacity_overrides row with the estancia resultante). The
    branch only fires when ``count >= capacidad`` in the casa, which
    requires an active stay — the FOSTER-02 flow's setup, not this
    file's.

    The unit-level coverage in
    ``tests/test_foster_assignment_routes.py::test_post_asignar_admit_with_warning_con_motivo_graba_override_y_redirect``
    pins the 303 + ``override_id`` in URL contract directly.
    """
    pytest.skip(
        "admit_with_warning requires an active stay at the target casa "
        "exceeding capacidad; see "
        "test_post_asignar_admit_with_warning_empty_motivo_returns_422 "
        "for the same setup constraint. Unit-level coverage in "
        "tests/test_foster_assignment_routes.py::test_post_asignar_admit_with_warning_con_motivo_graba_override_y_redirect "
        "pins the 303 + override_id contract."
    )


# --- 6. GET overrides -----------------------------------------------------


def test_get_overrides_lists_historical_overrides(
    authenticated_session: tuple[Page, str],
    base_url: str,
    casa_factory: Callable[..., str],
) -> None:
    """GET /casas-acogida/{id}/overrides → 200, lists overrides.

    Pins the developer-only override list: the route loads the casa
    (404 if missing), queries ``foster_capacity_overrides`` for the
    casa id, and renders the table OR the ``"Sin overrides
    registrados"`` empty-state message depending on whether the casa
    has any historical overrides.

    This test creates a fresh casa and does NOT trigger any override,
    so the empty-state is the expected rendering. The
    unit-level coverage in
    ``tests/test_foster_assignment_routes.py::test_get_overrides_*``
    covers both branches (table + empty-state).
    """
    page, _ = authenticated_session
    casa_id = casa_factory()

    response = page.goto(
        f"{base_url}/casas-acogida/{casa_id}/overrides", wait_until="domcontentloaded"
    )

    assert response is not None
    assert response.status == 200, (
        f"/casas-acogida/{{id}}/overrides must return 200, got {response.status}"
    )
    body = page.content()
    assert "Overrides de capacidad" in body, (
        f"overrides page must render the 'Overrides de capacidad' h1; "
        f"body excerpt: {body[:500]!r}"
    )
    # Either the empty-state OR the table is rendered — a fresh casa
    # has no overrides so the empty-state is the expected rendering,
    # but we accept either to stay robust against future changes that
    # pre-populate overrides.
    assert (
        "Sin overrides registrados" in body or "<table" in body
    ), (
        f"overrides page must render the empty-state OR the table; "
        f"body excerpt: {body[:500]!r}"
    )
