"""Shared pytest fixtures for the APAP_WEB test suite.

The ``client`` fixture is the only thing most route tests need: an
``httpx.AsyncClient`` wired to the module-level ``app`` via
``httpx.ASGITransport`` (the current recommended way to exercise an
ASGI app from tests, per the httpx docs). Using the module-level
``app`` (rather than calling ``create_app()`` per test) is what makes
``app.dependency_overrides[...]`` work: the test that overrides a
dependency and the test that uses the client must see the same
``app`` instance.

The ``_clear_settings_cache`` autouse fixture (function scope) clears
the ``get_settings`` lru_cache before every test. This keeps tests
hermetic even when one test mutates ``APAP_*`` env vars via
``monkeypatch.setenv`` / ``mp.setenv`` and a later test expects the
defaults. It costs one function call per test — negligible.

The ``make_csrf_request`` helper (PR-5B2, REQ-AH-7) attaches the
session-bound CSRF token to outgoing POSTs so existing route tests
keep working after the ``CsrfMiddleware`` lands. Tests that exercise
the middleware itself (cross-session attacks, missing token, etc.)
pass an explicit ``csrf_token=`` override.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
import pytest_asyncio

# CRITICAL: set APAP_MODE=test BEFORE any other import that reads Settings.
# The RateLimitMiddleware (issue #286) short-circuits when ``settings.mode == "test"``,
# which is the contract that route tests rely on to avoid 429s in the test client.
# Without this env var set at conftest-import time, every test that hits a write
# route gets 429 (rate-limited) BEFORE the role/auth check runs, and the test
# expecting 403 (forbidden) sees 429 instead. PR #361 routes CI to the
# self-hosted runner, which actually executes the tests; before that PR, the
# GitHub-hosted runner pool was blocked and tests never ran, masking this
# configuration gap.
os.environ.setdefault("APAP_MODE", "test")

from app.core.config import get_settings  # noqa: E402  (must follow the env set)
from app.core.di.local_postgres_di import get_local_postgres_executor_dep  # noqa: E402
from app.core.local_backend.db import LocalPostgresExecutor  # noqa: E402
from app.core.session import read_session, session_cookie_name  # noqa: E402
from app.main import app as _app  # noqa: E402

# Enables the built-in ``pytester`` fixture (opt-in plugin) used by
# ``tests/test_coverage_gate.py`` to spawn nested pytest subprocesses and
# assert on their real exit code (issue #257 regression coverage).
pytest_plugins = ["pytester"]


def auth_reval_rows(
    query: str, params: object = None, *, rol: str = "key_user"
) -> list[dict[str, Any]] | None:
    """Issue #143 seam for route-test LocalBackend spies.

    ``require_authorized_user`` now SELECTs the caller from
    ``usuarios_autorizados`` on EVERY request (the cookie signs identity;
    the DB is the source of truth for authorization). Route spies that
    returned ``[]`` — or a rowless stub — for unknown SQL would therefore
    make every authenticated request 302 to ``/unauthorized`` (or raise
    ``KeyError`` on the missing ``rol``).

    Spies call this as the FIRST line of ``execute_sql`` so they answer the
    revalidation query with an active-user row, then fall through to their
    own domain SQL. Returning here (before any ``captured_queries.append``)
    keeps the revalidation SELECT out of the domain-SQL assertions.

    Returns the row list for the auth query, or ``None`` when ``query`` is
    not the revalidation SELECT so the spy handles it. ``rol`` matches the
    test's login helper (default ``key_user``; admin/developer tests pass
    ``rol="developer"``).
    """
    # Auth revalidation (issue #143): uses GET_USER_BY_EMAIL_SQL which
    # includes 'rol' as a selected column (appears in SELECT ... rol, ...).
    # The duplicate-check uses _CHECK_DUPLICATE_EMAIL_SQL with a minimal
    # 'SELECT id' (no rol column) — this pattern must NOT be intercepted.
    if (
        "usuarios_autorizados" in query
        and "email = $1" in query
        and re.search(r"(?<=[, ])rol(?=[,])", query) is not None
    ):
        email = (
            params[0]
            if isinstance(params, list | tuple) and params
            else "reval@example.com"
        )
        return [{"id": "u-reval", "email": email, "rol": rol, "activo": True}]
    return None


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Reset ``get_settings()`` lru_cache before every test.

    Added for code-quality-fixes T1 (see ``app/core/config.py`` docstring
    and ``openspec/changes/code-quality-fixes/proposal.md``). Tests that
    mutate ``APAP_*`` env vars without explicitly clearing the cache
    would otherwise observe a stale singleton from a previous test.
    """
    get_settings.cache_clear()
    # Reset the rate-limit backend between every test so bucket state from
    # one test does not affect another (issue #286).
    try:
        from app.core.rate_limit_middleware import _reset_rate_limit_backend
        _reset_rate_limit_backend()
    except ImportError:
        pass  # Before rate-limit middleware is added; no-op


@pytest.fixture(autouse=True)
def _install_default_local_backend_client() -> None:
    """Wire a default ``state.sql_executor`` spy into the module ``app``.

    Epic #420 migrated the animals slice (and several cross-slice
    consumers) to ``Depends(get_animals_port)`` which reads
    ``request.app.state.sql_executor`` directly. Routes that
    exercise those handlers no longer go through the legacy
    ``get_local_backend_client_dep`` override; the test client needs the
    state populated for any POST that reaches the hexagonal port
    provider, including CSRF middleware tests, XSS audit
    handlers, and auth middleware tests.

    Tests that want a custom spy (recording INSERT/UPDATE/SELECT
    SQL) override this by setting ``app.state.sql_executor`` to
    their own object after this fixture runs.

    The default spy implements pattern-matching on ``execute_sql`` so
    pre-existing CSRF / XSS / session / migration tests that exercise
    CSRF middleware, the animales routes, and the voluntarios routes
    (each of which writes a row-keyed lookup against the spy) all get
    the keys they expect without each test having to install its own
    ``app.state.sql_executor`` fixture. Tests that need richer
    data (e.g. ``xss_local_backend``) override this by setting
    ``app.state.sql_executor`` to their own object after this
    fixture runs; the test order runs autouse FIRST then
    non-autouse, so the override wins for that test.
    """
    class _DefaultLocalBackendSpy(LocalPostgresExecutor):
        def __init__(self) -> None:
            import httpx as _httpx
            self._client = _httpx.Client(base_url="https://default-spy.example")
            self.execute_sql_calls: list[tuple[str, list[object]]] = []

        def execute_sql(
            self, sql: str, params: list[object] | None = None
        ) -> list[dict[str, object]]:
            self.execute_sql_calls.append((sql, list(params or [])))
            s = sql.strip().lower()
            # Routes that select a single animal by primary key expect
            # one row back; otherwise the handler 404s and the test
            # fails an unrelated assertion. Tests that need richer
            # data override this spy.
            if s.startswith("select") and "from animales" in s and "where id =" in s.replace(" ", "").replace("=", "= "):
                return [
                    {
                        "id": params[0] if params else "abc-123",
                        "NCHIP": "985112004409871",
                        "NombreAnimal": "Luna",
                        "Especie": "CANINA",
                        "Sexo": "H",
                        "FNacimiento": "2023-04-12",
                        "activo": True,
                    }
                ]
            if s.startswith("select") and "from voluntarios" in s and "where id =" in s.replace(" ", ""):
                return [
                    {
                        "id": params[0] if params else "v-1",
                        "Voluntario": "Ana",
                        "Email": "ana@example.com",
                        "DNI": "12345678A",
                        "Tel1": "+34 600 000 000",
                        "Tel2": None,
                        "fecha_alta": "2024-01-01",
                        "activo": True,
                    }
                ]
            if s.startswith("select") and "from entradas" in s and "where id =" in s.replace(" ", ""):
                return [
                    {
                        "id": params[0] if params else "ent-1",
                        "FechaEntrada": "2024-01-01",
                        "activo": True,
                    }
                ]
            return []

    spy = _DefaultLocalBackendSpy()
    _app.state.sql_executor = spy
    _app.dependency_overrides[get_local_postgres_executor_dep] = (
        lambda: _app.state.sql_executor
    )
    yield
    _app.dependency_overrides.pop(get_local_postgres_executor_dep, None)
    _app.state.__dict__.pop("sql_executor", None)


@pytest_asyncio.fixture
async def client() -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` bound to the module-level ``app``."""
    transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def make_csrf_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    csrf_token: str | None = None,
    form_data: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    """Sign a CSRF-protected request on the test client.

    Helper for PR-5B2 (REQ-AH-7). Reads the ``apap_session`` cookie
    the client is currently carrying, decodes the payload via
    ``read_session``, and attaches the session's ``csrf_token`` as the
    ``X-CSRFToken`` header. Falls back to a ``csrf_token`` form field
    when ``form_data`` is provided so the middleware's "form field
    path" branch can be exercised too.

    Parameters
    ----------
    client:
        The httpx async client (typically the ``client`` fixture).
    method:
        HTTP verb (``POST``, ``PUT``, ``PATCH``, ``DELETE``).
    url:
        Target URL (absolute path, e.g. ``"/admin/users"``).
    csrf_token:
        Explicit token override. Use this for cross-session adversarial
        tests (session A cookie + session B token). When ``None``,
        reads the token from the client's current session cookie.
    form_data:
        Optional ``application/x-www-form-urlencoded`` body. When
        provided, the helper ALSO adds the token under
        ``csrf_token`` so form-submitted POSTs pass the middleware.
    headers:
        Extra headers to merge onto the outgoing request.
    """
    settings = get_settings()
    merged_headers: dict[str, str] = {"X-CSRFToken": csrf_token} if csrf_token else {}

    if csrf_token is None:
        cookie = client.cookies.get(session_cookie_name())
        if cookie:
            payload = read_session(cookie, secret=settings.session_secret)
            if payload is not None:
                token = payload.get("csrf_token")
                if isinstance(token, str) and token:
                    merged_headers["X-CSRFToken"] = token

    if headers:
        merged_headers.update(headers)

    kwargs: dict[str, Any] = {"headers": merged_headers, "follow_redirects": False}
    if form_data is not None:
        body = dict(form_data)
        if csrf_token is not None:
            body.setdefault("csrf_token", csrf_token)
        else:
            body.setdefault("csrf_token", merged_headers.get("X-CSRFToken", ""))
        kwargs["data"] = body

    return await getattr(client, method.lower())(url, **kwargs)


def test_fake_sql_executor_helpers_have_required_methods() -> None:
    """Regression guard: detect files where a class docstring lost its closing.

    When a triple-quoted string opens but never closes, Python compiles the
    file successfully but consumes the class body as a string literal. The
    methods "disappear" from the class namespace and tests fail at runtime
    with NameError on every call site. ruff and mypy do not catch this
    because py_compile succeeds on the source file.

    This guard runs as a pytest test on every suite invocation. It imports
    every _FakeSqlExecutor helper defined in the test tree, asserts the
    presence of the five methods that the SqlExecutor Protocol requires for
    tests, and fails loudly if even one is missing.

    The five required methods are:
    - __init__      constructs the fake executor
    - set_response  load one round-trip response
    - set_responses load multiple round-trip responses (consumed in order)
    - set_handler   install a per-call (query, params) -> rows handler
    - execute_sql   SqlExecutor Protocol entry point (records + answers)
    """
    import importlib

    candidates = [
        "tests.test_auth",
        "tests.test_entradas",
        "tests.test_adopciones",
        "tests.test_acogidas",
        "tests.test_cesiones",
        "tests.test_sanidad_batch",
    ]
    failures: list[str] = []
    for modname in candidates:
        try:
            mod = importlib.import_module(modname)
        except ImportError:
            continue  # file may not define _FakeSqlExecutor (OK)
        if not hasattr(mod, "_FakeSqlExecutor"):
            continue
        cls = mod._FakeSqlExecutor
        required = frozenset(
            {"__init__", "set_response", "set_responses", "set_handler", "execute_sql"}
        )
        missing = required - frozenset(dir(cls))
        if missing:
            failures.append(f"{modname}._FakeSqlExecutor missing: {sorted(missing)}")

    assert not failures, (
        f"One or more _FakeSqlExecutor helpers lost method bodies. "
        f"This happens when a class docstring opens with triple-quoted "
        f"but the closing triple-quoted is missing -- Python compiles the "
        f"file but treats the body as string content, so the methods vanish. "
        f"Failures: {failures}"
    )

