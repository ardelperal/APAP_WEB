"""XSS audit — handler-level Markup() tests (REQ-XSS-2.b of hardening-2026-q2).

While ``test_xss_audit.py`` exercises template rendering directly,
this file exercises the route handlers that return ``HTMLResponse``,
to catch ``Markup()`` / ``format()`` / ``f"..."`` HTML construction
inside the handlers (a vector the template test cannot detect because
the template is never reached).

Method:
  1. Build a spy ``InsForgeClient`` that returns rows whose
     user-controlled columns contain the four XSS patterns from
     spec REQ-XSS-2.
  2. Log in as an authorized user (any role works).
  3. Hit each GET/POST route that returns ``HTMLResponse``.
  4. Assert the response body does NOT contain any of the patterns
     literally.

The audit also runs an AST check: every handler in
``app/main.py`` / ``app/modules/.../routes.py`` is inspected for
``Markup(...)`` / ``format(...)``-on-HTML / ``f\"<\"``-style
construction, mirroring the template-level ``|safe`` check.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from tests.conftest import auth_reval_rows, make_csrf_request

# Four XSS payloads from spec REQ-XSS-2 — chosen so each spans a
# different attack vector (script tag / event handler / SVG / URL).
# The handler-level test asserts that patterns 1-3 (text-context XSS)
# do NOT appear in the response body. Pattern 4 (URL scheme) is only
# exploitable when interpolated into a URL attribute; the handler
# test does not assert against it in text context because the browser
# does not execute JS from text nodes (see ``test_no_user_data_in_url_attrs``
# in ``test_xss_audit.py`` for the URL-attribute structural check).
XSS_SCRIPT = "<script>alert(1)</script>"
XSS_IMG = "<img src=x onerror=alert(1)>"
XSS_SVG = "<svg onload=alert(1)>"
XSS_URL = "javascript:alert(1)"
TEXT_CONTEXT_XSS_PATTERNS: tuple[str, ...] = (XSS_SCRIPT, XSS_IMG, XSS_SVG)
URL_CONTEXT_XSS_PATTERN: str = XSS_URL


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    from app.core.config import get_settings

    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            # PR-5B2: session-bound CSRF token so CsrfMiddleware validates POSTs.
            "csrf_token": "test-csrf-token-xss",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


# ---------------------------------------------------------------------------
# Spy InsForge client — returns rows with XSS payloads in user columns.
# ---------------------------------------------------------------------------


class _XssInsForge(InsForgeClient):
    """Stand-in for ``InsForgeClient`` that returns XSS-laden rows.

    Pattern matches SQL fragments (same shape as the real routes) so
    that all ``animales``/``entradas``/``voluntarios`` queries return
    rows whose user-controlled columns contain every XSS payload from
    the spec. Routes that render those rows must HTML-escape the
    payload; if the payload appears literally in the response body,
    that is the XSS finding the audit captures.
    """

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://xss-spy.example")
        self.list_animales_rows: list[dict[str, object]] = [
            {
                "id": "abc-123",
                "NCHIP": XSS_SCRIPT,
                "NombreAnimal": XSS_IMG,
                "Especie": "CANINA",
                "Sexo": "H",
                "FNacimiento": "2023-04-12",
                "activo": True,
                "Raza": XSS_SVG,
                "Observaciones": XSS_URL,
            }
        ]
        self.list_entradas_rows: list[dict[str, object]] = [
            {
                "id": "ent-1",
                "animal_id": XSS_SCRIPT,
                "fecha_entrada": "2024-01-15",
                "voluntario_entrada_id": None,
                "origen": XSS_IMG,
                "motivo": XSS_SVG,
                "observaciones": XSS_URL,
            }
        ]
        self.list_voluntarios_rows: list[dict[str, object]] = [
            {
                "id": "v-1",
                "Voluntario": XSS_SCRIPT,
                "Email": XSS_IMG,
                "DNI": XSS_SVG,
                "Tel1": XSS_URL,
                "Tel2": None,
                "fecha_alta": "2024-01-01",
                "activo": True,
            }
        ]
        # Per-id lookups (animals / entradas / voluntarios detail).
        self.single_animal_row: dict[str, object] = dict(self.list_animales_rows[0])
        self.single_entrada_row: dict[str, object] = dict(self.list_entradas_rows[0])
        self.single_voluntario_row: dict[str, object] = dict(self.list_voluntarios_rows[0])
        self.authorized_users: list[dict[str, object]] = [
            {
                "id": "u-admin",
                "email": XSS_SCRIPT,
                "rol": "developer",
                "activo": True,
            }
        ]

    def execute_sql(self, query, params=None):  # type: ignore[override]
        _reval = auth_reval_rows(query if isinstance(query, str) else "", params)
        if _reval is not None:
            return _reval
        sql = query if isinstance(query, str) else ""
        s = sql.lower()
        # Word-boundary detection: ``updated_at`` must NOT count as
        # ``update``. The audit was getting false-positive matches
        # because ``updated_at`` is a column name in the SELECT
        # clauses and tripped the literal ``"update" not in s`` guard.
        verb = re.match(r"\s*(\w+)", s)
        verb_token = verb.group(1) if verb else ""
        starts_select = verb_token == "select"
        starts_insert = verb_token == "insert"
        starts_update = verb_token == "update"
        starts_delete = verb_token == "delete"
        if starts_select and "from animales" in s and "where id = $1" in s:
            return [dict(self.single_animal_row)]
        if starts_select and "from entradas" in s and "where id = $1" in s:
            return [dict(self.single_entrada_row)]
        if starts_select and "from voluntarios" in s and "where id = $1" in s:
            return [dict(self.single_voluntario_row)]
        if starts_select and "from animales" in s and "order by" in s:
            return list(self.list_animales_rows)
        if starts_select and "from entradas" in s and "order by" in s:
            return list(self.list_entradas_rows)
        if starts_select and "from voluntarios" in s and "order by" in s:
            return list(self.list_voluntarios_rows)
        if "from usuarios_autorizados" in s and "where id = $1" in s:
            return list(self.authorized_users)
        if "from usuarios_autorizados" in s:
            return list(self.authorized_users)
        if starts_select and "count" in s and "from animales" in s:
            return [{"n": 1}]
        if starts_select and "count" in s and "from entradas" in s:
            return [{"n": 1}]
        if starts_select and "count" in s and "from voluntarios" in s:
            return [{"n": 1}]
        # INSERT / UPDATE / DELETE — return a row shaped like the
        # module the request is touching. We dispatch by ``from`` table
        # in the SQL when present.
        if starts_insert or starts_update or starts_delete:
            if "from animales" in s:
                return [dict(self.single_animal_row)]
            if "from entradas" in s:
                return [dict(self.single_entrada_row)]
            if "from voluntarios" in s:
                return [dict(self.single_voluntario_row)]
            return [dict(self.single_animal_row)]
        return []

    def close(self) -> None:  # type: ignore[override]
        return None


@pytest.fixture
def xss_insforge() -> _XssInsForge:
    spy = _XssInsForge()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_insforge_client, None)


# ---------------------------------------------------------------------------
# Handler-level route coverage — parametrized.
# ---------------------------------------------------------------------------


# Each entry: (test_id, method, url, login_role, expected_status_in_200_3xx)
HANDLER_ROUTES: list[tuple[str, str, str]] = [
    # Animales
    ("animales_list", "GET", "/animales"),
    ("animales_new", "GET", "/animales/new"),
    ("animales_detail", "GET", "/animales/abc-123"),
    ("animales_edit", "GET", "/animales/abc-123/edit"),
    # Entradas
    ("entradas_list", "GET", "/entradas"),
    ("entradas_new", "GET", "/entradas/new"),
    ("entradas_detail", "GET", "/entradas/ent-1"),
    ("entradas_edit", "GET", "/entradas/ent-1/edit"),
    # Voluntarios
    ("voluntarios_list", "GET", "/voluntarios"),
    ("voluntarios_new", "GET", "/voluntarios/new"),
    ("voluntarios_detail", "GET", "/voluntarios/v-1"),
]


@pytest.mark.parametrize(("_id", "method", "url"), HANDLER_ROUTES, ids=[r[0] for r in HANDLER_ROUTES])
async def test_handler_does_not_leak_xss_payload(
    _id: str,
    method: str,
    url: str,
    client: httpx.AsyncClient,
    xss_insforge: _XssInsForge,  # noqa: ARG001 — fixture installs the spy
) -> None:
    """Every HTMLResponse route MUST escape the XSS payloads from spec.

    The fixture ``xss_insforge`` returns rows whose user-controlled
    columns contain each of the four spec patterns. The route renders
    the row through a Jinja2 template; autoescape is the only line of
    defense, so the literal payload must NOT appear in the rendered
    HTML. If any pattern appears, the route has a stored-XSS finding.
    """
    _login_as_key_user(client)

    response = await client.request(method, url, follow_redirects=False)
    # Either 200 (HTML rendered) or 303 (redirect; we'll follow it).
    if response.status_code in (302, 303):
        # The route redirected; fetch the redirect target to follow.
        response = await client.request(
            method,
            url,
            follow_redirects=True,
        )
    assert response.status_code == 200, (
        f"unexpected status {response.status_code} for {method} {url}"
    )
    assert "text/html" in response.headers["content-type"], (
        f"non-HTML response for {method} {url}: {response.headers.get('content-type')}"
    )

    body = response.text
    for pattern in TEXT_CONTEXT_XSS_PATTERNS:
        assert pattern not in body, (
            f"Stored XSS in {method} {url}: pattern {pattern!r} appears "
            f"literally in the response body. This is the XSS finding for "
            f"REQ-XSS-2.b — document in docs/audits/xss-audit-2026-Q2.md."
        )


# ---------------------------------------------------------------------------
# Reflected-XSS test for the POST → re-render form path.
# The error path renders the form with the user's submitted values; if
# autoescape is off, an attacker-controlled value in any field would
# execute. The animal and entrada POST handlers both re-render the form
# on ``ValueError``/``EntradaConflictError``.
# ---------------------------------------------------------------------------


async def test_animal_create_post_re_renders_form_with_xss_escaped(
    client: httpx.AsyncClient,
    xss_insforge: _XssInsForge,  # noqa: ARG001
) -> None:
    """POST ``/animales`` with XSS in every field — body MUST escape it.

    The handler re-renders the form on ``ValueError`` (422) — which our
    spy triggers because ``Especie``/``Sexo`` validate against the
    enum. We assert the response body contains the escaped forms and
    NOT the raw patterns.
    """
    _login_as_key_user(client)
    response = await make_csrf_request(
        client,
        "POST",
        "/animales",
        form_data={
            # XSS payloads en los campos string que llegan al re-render.
            "NCHIP": XSS_SCRIPT,
            "NombreAnimal": XSS_IMG,
            # Especie invalida fuerza el 422 re-render (mismo trick que
            # antes del #129; seguimos testeando XSS en el path de error).
            "Especie": "INVALIDO_PARA_FORZAR_VALUEERROR",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "Raza": XSS_SVG,
            "Observaciones": XSS_URL,
            # #129: los 4 nuevos required fields requieren valores validos
            # (sino Pydantic rechaza con "Field required" ANTES del 422
            # del handler). Valores benignos para no introducir XSS aqui.
            "Terapia": "No",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2023-04-15",
            "NombreFoto": "luna.jpg",
        },
    )
    assert response.status_code == 422, (
        f"expected 422 re-render on invalid Especie, got {response.status_code}"
    )
    body = response.text
    for pattern in TEXT_CONTEXT_XSS_PATTERNS:
        assert pattern not in body, (
            f"Reflected XSS in POST /animales error path: pattern {pattern!r} "
            f"appears literally. Document in docs/audits/xss-audit-2026-Q2.md."
        )


# ---------------------------------------------------------------------------
# AST-level audit: no ``Markup(...)`` / ``format(<html)`` / ``f"<...{user}"``
# in any handler.
# ---------------------------------------------------------------------------


HANDLER_FILES = [
    Path("app") / "main.py",
    Path("app") / "modules" / "animals" / "routes.py",
    Path("app") / "modules" / "entradas" / "routes.py",
    Path("app") / "modules" / "voluntarios" / "routes.py",
]


def test_no_markup_in_handlers() -> None:
    """No handler in ``app/`` may build HTML with ``Markup()``.

    ``Markup`` from ``markupsafe`` returns an object that the Jinja
    autoescape layer treats as trusted; using it on user data
    reintroduces XSS. The grep below mirrors the ``|safe`` guard in
    ``test_xss_audit.py`` but for the handler side.
    """
    repo_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in HANDLER_FILES:
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if re.search(r"\bMarkup\s*\(", line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "XSS audit FAILED: Markup(...) used in handler code. Markup bypasses "
        "Jinja2 autoescape; replace with plain string + autoescape or a "
        "sanitiser. Offending lines:\n" + "\n".join(offenders)
    )


def test_no_fstring_html_in_handlers() -> None:
    """No handler builds HTML via ``f\"<...{var}\"``.

    Building HTML via f-strings skips Jinja2's autoescape entirely.
    The grep looks for an opening angle bracket within an f-string
    followed by an interpolation. This catches the common
    ``return HTMLResponse(content=f\"<p>{user_input}</p>\")`` pattern.
    """
    repo_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in HANDLER_FILES:
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if re.search(r"f[\"'][^\"']*<[a-zA-Z/!][^\"']*\{[^}]+\}", line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "XSS audit FAILED: handler builds HTML via f-string interpolation. "
        "Route the value through a Jinja2 template so autoescape applies. "
        "Offending lines:\n" + "\n".join(offenders)
    )


def test_no_htmlresponse_with_content_in_handlers() -> None:
    """No handler MUST ``return HTMLResponse(content=...)``.

    The only acceptable HTML responses go through Jinja2
    ``TemplateResponse`` (which autoescapes). ``HTMLResponse(content=...)``
    forces the developer to hand-escape — easy to forget. This grep
    is the audit's hand-rolled safety net.
    """
    repo_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in HANDLER_FILES:
        path = repo_root / rel
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Match ``HTMLResponse(content=`` but NOT
            # ``templates.TemplateResponse(`` or ``_templates.TemplateResponse(``.
            if re.search(r"\bHTMLResponse\s*\(\s*content\s*=", line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "XSS audit FAILED: handler constructs HTMLResponse(content=...). "
        "Route the response through Jinja2 TemplateResponse so autoescape "
        "applies. Offending lines:\n" + "\n".join(offenders)
    )
