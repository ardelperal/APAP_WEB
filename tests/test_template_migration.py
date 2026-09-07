"""Slice C — UA-based template selection migration (engram obs #15705).

Slice A (``UADetectionMiddleware``) and slice B
(``base_template_context_processor`` + ``base_mobile.html``) shipped the
mechanism. Slice C is the mechanical migration of every module's
templates + every per-module ``Jinja2Templates`` instance so the mobile
chrome reaches every page on every device.

Test layers:

1. **Static regression guard on templates** — no template under
   ``app/templates/`` may use the literal ``{% extends "base.html" %}``.
   All extending templates must use ``{% extends base_template %}`` so
   ``UADetectionMiddleware`` can pick the right base. If a future dev
   adds a template with the literal, the test fails and names the
   file:line.

2. **Static regression guard on routes** — every
   ``Jinja2Templates(..., context_processors=[...])`` instance under
   ``app/modules/**/routes.py`` must include
   ``base_template_context_processor`` in its processor list. Without
   this, the per-module ``_templates`` instance never injects
   ``base_template`` and the new templates raise ``UndefinedError`` at
   render time.

3. **HTTP-level mobile sentinel** — ``GET /casas-acogida`` with a
   mobile User-Agent renders the mobile chrome (``viewport-fit=cover``
   in the ``<meta name="viewport">``). This proves the full
   chain end-to-end: middleware → context processor → per-module
   ``_templates`` → Jinja ``{% extends base_template %}`` → response
   body. We use the foster list (FOSTER-01) because it's a non-form
   public-ish page reachable through a key_user session, doesn't
   require fixtures beyond a logged-in cookie, and the migration
   covers its template directly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_local_backend_client_dep
from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_local_backend_client
from tests.conftest import auth_reval_rows

# --- Paths ----------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATES_DIR = _REPO_ROOT / "app" / "templates"
_MODULES_DIR = _REPO_ROOT / "app" / "modules"

# Sentinel matches the LITERAL string "base.html" or 'base.html' used
# as the argument of a ``{% extends %}`` tag. We deliberately anchor on
# the tag opener ``{% extends`` so a ``{% block %}`` that mentions
# "base.html" in a comment does not trip the guard.
_EXTENDS_LITERAL_RE = re.compile(
    r"""\{%\s*extends\s*['"]base\.html['"]\s*%\}"""
)

# Sentinel matches the import line of base_template_context_processor
# in a routes module. We accept any indentation and any quote style.
_PROCESSOR_IMPORT_RE = re.compile(
    r"""from\s+app\.core\.middleware\s+import\s+.*base_template_context_processor"""
)


# --- Static regression guard: templates ----------------------------------


def _all_extending_templates() -> list[Path]:
    """Return every .html under app/templates/ that has ``{% extends %}``.

    Excludes ``base.html`` and ``base_mobile.html`` themselves because
    they are the layout roots, not consumers of the ``base_template``
    variable.
    """
    out: list[Path] = []
    for html in sorted(_TEMPLATES_DIR.rglob("*.html")):
        if html.name in {"base.html", "base_mobile.html"}:
            continue
        text = html.read_text(encoding="utf-8")
        if "{% extends" not in text:
            continue
        out.append(html)
    return out


def test_no_template_extends_base_html_literal() -> None:
    """No template uses ``{% extends "base.html" %}`` literally.

    Slice C migrated every extending template to
    ``{% extends base_template %}`` so the UA-based selector (slice B)
    can pick the right base. A literal ``{% extends "base.html" %}``
    bypasses the selector and forces desktop chrome on mobile — the
    exact regression this guard prevents.
    """
    bad: list[str] = []
    for html in _all_extending_templates():
        rel = html.relative_to(_REPO_ROOT)
        for line_no, line in enumerate(html.read_text(encoding="utf-8").splitlines(), start=1):
            if _EXTENDS_LITERAL_RE.search(line):
                bad.append(f"{rel}:{line_no}: {line.strip()}")
    assert not bad, (
        "Templates still using literal `{% extends \"base.html\" %}`. "
        "Migrate to `{% extends base_template %}` so UA-based selection "
        "works on every page. Offending files:\n  - "
        + "\n  - ".join(bad)
    )


def test_every_extending_template_uses_base_template_variable() -> None:
    """Positive companion: every extending template uses ``base_template``.

    The companion to ``test_no_template_extends_base_html_literal``:
    proves the migration target was applied. A template might have
    ``{% extends "base.html" %}` removed but never replaced — this
    test would still pass for the negative (no literal extends), but
    here we assert the variable is actually referenced.
    """
    bad: list[str] = []
    for html in _all_extending_templates():
        rel = html.relative_to(_REPO_ROOT)
        text = html.read_text(encoding="utf-8")
        if "{% extends base_template %}" not in text:
            bad.append(str(rel))
    assert not bad, (
        "Templates that extend something but do not use `{% extends "
        "base_template %}`. Expected `{% extends base_template %}` so "
        "the UA selector chooses the chrome per request. Offending "
        "files:\n  - " + "\n  - ".join(bad)
    )


# --- Static regression guard: routes -------------------------------------


def _route_files_with_jinja_templates() -> list[Path]:
    """Return every router file under app/modules/ that instantiates Jinja2Templates.

    Router files end in ``routes.py`` (e.g. ``animals/routes.py``) or
    in ``<scope>_routes.py`` for sub-routers that share the module's
    templates directory (e.g. ``entradas/batch_routes.py``,
    ``foster/assignment_routes.py``). The glob ``*routes.py`` matches
    both shapes; ``rglob("routes.py")`` would miss the
    ``<scope>_routes.py`` files because rglob is a literal match.

    Service modules (``animals/service.py``,
    ``entradas/batch_service.py``) never call ``Jinja2Templates(``,
    so the substring filter below is what actually excludes them.
    """
    out: list[Path] = []
    for routes in sorted(_MODULES_DIR.rglob("*routes.py")):
        text = routes.read_text(encoding="utf-8")
        if "Jinja2Templates(" in text:
            out.append(routes)
    return out


def test_every_module_route_jinja2_includes_base_template_processor() -> None:
    """Every ``Jinja2Templates(...)`` instance under ``app/modules/`` registers the UA processor.

    Without ``base_template_context_processor`` in the processor list,
    the per-module ``_templates`` instance never injects
    ``base_template`` into the context. Templates that write
    ``{% extends base_template %}`` (the migrated form) then raise
    ``UndefinedError`` at render time — a 500 on every page served by
    that module. This static guard catches a missed migration before
    the test suite runs.
    """
    bad: list[str] = []
    for routes in _route_files_with_jinja_templates():
        rel = routes.relative_to(_REPO_ROOT)
        text = routes.read_text(encoding="utf-8")
        if "base_template_context_processor" not in text:
            bad.append(str(rel))
    assert not bad, (
        "Route files instantiate Jinja2Templates but do not register "
        "base_template_context_processor. Add it to the "
        "context_processors= list (and the import) so per-module "
        "templates can `{% extends base_template %}`. Offending "
        "files:\n  - " + "\n  - ".join(bad)
    )


def test_every_module_route_jinja2_also_keeps_csrf_processor() -> None:
    """Companion: the csrf processor must remain registered.

    Slice C only ADDS ``base_template_context_processor`` — it does
    NOT remove ``csrf_token_context_processor``. If a future refactor
    replaces the processor list wholesale, the CSRF defense-in-depth
    could silently drop out. This test pins the existing CSRF
    processor as a stable contract.
    """
    bad: list[str] = []
    for routes in _route_files_with_jinja_templates():
        rel = routes.relative_to(_REPO_ROOT)
        text = routes.read_text(encoding="utf-8")
        if "csrf_token_context_processor" not in text:
            bad.append(str(rel))
    assert not bad, (
        "Route files dropped csrf_token_context_processor from the "
        "context_processors= list. Slice C only ADDS the UA processor; "
        "do not remove CSRF. Offending files:\n  - "
        + "\n  - ".join(bad)
    )


def test_processor_import_is_from_app_core_middleware() -> None:
    """The processor import path matches the module that defines it.

    Catches the case where a future refactor moves
    ``base_template_context_processor`` from
    ``app.core.middleware`` to another module without updating the
    imports here. The migration guards below depend on the import
    path being stable.
    """
    bad: list[str] = []
    for routes in _route_files_with_jinja_templates():
        rel = routes.relative_to(_REPO_ROOT)
        text = routes.read_text(encoding="utf-8")
        # The processor must be present; we already check that above.
        if "base_template_context_processor" not in text:
            continue
        if not _PROCESSOR_IMPORT_RE.search(text):
            bad.append(str(rel))
    assert not bad, (
        "Route files reference base_template_context_processor but do "
        "not import it from app.core.middleware. Update the import to "
        "`from app.core.middleware import base_template_context_processor`. "
        "Offending files:\n  - " + "\n  - ".join(bad)
    )


# --- HTTP-level mobile sentinel ------------------------------------------


_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
    "Mobile/15E148 Safari/604.1"
)


class _RevalOnlySpy(LocalPostgresExecutor):
    """Minimal LocalBackend spy that ONLY answers the auth revalidation SELECT.

    Mirrors the pattern used by ``tests/test_template_selection.py``
    and ``tests/test_foster_routes.py``. The foster list endpoint
    (``GET /casas-acogida``) calls ``foster_service.list_casas_acogida``
    which issues one SELECT against the ``casas_acogida`` table; we
    return an empty list so the page renders its empty state. Any
    OTHER direct SQL from the route would be a regression — that is
    covered by the existing ``test_foster_routes.py`` layer-boundary
    guards, not duplicated here.
    """

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval
        # ``list_casas_acogida`` returns all active rows; the empty
        # list exercises the empty-state branch and keeps the test
        # independent of seed data.
        if "casas_acogida" in query:
            return []
        # Let the test fail loudly if a new query path appears that
        # we have not accounted for.
        raise AssertionError(
            f"unexpected SQL on /casas-acogida route test: {query!r}"
        )


@pytest.fixture
def foster_route_client() -> _RevalOnlySpy:
    """Install the per-request LocalBackend spy for the duration of the test."""
    spy = _RevalOnlySpy()
    app.dependency_overrides[get_local_backend_client] = lambda: spy
    app.dependency_overrides[get_local_backend_client_dep] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_local_backend_client, None)
    app.dependency_overrides.pop(get_local_backend_client_dep, None)


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    """Mint a key_user session cookie so /casas-acogida does not redirect to /login."""
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-migration",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


async def test_foster_list_renders_with_base_template_for_mobile(
    client: httpx.AsyncClient,
    foster_route_client: _RevalOnlySpy,
) -> None:
    """Mobile UA + /casas-acogida → response renders the mobile chrome.

    End-to-end chain that slice C closes:

    1. ``UADetectionMiddleware`` (slice A) sets ``request.state.is_mobile``
       from the User-Agent.
    2. The per-module ``_templates`` instance in
       ``app/modules/foster/routes.py`` — migrated in slice C to
       register ``base_template_context_processor`` — injects
       ``base_template = "base_mobile.html"`` into the template
       context.
    3. The template ``app/templates/casas_acogida/list.html`` —
       migrated in slice C to ``{% extends base_template %}`` — picks
       the mobile base.
    4. The response HTML carries the mobile-only marker
       ``viewport-fit=cover`` in ``<meta name="viewport">``.

    Sentinel: ``viewport-fit=cover`` is the mobile-only marker. It is
    ABSENT from ``base.html`` and PRESENT in ``base_mobile.html``.
    """
    _login_as_key_user(client)

    response = await client.get(
        "/casas-acogida", headers={"User-Agent": _MOBILE_UA}
    )

    assert response.status_code == 200, response.text
    assert "viewport-fit=cover" in response.text, (
        "Mobile UA on /casas-acogida did not render base_mobile.html. "
        "Either the per-module Jinja2Templates instance is missing "
        "base_template_context_processor, or the template still uses "
        "`{% extends \"base.html\" %}` literal."
    )
