"""Runtime form enumeration test (PR-5B2, T-5B.15 — round-2 fix REG-S-2).

Catches JS-submitted forms that the static grep enumeration misses:
fetch() calls, onclick handlers, and other dynamic submissions that
don't go through a rendered HTML form tag. For every non-safe route
registered on the FastAPI app, this test POSTs WITHOUT a CSRF token
and asserts the middleware rejects with 403.

If a future PR adds a new POST endpoint that doesn't have CSRF
protection, this test catches it at CI time, before it reaches
``staging``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.core.session import session_cookie_name, write_session
from app.main import app


class _NoSqlSpy:
    """InsForge stand-in that returns no rows."""

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[no-untyped-def]
        return []

    def __getattr__(self, name: str) -> Any:  # type: ignore[no-untyped-def]
        # Strict mode: unmocked methods surface as test failures (see
        # tests/test_all_post_forms_have_csrf_input.py for the rationale).
        raise NotImplementedError(
            f"_AnonymousSpy.{name} is not mocked. Add an explicit method "
            f"to the spy in this test instead of relying on no-op fallback."
        )


def _enumerate_non_safe_routes() -> list[tuple[str, str]]:
    """Walk the FastAPI app's routes and yield (method, path) for non-safe ones.

    Includes nested routes inside ``Mount`` and ``_IncludedRouter``
    sub-routers (each module's APIRouter is mounted under the app
    via ``app.include_router``).

    SAFE methods (GET/HEAD/OPTIONS) bypass the CSRF middleware by design
    (RFC 7231). Anything else MUST carry a CSRF token. Public paths
    (``/login``, ``/healthz``, etc.) and disabled-doc paths are still
    tested — the public-path check is auth-layer, and the CSRF layer
    is only active on POSTs; even if the auth layer redirects, the
    CSRF layer runs FIRST on POSTs.
    """
    safe = {"GET", "HEAD", "OPTIONS"}
    results: list[tuple[str, str]] = []

    def _walk(routes, prefix: str = "") -> None:
        for route in routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None) or set()
            # ``_IncludedRouter`` (FastAPI) wraps the original APIRouter;
            # recurse via ``.original_router.routes`` with the prefix.
            original = getattr(route, "original_router", None)
            if original is not None and hasattr(original, "routes"):
                _walk(original.routes, prefix + getattr(original, "prefix", ""))
                continue
            # Plain APIRouter (nested) — recurse via ``.routes``.
            if hasattr(route, "routes"):
                _walk(route.routes, prefix + (path or ""))
                continue
            if not path or not methods:
                continue
            full_path = prefix + path
            for method in methods:
                if method.upper() not in safe and method.upper() != "TRACE":
                    results.append((method.upper(), full_path))

    _walk(app.routes)
    return results


_NON_SAFE_ROUTES = _enumerate_non_safe_routes()


@pytest.fixture
def no_sql_client(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """Client pre-loaded with a session; InsForge dep is a no-op."""
    from app.main import get_insforge_client

    spy = _NoSqlSpy()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    monkeypatch.setattr(
        "app.modules.animals.routes.get_insforge_client_dep", lambda: spy
    )
    monkeypatch.setattr(
        "app.modules.entradas.routes.get_insforge_client_dep", lambda: spy
    )


    settings = get_settings()
    token = write_session(
        {
            "email": "enum@example.com",
            "rol": "developer",
            "user_id": "u-enum",
            "is_authorized": True,
            "csrf_token": "do-not-use-this-for-the-check",
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)
    yield client
    app.dependency_overrides.pop(get_insforge_client, None)


@pytest.mark.parametrize("method,path", _NON_SAFE_ROUTES)
async def test_non_safe_route_without_csrf_token_is_rejected_with_403(
    no_sql_client: httpx.AsyncClient,
    method: str,
    path: str,
) -> None:
    """Every non-safe (POST/PUT/PATCH/DELETE) route MUST return 403 without a CSRF token.

    This is the dynamic counterpart to ``test_all_post_forms_have_csrf_input.py``.
    The static form-audit test catches rendered HTML forms; this test
    catches fetch/JS submissions and any route that was added without
    the static audit being re-run.
    """
    # Build a minimal payload. Path params use placeholders; we don't
    # care if the route 404s after the CSRF check — what matters is
    # that the CSRF middleware rejects FIRST.
    import re

    def _replace_param(match: re.Match[str]) -> str:
        return {
            "user_id": "u-1",
            "animal_id": "abc-123",
            "entrada_id": "ent-1",
            "voluntario_id": "v-1",
        }.get(match.group(1), "x")

    actual_path = re.sub(r"\{([^:}]+)(?::[^}]+)?\}", _replace_param, path)

    response = await no_sql_client.request(
        method,
        actual_path,
        data={"csrf_token": "deliberately-wrong", "name": "x"},
        follow_redirects=False,
    )

    # The CSRF middleware MUST 403 BEFORE the route handler runs.
    # If the middleware is disabled or the route bypasses it, this
    # assertion fails and the regression is caught at CI time.
    assert response.status_code == 403, (
        f"{method} {path} returned {response.status_code} (expected 403 — "
        "no CSRF token was sent). Either the CSRF middleware is not "
        "applied to this route, or the test is missing the path-param "
        "substitution. See app/core/csrf.py and app/main.py."
    )
