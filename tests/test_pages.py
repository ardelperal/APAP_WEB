"""Tests for protected top-level HTML routes."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from app.core.config import get_settings
from app.core.session import session_cookie_name, write_session


def _login_as_authorized_user(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "user@example.com",
            "rol": "key_user",
            "user_id": "u-user",
            "is_authorized": True,
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_unauthorized_user(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "inactive@example.com",
            "rol": "key_user",
            "user_id": "u-inactive",
            "is_authorized": False,
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


async def test_index_redirects_anonymous_users_to_login(
    client: httpx.AsyncClient,
) -> None:
    """``GET /`` is user-facing and must require login.

    Anonymous visitors must be bounced to /login before any landing
    copy renders — the marketing modules list (Animales, Voluntarios,
    Entradas) is only meaningful behind the auth gate, and exposing
    the page publicly invites unauthenticated probing of the
    authenticated app routes it links to.

    The middleware (PR-5B2 + hardening-2026-q2 slice 5B1) enforces
    this before route/form validation so even malformed anonymous
    POSTs to the same handler can't 422-leak the app surface.
    """
    response = await client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_index_renders_html(client: httpx.AsyncClient) -> None:
    """``GET /`` returns an HTML page rendered from base.html + index.html."""
    _login_as_authorized_user(client)

    response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_index_links_compiled_css(client: httpx.AsyncClient) -> None:
    """The landing page links the compiled Tailwind CSS asset."""
    _login_as_authorized_user(client)

    response = await client.get("/")

    assert "/static/css/output.css" in response.text


async def test_index_mentions_product_name(client: httpx.AsyncClient) -> None:
    """The landing page shows the APAP product name."""
    _login_as_authorized_user(client)

    response = await client.get("/")

    assert "APAP Alcalá" in response.text


async def test_index_renders_operational_dashboard_cards(
    client: httpx.AsyncClient,
) -> None:
    """The home page is an APAP operations dashboard, not a technical landing."""
    _login_as_authorized_user(client)

    response = await client.get("/")

    assert response.status_code == 200
    expected_labels = [
        "Animales incoherentes",
        "Pendientes de entrada",
        "Pendientes de nueva situación",
        "Pendientes de chip",
        "Cambio de titular pendiente",
        "Fallecidos sin RIAC",
        "Impresos por entregar",
        "Impresos entregados no recibidos",
        "Seguimientos activos",
        "Seguimientos totales",
    ]
    for label in expected_labels:
        assert label in response.text
    assert response.text.count("Pendiente de conectar") >= len(expected_labels)


async def test_user_facing_pages_do_not_render_internal_stack_copy(
    client: httpx.AsyncClient,
) -> None:
    """Rendered product pages must not expose implementation or migration copy."""
    _login_as_authorized_user(client)

    response = await client.get("/")

    assert response.status_code == 200
    forbidden = re.compile(
        r"\b(legacy|migration|FastAPI|HTMX|InsForge|Access|stack|internal)\b|migraci[oó]n|APAP_WEB",
        flags=re.IGNORECASE,
    )
    assert forbidden.search(response.text) is None


def test_key_template_sources_do_not_include_internal_ui_copy() -> None:
    """Source templates for current user-facing pages avoid internal product copy."""
    root = Path(__file__).resolve().parents[1]
    templates = [
        root / "app" / "templates" / "base.html",
        root / "app" / "templates" / "index.html",
        root / "app" / "templates" / "login.html",
        root / "app" / "templates" / "unauthorized.html",
        root / "app" / "templates" / "animales" / "detail.html",
        root / "app" / "templates" / "animales" / "form.html",
        root / "app" / "templates" / "animales" / "list.html",
        root / "app" / "templates" / "entradas" / "detail.html",
        root / "app" / "templates" / "entradas" / "form.html",
        root / "app" / "templates" / "entradas" / "list.html",
        root / "app" / "templates" / "voluntarios" / "detail.html",
        root / "app" / "templates" / "voluntarios" / "form.html",
        root / "app" / "templates" / "voluntarios" / "list.html",
    ]
    forbidden = re.compile(
        r"\b(legacy|migration|FastAPI|HTMX|InsForge|Access|stack|internal|intern[oa]s?)\b|"
        r"migraci[oó]n|APAP_WEB|Copy provisional|Fase \d|esqueleto",
        flags=re.IGNORECASE,
    )

    for template in templates:
        source = template.read_text(encoding="utf-8")
        visible_source = re.sub(r"\{#.*?#\}", "", source, flags=re.DOTALL)
        assert forbidden.search(visible_source) is None, template


def test_animal_form_uses_professional_optional_section_label() -> None:
    """The animal form names optional fields with product wording."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "templates" / "animales" / "form.html").read_text(
        encoding="utf-8"
    )

    assert "Datos complementarios del animal" in source


def test_animal_templates_use_human_readable_visible_labels() -> None:
    """Animal pages show Spain-Spanish labels, not internal column names."""
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (
            root / "app" / "templates" / "animales" / template
        ).read_text(encoding="utf-8")
        for template in ("detail.html", "form.html", "list.html")
    )

    expected_labels = [
        "N.º de chip",
        "Fecha de nacimiento",
        "Fecha de defunción",
        "Tamaño",
        "Carácter",
        "¿Trae chip?",
        "Fecha de implantación del chip",
        "Raza PPP",
        "Foto",
        "Comunicación RIAC",
    ]
    for label in expected_labels:
        assert label in sources

    bad_visible_labels = re.compile(
        r">\s*(NCHIP|FNacimiento|FDefuncion|Tamano|Caracter|TraeNChip|"
        r"FIMPLANTACIONCHIP|RazaPPP|NombreFoto|ComunicacionARIAC)\s*(?:<|:)",
    )
    assert bad_visible_labels.search(sources) is None


def test_animal_form_preserves_internal_field_names() -> None:
    """Visible labels can change, but posted field names stay contract-stable."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "templates" / "animales" / "form.html").read_text(
        encoding="utf-8"
    )

    for field_name in [
        "NCHIP",
        "FNacimiento",
        "FDefuncion",
        "Tamano",
        "Caracter",
        "TraeNChip",
        "FIMPLANTACIONCHIP",
        "RazaPPP",
        "NombreFoto",
        "ComunicacionARIAC",
    ]:
        assert f'name="{field_name}"' in source


def test_volunteer_templates_use_human_readable_visible_labels() -> None:
    """Volunteer pages show Spain-Spanish labels, not raw column shorthand."""
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (
            root / "app" / "templates" / "voluntarios" / template
        ).read_text(encoding="utf-8")
        for template in ("detail.html", "form.html", "list.html")
    )

    for label in ["Teléfono", "Teléfono 1", "Teléfono 2"]:
        assert label in sources

    bad_visible_labels = re.compile(r">\s*(Tel1|Tel2|Telefono 1|Telefono 2)\s*(?:<|:)")
    assert bad_visible_labels.search(sources) is None


def test_volunteer_form_preserves_internal_field_names() -> None:
    """Volunteer POST contract keeps legacy field names while labels improve."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "templates" / "voluntarios" / "form.html").read_text(
        encoding="utf-8"
    )

    for field_name in ["Tel1", "Tel2"]:
        assert f'name="{field_name}"' in source


async def test_unauthorized_redirects_anonymous_users_to_login(
    client: httpx.AsyncClient,
) -> None:
    """The access-denied page is only for users with a deactivated session.

    Anonymous visitors must be bounced to /login — the denial copy is
    only meaningful after the auth flow has placed a session cookie in
    the browser (the auth callback sends deactivated users here). The
    e2e landing suite reads the friendly copy through that path too.
    """
    response = await client.get("/unauthorized", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize(
    "path",
    [
        "/animales",
        "/animales/abc-123/update",
        "/entradas",
        "/entradas/ent-123/update",
        "/voluntarios",
    ],
)
async def test_protected_form_posts_redirect_anonymous_before_validation(
    client: httpx.AsyncClient,
    path: str,
) -> None:
    """Malformed anonymous POSTs must hit auth before FastAPI form validation."""
    response = await client.post(path, data={}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize(
    "path",
    [
        "/animales",
        "/entradas",
        "/voluntarios",
    ],
)
async def test_protected_form_posts_redirect_unauthorized_sessions_before_validation(
    client: httpx.AsyncClient,
    path: str,
) -> None:
    """Inactive sessions should reach /unauthorized before form validation."""
    _login_as_unauthorized_user(client)

    response = await client.post(path, data={}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


async def test_unauthorized_renders_html(client: httpx.AsyncClient) -> None:
    """Authenticated-but-inactive users can see the access-denied copy."""
    _login_as_unauthorized_user(client)

    response = await client.get("/unauthorized")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "no autorizado" in response.text.lower()
    assert "APAP Alcalá" in response.text
    forbidden = re.compile(
        r"APAP_WEB|Copy provisional|Fase \d|esqueleto",
        flags=re.IGNORECASE,
    )
    assert forbidden.search(response.text) is None


async def test_unauthorized_links_compiled_css(client: httpx.AsyncClient) -> None:
    """The unauthorized page links the compiled Tailwind CSS asset."""
    _login_as_unauthorized_user(client)

    response = await client.get("/unauthorized")

    assert "/static/css/output.css" in response.text
