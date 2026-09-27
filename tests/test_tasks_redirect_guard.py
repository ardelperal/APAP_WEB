"""Redirect guard + XSS disposition tests for the tareas slice (issue #1038).

Two CodeQL findings families are pinned here:

1. ``py/url-redirection`` (#30, #31, #124, #125): the write routes
   (``asignar_tarea``, ``cerrar_tarea``) interpolated the raw
   ``tarea_id`` path param into the final ``RedirectResponse`` URL.
   ``tarea_id`` is semantically a Postgres UUID (queries cast ``::uuid``),
   so the redirect must validate it with ``uuid.UUID`` and fall back to
   the ``/tareas`` constant for any malformed value.

2. ``py/reflective-xss`` (#122, #123): the ``filter_estado`` query field
   flows into ``TemplateResponse`` context. Starlette's
   ``Jinja2Templates`` enables autoescape by default, so the payload is
   entity-escaped — these tests prove that behaviorally instead of
   touching the read-only templates.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import httpx
import pytest

from app.main import app
from tests.conftest import make_csrf_request
from tests.test_tasks import _FakeTasksLocalBackend, _login_as

_PAYLOAD = "<script>alert(1)</script>"


@pytest.fixture
def fake_tasks_local_backend() -> _FakeTasksLocalBackend:
    """Same contract as ``tests/test_tasks.py`` — fake answers revalidation SQL."""
    from app.core.auth_dependencies import get_local_postgres_executor_dep
    from app.main import get_local_backend_client

    fake = _FakeTasksLocalBackend()
    app.dependency_overrides[get_local_backend_client] = lambda: fake
    app.dependency_overrides[get_local_postgres_executor_dep] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_local_backend_client, None)
    app.dependency_overrides.pop(get_local_postgres_executor_dep, None)


# ---------------------------------------------------------------------------
# Part A — URL redirection guard (uuid.UUID validation)
# ---------------------------------------------------------------------------


class TestTareaRedirectGuard:
    """The final redirect of the write routes must not echo a raw id."""

    async def test_asignar_tarea_invalid_id_redirects_to_list(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend,  # noqa: ANN001  # reuses test_tasks fixture
    ) -> None:
        """POST /tareas/<not-a-uuid>/asignar redirects to the /tareas constant."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        response = await make_csrf_request(client, "POST", "/tareas/not-a-uuid/asignar")
        assert response.status_code == 302
        assert response.headers["location"] == "/tareas"

    async def test_cerrar_tarea_invalid_id_redirects_to_list(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend,
    ) -> None:
        """POST /tareas/<not-a-uuid>/cerrar redirects to the /tareas constant."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        response = await make_csrf_request(client, "POST", "/tareas/not-a-uuid/cerrar")
        assert response.status_code == 302
        assert response.headers["location"] == "/tareas"

    async def test_asignar_tarea_injected_id_not_reflected(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend,
    ) -> None:
        """An angle-bracket payload in the path param never reaches Location."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        # Angle brackets, no slash: a slash would 404 at routing before the
        # handler runs, and we want to exercise the redirect itself.
        injected = quote("<script>alert(1)", safe="")
        response = await make_csrf_request(
            client, "POST", f"/tareas/{injected}/asignar"
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert location == "/tareas"
        assert "<script" not in location

    async def test_valid_uuid_still_redirects_to_detail(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend,
    ) -> None:
        """A well-formed UUID keeps the historical redirect to the detail URL."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        valid_id = str(uuid.uuid4())
        response = await make_csrf_request(
            client, "POST", f"/tareas/{valid_id}/asignar"
        )
        # ValueError (not found) is still swallowed by the route; the
        # redirect target for a VALID id is the detail URL.
        assert response.status_code == 302
        assert response.headers["location"] == f"/tareas/{valid_id}"


# ---------------------------------------------------------------------------
# Part B — XSS disposition (autoescape evidence, templates untouched)
# ---------------------------------------------------------------------------


class TestTareasXssAutoescape:
    """CodeQL #122/#123: filter fields into TemplateResponse are escaped."""

    async def test_filter_estado_payload_is_entity_escaped(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend,
    ) -> None:
        """GET /tareas?estado=<script> renders the escaped entities only."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        response = await client.get(
            "/tareas", params={"estado": _PAYLOAD}, follow_redirects=False
        )
        assert response.status_code == 200
        body = response.text
        assert "&lt;script&gt;" in body, (
            "the payload must be entity-escaped by Jinja2 autoescape"
        )
        assert _PAYLOAD not in body, (
            "the raw payload must never appear unescaped in the HTML"
        )

    def test_tareas_templates_autoescape_is_truthy(self) -> None:
        """The tareas slice Jinja2Templates env has autoescape enabled."""
        from app.modules.tasks.routes import _templates

        assert _templates.env.autoescape, (
            "Jinja2Templates autoescape is disabled for the tareas slice — "
            "every XSS disposition in docs/audits/ would be invalidated"
        )
