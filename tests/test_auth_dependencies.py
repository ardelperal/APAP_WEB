"""Tests for shared auth-related FastAPI dependencies.

The dependencies live in ``app.core.auth_dependencies`` and are used by
both the app entrypoint (``app.main``) and every module router. They
are a regression surface, so the contract is pinned here independently
of the route-level tests in ``test_admin.py`` / ``test_animals.py`` /
``test_voluntarios.py``.

Currently pinned:

- ``get_insforge_client_dep`` closes the ``httpx.Client`` it creates
  for each request (no resource leak across requests). This is the
  fix for code-quality-fixes T2 / problem #3 of the external review.
- F-2 / F-4 (issue #119): ``return_early_if_response(value: object)``
  → ``Response | dict``; ``get_insforge_client_dep()`` declares
  ``Iterator[InsForgeClient]`` as return annotation.
- F-3 (issue #120): the triple-duplicated "read cookie + decode
  payload" pattern is replaced by ``app.core.session.read_session_payload``;
  the call sites in ``app/main.py`` (middleware) and
  ``app/core/csrf.py`` (CsrfMiddleware) MUST delegate to it.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import pytest as _pytest
from fastapi import Request
from starlette.responses import Response as _Response

from app.core import auth_cache as _auth_cache
from app.core.auth_dependencies import (
    get_current_user_optional,
    get_insforge_client_dep,
    require_authorized_user,
    return_early_if_response,
)
from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.session import (
    session_cookie_name,
    write_session,
)

# ---------------------------------------------------------------------------
# F-4 (issue #119): get_insforge_client_dep return annotation
# ---------------------------------------------------------------------------


def test_get_insforge_client_dep_return_annotation_is_iterator() -> None:
    """F-4: ``get_insforge_client_dep`` MUST declare ``Iterator[InsForgeClient]``.

    Without the annotation, type checkers infer the return as
    ``Any`` and every handler that does
    ``client: InsForgeClient = Depends(get_insforge_client_dep)``
    loses precision on every method call on ``client``.

    Uses ``typing.get_type_hints`` because ``from __future__ import
    annotations`` makes all annotations lazy strings; the raw
    ``inspect.signature(...).return_annotation`` returns the
    string ``"Iterator[InsForgeClient]"``, not the resolved type.
    """
    from typing import get_args, get_origin, get_type_hints

    hints = get_type_hints(get_insforge_client_dep)
    return_hint = hints["return"]
    # ``typing.get_type_hints`` may return a fresh ``Iterator[...]``
    # object on each call, so compare by origin + args rather than ``is``.
    assert get_origin(return_hint) is Iterator, (
        f"get_insforge_client_dep return must be an Iterator, "
        f"got: {return_hint!r}"
    )
    type_args = get_args(return_hint)
    assert InsForgeClient in type_args, (
        f"get_insforge_client_dep return must yield InsForgeClient, "
        f"got args: {type_args!r}"
    )


def test_get_insforge_client_dep_is_a_generator() -> None:
    """The implementation MUST be a generator function (uses ``yield``).

    Pre-#260 the dep was a generator that created + closed a per-request
    InsForgeClient (the yield + finally closed the client's httpx
    transport so it never leaked). After #260 the lifecycle is owned by
    the lifespan (created in startup, closed in shutdown), so the dep
    only ``yield``s the pooled instance — no per-request create or
    close. The generator-function shape is still required so:

    - FastAPI's dependency-injection protocol treats it the same way
      (callers that use ``dependency_overrides[...]`` continue to work
      whether they override with a generator or a plain callable).
    - The return annotation stays ``Iterator[InsForgeClient]`` (see
      :func:`test_get_insforge_client_dep_return_annotation_is_iterator`).

    This test is a defence-in-depth check: even if the annotation
    changes, the body must still be a generator function.
    """
    assert inspect.isgeneratorfunction(get_insforge_client_dep), (
        "get_insforge_client_dep must be a generator function "
        "(uses yield) so the dep hands out the pooled client via the "
        "same Iterator[InsForgeClient] protocol FastAPI expects"
    )


# ---------------------------------------------------------------------------
# Issue #260: pooled httpx.Client on app.state
#
# The dep no longer creates or closes an InsForgeClient. It yields the
# pooled instance stored on ``request.app.state.insforge_client`` by
# the lifespan. The two tests below pin that contract.
# ---------------------------------------------------------------------------


def test_get_insforge_client_dep_returns_pooled_client_from_app_state() -> None:
    """Issue #260: the dep MUST yield the InsForgeClient stored on app.state.

    A single ``httpx.Client`` connection pool must be reused across
    requests — created in the lifespan, closed in shutdown, never
    per-request. The dep is the bridge between that pooled instance
    and the route handlers: it MUST pull from ``request.app.state``,
    not construct a new client.

    Without this, the dep could silently re-create a client per
    request (the very behaviour #260 is removing) and the whole
    pooling refactor would regress to "no pooling" without any test
    noticing.
    """
    from app.core.auth_dependencies import get_insforge_client_dep  # noqa: PLC0415

    pooled = InsForgeClient("http://test", "k")

    # Wire up a fake request whose ``app.state.insforge_client`` is
    # our pooled sentinel. The dep MUST hand that exact instance back.
    class _State:
        insforge_client = pooled

    class _App:
        state = _State()

    class _Request:
        app = _App()

    gen = get_insforge_client_dep(request=_Request())
    try:
        handed_out = next(gen)
    finally:
        # Close the generator so the dep's protocol completes cleanly
        # (the dep yields exactly once, so this is a no-op finalisation).
        for _ in gen:
            pass
        gen.close()

    assert handed_out is pooled, (
        "get_insforge_client_dep MUST return the same InsForgeClient "
        "stored on app.state.insforge_client — pooling breaks if the "
        "dep returns anything else"
    )


def test_get_insforge_client_dep_does_not_close_pooled_client() -> None:
    """Issue #260: the dep MUST NOT call ``close()`` on the pooled client.

    Pre-#260 the dep owned the per-request lifecycle (``finally:
    client.close()``). Post-#260 the lifespan owns the lifecycle
    (close on shutdown). If the dep accidentally re-introduced a
    ``close()`` call, the FIRST request after the lifespan started
    would tear down the pooled client — every subsequent request
    would fail with ``httpx.ClosedResourceError`` or similar.

    The contract pinned here: the dep's generator body never invokes
    ``close()`` on the client it yields. We verify by tracking every
    ``close()`` call on the pooled sentinel.
    """
    from app.core.auth_dependencies import get_insforge_client_dep  # noqa: PLC0415

    close_calls: list[None] = []

    class _PooledClient:
        def execute_sql(self, query: str, params: Any = None) -> list[dict[str, Any]]:
            return []

        def close(self) -> None:
            close_calls.append(None)

    class _State:
        insforge_client = _PooledClient()

    class _App:
        state = _State()

    class _Request:
        app = _App()

    gen = get_insforge_client_dep(request=_Request())
    try:
        next(gen)
    finally:
        # Drive the generator to completion (including any finally
        # block) and observe whether close() was invoked.
        for _ in gen:
            pass
        gen.close()

    assert close_calls == [], (
        f"get_insforge_client_dep MUST NOT close the pooled client "
        f"(lifespan owns the lifecycle). close() calls observed: "
        f"{close_calls!r}"
    )


# ---------------------------------------------------------------------------
# F-2 (issue #119): return_early_if_response signature
# ---------------------------------------------------------------------------


def test_return_early_if_response_accepts_response_or_dict() -> None:
    """F-2: ``return_early_if_response`` parameter MUST be ``Response | dict``.

    The previous ``object`` annotation hid misuse — passing an
    int or a string would not be caught until the function tried
    to call ``.get()`` on it at runtime. The narrower union makes
    the helper's purpose explicit.

    Reads the raw ``__annotations__`` because ``from __future__ import
    annotations`` makes them lazy strings, and ``get_type_hints``
    cannot resolve cross-module types like ``starlette.responses.Response``
    from the test module's namespace.
    """
    annotations = return_early_if_response.__annotations__
    value_annotation = annotations["value"]
    assert "Response" in value_annotation, (
        f"return_early_if_response(value=...) must accept Response, "
        f"got annotation: {value_annotation!r}"
    )
    assert "dict" in value_annotation, (
        f"return_early_if_response(value=...) must accept dict, "
        f"got annotation: {value_annotation!r}"
    )
    # The previous bug was ``object`` — the widest possible type. The
    # fix narrows it to the union. Guard against regression by
    # rejecting ``object`` directly.
    assert value_annotation.strip() != "object", (
        "F-2 regression: return_early_if_response parameter is back to "
        "``object`` (no type narrowing). Use ``Response | dict`` instead."
    )


# ---------------------------------------------------------------------------
# F-3 (issue #120): read_session_payload helper consolidation
# ---------------------------------------------------------------------------


def test_read_session_payload_helper_exists() -> None:
    """F-3 (issue #120): the read_session_payload(request) helper MUST exist.

    Consolidates the 4-line "read cookie + decode payload" pattern
    duplicated across ``get_current_user_optional``,
    ``protect_user_facing_routes`` middleware, and ``CsrfMiddleware``.
    Without the helper, any future call site would re-introduce
    the same snippet.
    """
    from app.core.session import read_session_payload  # noqa: PLC0415

    assert callable(read_session_payload), (
        "app.core.session.read_session_payload must be a callable helper"
    )


def _make_request(cookie_header: bytes | None = None) -> Request:
    headers = []
    if cookie_header is not None:
        headers.append((b"cookie", cookie_header))
    return Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": b"",
        }
    )


def test_read_session_payload_returns_none_when_no_cookie() -> None:
    """The helper returns None when the request has no session cookie.

    Pins the contract used by every call site: a None return means
    "anonymous" so the caller can short-circuit to /login without
    catching exceptions.
    """
    from app.core.session import read_session_payload  # noqa: PLC0415

    request = _make_request()
    assert read_session_payload(request, secret="any") is None


def test_read_session_payload_returns_payload_when_valid_cookie() -> None:
    """The helper returns the decoded payload dict when the cookie is valid."""
    from app.core.session import read_session_payload  # noqa: PLC0415

    secret = "s" * 32
    token = write_session({"email": "u@e.com", "is_authorized": True}, secret=secret)
    request = _make_request(
        f"{session_cookie_name()}={token}".encode("latin-1")
    )
    payload = read_session_payload(request, secret=secret)
    assert payload == {"email": "u@e.com", "is_authorized": True}


def test_read_session_payload_returns_none_when_signature_invalid() -> None:
    """A tampered cookie (wrong secret) returns None, not a partial dict.

    Pins the security contract: a cookie signed with one secret must
    NOT leak any field when validated against a different secret.
    """
    from app.core.session import read_session_payload  # noqa: PLC0415

    token = write_session({"email": "u@e.com"}, secret="correct-secret")
    request = _make_request(
        f"{session_cookie_name()}={token}".encode("latin-1")
    )
    # Different secret → signature check fails → None (no leak).
    assert read_session_payload(request, secret="WRONG-secret") is None


def test_get_current_user_optional_delegates_to_read_session_payload() -> None:
    """``get_current_user_optional`` MUST call ``read_session_payload``.

    Without the delegation, a future change to the helper (e.g.
    a logging hook) would miss the auth path. The mock catches
    that drift.
    """
    request = _make_request()

    with patch(
        "app.core.auth_dependencies.read_session_payload", return_value={"x": 1}
    ) as spy:
        get_current_user_optional(request=request)

    spy.assert_called_once()
    # The helper MUST receive the active session secret so a
    # future ``APAP_SESSION_SECRET`` rotation is honoured.
    _settings = get_settings()
    call_args, call_kwargs = spy.call_args
    secret_arg = call_kwargs.get("secret")
    if secret_arg is None and len(call_args) >= 2:
        secret_arg = call_args[1]
    assert secret_arg == _settings.session_secret


def test_middleware_uses_read_session_payload() -> None:
    """The auth middleware in ``app.main`` MUST delegate to ``read_session_payload``.

    Three call sites used to inline the 4-line pattern
    (read cookie + decode payload); they MUST now go through the
    helper so a future change to the helper is picked up by all
    three. This test reads ``app/main.py`` as text and asserts the
    helper name appears at the right call site — a structural test
    that catches the regression of inlining the snippet back.
    """
    main_source = Path("app/main.py").read_text(encoding="utf-8")
    assert "read_session_payload(" in main_source, (
        "app/main.py must call read_session_payload(request, secret=...) "
        "in the protect_user_facing_routes middleware; inlining the "
        "read-cookie + decode-payload snippet again would re-introduce "
        "the triple duplication that issue #120 is meant to fix."
    )
    # The middleware MUST NOT inline the snippet.
    inlined = (
        "    payload = (\n"
        "        read_session(token, secret=settings.session_secret)\n"
        "        if token\n"
        "        else None\n"
        "    )"
    )
    assert inlined not in main_source, (
        "app/main.py middleware still inlines the read-cookie snippet; "
        "must delegate to read_session_payload per issue #120."
    )


def test_csrf_middleware_uses_read_session_payload() -> None:
    """``CsrfMiddleware.dispatch`` MUST delegate to ``read_session_payload``.

    Same rationale as test_middleware_uses_read_session_payload but
    for the CSRF middleware.
    """
    csrf_source = Path("app/core/csrf.py").read_text(encoding="utf-8")
    assert "read_session_payload(" in csrf_source, (
        "app/core/csrf.py must call read_session_payload(request, secret=...) "
        "in CsrfMiddleware.dispatch per issue #120."
    )


# ---------------------------------------------------------------------------
# Existing regression tests (kept from the prior version of this file)
# ---------------------------------------------------------------------------


def _login_pre_fix(client):  # type: ignore[no-untyped-def]
    from app.core.config import get_settings

    client.cookies.set(
        session_cookie_name(),
        write_session(
            {"email": "g@e.com", "rol": "key_user", "user_id": "u-g"},
            secret=get_settings().session_secret,
        ),
    )


class _SpyInsForge:
    """Minimal InsForge stand-in. Raises on unmocked methods."""

    def __init__(self) -> None:
        self.get_user_by_email_response: dict | None = {
            "id": "u-1", "email": "a@b.com", "rol": "key_user", "activo": True,
        }

    def __getattr__(self, name):  # type: ignore[no-untyped-def]
        raise NotImplementedError(
            f"_SpyInsForge.{name} is not mocked. Add an explicit method "
            f"to the spy in this test instead of relying on no-op fallback."
        )

    def get_user_by_email(self, client, email):  # type: ignore[no-untyped-def]
        if self.get_user_by_email_response is None:
            return None
        if self.get_user_by_email_response["email"] != email:
            return None
        return dict(self.get_user_by_email_response)


async def test_middleware_default_false_redirects_to_unauthorized(
    client,  # type: ignore[no-untyped-def]
) -> None:
    """Pre-fix cookie → 302 /unauthorized (NOT /login; cookie signature verifies).

    The landing is now public, so we exercise the middleware on a
    protected app route (``/animales``).
    """
    _login_pre_fix(client)
    r = await client.get("/animales", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/unauthorized"


async def test_middleware_pasa_con_is_authorized_true(
    client,  # type: ignore[no-untyped-def]
) -> None:
    """``/animales`` with ``is_authorized=True`` reaches the route handler."""
    from app.core.config import get_settings
    from app.main import app, get_insforge_client

    # The route handler needs an InsForge client; without a stub the
    # lifespan tries to reach the real backend and the test errors with
    # httpx.ConnectError before the middleware verdict is observable.
    class _StubInsForge:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.calls: list[str] = []

        def close(self) -> None:  # noqa: D401
            return None

        def execute_sql(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
            # The /animales route calls a couple of SELECTs; return
            # empty rows so the handler renders the empty-state page
            # without InsForge.
            from tests.conftest import auth_reval_rows

            query = args[0] if args else ""
            params = args[1] if len(args) > 1 else None
            _reval = auth_reval_rows(query if isinstance(query, str) else "", params)
            if _reval is not None:
                return _reval
            return []

        def __getattr__(self, name: str) -> object:
            raise NotImplementedError(f"_StubInsForge.{name} not mocked")

    app.dependency_overrides[get_insforge_client] = lambda: _StubInsForge()
    try:
        client.cookies.set(
            session_cookie_name(),
            write_session(
                {
                    "email": "l@e.com",
                    "rol": "key_user",
                    "user_id": "u-l",
                    "is_authorized": True,
                },
                secret=get_settings().session_secret,
            ),
        )
        r = await client.get("/animales", follow_redirects=False)
        assert r.headers.get("location") not in ("/unauthorized", "/login")
    finally:
        app.dependency_overrides.pop(get_insforge_client, None)


# ---------------------------------------------------------------------------
# Issue #143: require_authorized_user re-validates authorization per request
# ---------------------------------------------------------------------------
#
# The signed cookie carries IDENTITY (stable). AUTHORIZATION is re-validated
# against ``usuarios_autorizados`` on every request, memoized for a short
# TTL. These unit tests call the dependency directly (bypassing FastAPI DI)
# so the cache-hit / cache-miss / revocation / role-refresh branches are
# pinned without a full ASGI round-trip.


@_pytest.fixture(autouse=True)
def _clear_auth_cache() -> None:
    _auth_cache.invalidate_all()
    yield
    _auth_cache.invalidate_all()


class _RevalSpy:
    """InsForge stand-in whose ``execute_sql`` returns a fixed user row set
    and records how many times it was queried (to prove cache hits)."""

    def __init__(self, rows: list[dict] | None) -> None:
        self._rows = rows if rows is not None else []
        self.query_count = 0

    def execute_sql(self, query, params=None):  # type: ignore[no-untyped-def]
        self.query_count += 1
        return [dict(r) for r in self._rows]

    def close(self) -> None:
        return None


def _authorized_payload(email: str = "u@e.com", rol: str = "key_user") -> dict:
    return {"email": email, "rol": rol, "user_id": "u-1", "is_authorized": True}


def test_require_authorized_user_redirects_to_login_when_no_session() -> None:
    """No payload → 302 /login (never touches the DB)."""
    spy = _RevalSpy([])
    result = require_authorized_user(request=_make_request(), payload=None, client=spy)
    assert isinstance(result, _Response)
    assert result.status_code == 302
    assert result.headers["location"] == "/login"
    assert spy.query_count == 0


def test_require_authorized_user_redirects_when_cookie_not_authorized() -> None:
    """is_authorized=False in the cookie → 302 /unauthorized, no DB query."""
    spy = _RevalSpy([])
    payload = {"email": "u@e.com", "rol": "key_user", "is_authorized": False}
    result = require_authorized_user(request=_make_request(), payload=payload, client=spy)
    assert isinstance(result, _Response)
    assert result.headers["location"] == "/unauthorized"
    assert spy.query_count == 0


def test_require_authorized_user_queries_db_on_first_request() -> None:
    """Cache miss → one DB query; returns the payload for an active user."""
    spy = _RevalSpy([{"id": "u-1", "email": "u@e.com", "rol": "key_user", "activo": True}])
    result = require_authorized_user(
        request=_make_request(), payload=_authorized_payload(), client=spy
    )
    assert not isinstance(result, _Response)
    assert result["email"] == "u@e.com"
    assert spy.query_count == 1


def test_require_authorized_user_uses_cache_on_second_request() -> None:
    """Second request within TTL is a cache hit → still exactly one DB query."""
    spy = _RevalSpy([{"id": "u-1", "email": "u@e.com", "rol": "key_user", "activo": True}])
    require_authorized_user(request=_make_request(), payload=_authorized_payload(), client=spy)
    require_authorized_user(request=_make_request(), payload=_authorized_payload(), client=spy)
    assert spy.query_count == 1


def test_require_authorized_user_redirects_when_user_deactivated_mid_session() -> None:
    """Active cookie but DB says inactive (no row) → 302 /unauthorized.

    This is the core of #143: the cookie still says ``is_authorized=True``
    (frozen for 7 days) but the DB is now the source of truth and returns
    no active row, so the request is revoked on the spot.
    """
    spy = _RevalSpy([])  # usuarios_autorizados filters activo=true → empty
    result = require_authorized_user(
        request=_make_request(), payload=_authorized_payload(), client=spy
    )
    assert isinstance(result, _Response)
    assert result.headers["location"] == "/unauthorized"
    assert spy.query_count == 1


def test_require_authorized_user_picks_up_role_change_mid_session() -> None:
    """A role change in the DB is reflected in the returned payload rol.

    The cookie was minted with ``key_user``; the DB now says ``admin``.
    The next request must see ``admin`` (the cookie is not the truth).
    """
    spy = _RevalSpy([{"id": "u-1", "email": "u@e.com", "rol": "admin", "activo": True}])
    result = require_authorized_user(
        request=_make_request(),
        payload=_authorized_payload(rol="key_user"),
        client=spy,
    )
    assert not isinstance(result, _Response)
    assert result["rol"] == "admin"


def test_require_authorized_user_reauthorizes_after_invalidation() -> None:
    """After ``invalidate_auth`` the next request re-queries the DB.

    Proves the invalidation seam add/deactivate rely on: a cleared entry
    forces a fresh lookup rather than serving the stale cached verdict.
    """
    spy = _RevalSpy([{"id": "u-1", "email": "u@e.com", "rol": "key_user", "activo": True}])
    require_authorized_user(request=_make_request(), payload=_authorized_payload(), client=spy)
    assert spy.query_count == 1
    _auth_cache.invalidate_auth("u@e.com")
    require_authorized_user(request=_make_request(), payload=_authorized_payload(), client=spy)
    assert spy.query_count == 2


# ---------------------------------------------------------------------------
# Issue #144: require_writer_user enforces write-role at the route boundary
# ---------------------------------------------------------------------------
#
# ``require_authorized_user`` only checks ``is_authorized``; a user with
# the ``reader`` rol passes it and could hit POST/PUT/PATCH/DELETE handlers
# unchallenged. ``require_writer_user`` composes on top and rejects readers
# with 403. These tests pin the contract: allowed roles pass through, the
# ``reader`` role is rejected, default-deny holds when the rol field is
# missing or unknown, and an upstream redirect (no session / deactivated)
# is propagated unchanged.


@pytest.mark.parametrize(
    "rol",
    ["developer", "admin", "key_user"],
    ids=["developer", "admin", "key_user"],
)
def test_require_writer_user_allows_writer_roles(rol: str) -> None:
    """Roles in :attr:`Settings.writer_rols` pass through with the payload intact.

    The dep is a thin composition on ``require_authorized_user`` — the
    contract is "I return what the upstream dep returned" so the handler
    keeps reading the same dict shape (rol, email, user_id, ...).
    """
    from app.core.auth_dependencies import require_writer_user  # noqa: PLC0415

    payload = _authorized_payload(rol=rol)
    result = require_writer_user(user=payload)

    assert not isinstance(result, _Response)
    assert result is payload
    assert result["rol"] == rol


def test_require_writer_user_rejects_reader() -> None:
    """A ``reader`` rol MUST be rejected with 403 (issue #144, the core gap).

    Before this dep, a reader could POST/PUT/PATCH/DELETE on every
    domain module because no route enforced the rol. The reader is
    explicit read-only by domain definition.
    """
    from fastapi import HTTPException

    from app.core.auth_dependencies import require_writer_user  # noqa: PLC0415

    payload = _authorized_payload(rol="reader")

    with pytest.raises(HTTPException) as exc_info:
        require_writer_user(user=payload)

    assert exc_info.value.status_code == 403
    # The detail message is user-facing; keep it actionable in castellano.
    assert "Permisos" in str(exc_info.value.detail)


def test_require_writer_user_rejects_missing_rol_default_deny() -> None:
    """A payload with no ``rol`` field MUST be rejected (regla 6: default-deny).

    Belt-and-braces: ``require_authorized_user`` always sets ``rol`` on
    the returned payload (either from the DB row or the cache), so this
    case is reachable only via a stale code path. The dep must still
    reject rather than trust a missing field.
    """
    from fastapi import HTTPException

    from app.core.auth_dependencies import require_writer_user  # noqa: PLC0415

    payload = {"email": "u@e.com", "user_id": "u-1", "is_authorized": True}
    assert "rol" not in payload  # sanity

    with pytest.raises(HTTPException) as exc_info:
        require_writer_user(user=payload)

    assert exc_info.value.status_code == 403


def test_require_writer_user_rejects_unknown_rol_default_deny() -> None:
    """An unknown rol string MUST be rejected (regla 6 + regla 4: source of truth).

    The set of accepted roles is :attr:`Settings.writer_rols`, derived
    from :class:`app.core.roles.Rol`. Anything outside the enum MUST be
    denied even if it looks plausible.
    """
    from fastapi import HTTPException

    from app.core.auth_dependencies import require_writer_user  # noqa: PLC0415

    with pytest.raises(HTTPException) as exc_info:
        require_writer_user(user=_authorized_payload(rol="superuser"))

    assert exc_info.value.status_code == 403


def test_require_writer_user_propagates_unauthorized_redirect() -> None:
    """When ``require_authorized_user`` returns a redirect, ``require_writer_user``
    MUST propagate it unchanged — the handler still has to bail out via
    ``return_early_if_response``.

    Composition contract: the writer dep never raises when the upstream
    dep returned a redirect, because the upstream dep already made the
    final verdict ("sesion no autorizada" -> /login or /unauthorized).
    """
    from fastapi.responses import RedirectResponse

    from app.core.auth_dependencies import require_writer_user  # noqa: PLC0415

    redirect = RedirectResponse(url="/login", status_code=302)
    result = require_writer_user(user=redirect)

    assert isinstance(result, _Response)
    assert result is redirect
    assert result.headers["location"] == "/login"


def test_require_writer_user_propagates_unauthorized_redirect_when_deactivated() -> None:
    """When ``require_authorized_user`` returns /unauthorized (deactivated user),
    ``require_writer_user`` MUST propagate it unchanged and NOT short-circuit
    to 403 — /unauthorized is the user-friendly path for that case.
    """
    from fastapi.responses import RedirectResponse

    from app.core.auth_dependencies import require_writer_user  # noqa: PLC0415

    redirect = RedirectResponse(url="/unauthorized", status_code=302)
    result = require_writer_user(user=redirect)

    assert isinstance(result, _Response)
    assert result is redirect
    assert result.headers["location"] == "/unauthorized"


def test_settings_writer_rols_is_derived_from_rol_enum() -> None:
    """``Settings.writer_rols`` MUST be derived from :class:`Rol` (regla 4).

    Single source of truth: adding a new rol to ``Rol`` (e.g. ``AUDITOR``)
    that should also be allowed to write only needs that one change in
    ``Rol`` + this property, NOT a hand-maintained string list anywhere
    else in the codebase.
    """
    from app.core.config import get_settings
    from app.core.roles import Rol

    settings = get_settings()
    expected = frozenset({Rol.DEVELOPER.value, Rol.ADMIN.value, Rol.KEY_USER.value})
    assert settings.writer_rols == expected
    # The reader rol is the only one NOT in writer_rols (by definition).
    assert Rol.READER.value not in settings.writer_rols


# ---------------------------------------------------------------------------
# FOSTER-03 (#45): ``require_developer_user`` enforces rol == "developer"
# at the route boundary for the foster overrides audit log endpoints.
#
# Composition contract (mirrors :func:`require_writer_user`):
#   - Builds on :func:`require_authorized_user` so the per-request
#     revalidation (#143) is reused, NOT re-implemented.
#   - Allowed rol (``developer``) → returns the payload untouched.
#   - Any other rol → 403 (different concept from /unauthorized, which
#     means "sesion invalida"; the dep propagates the upstream redirect
#     unchanged so the handler never reaches this code path).
# ---------------------------------------------------------------------------


def test_require_developer_user_developer_passes_and_others_get_403() -> None:
    """FOSTER-03 (#45): the developer dep is a thin allow-list on rol.

    Covers four rols in one go:

    - ``developer`` is the ONLY rol allowed by this dep (regla 4: source
      of truth is :class:`app.core.roles.Rol.DEVELOPER`).
    - ``admin``, ``key_user`` and ``reader`` all hit 403. ``key_user`` in
      particular is allowed by :func:`require_writer_user` (writes stay
      accessible) but NOT here — the overrides audit log is sensitive.
    - A missing ``rol`` is also rejected (regla 6: default-deny).
    """
    from fastapi import HTTPException

    from app.core.auth_dependencies import require_developer_user  # noqa: PLC0415

    # developer -> payload returned unchanged
    payload = _authorized_payload(rol="developer")
    assert require_developer_user(payload) is payload

    # every other rol -> 403
    for other in ("admin", "key_user", "reader"):
        with pytest.raises(HTTPException) as exc_info:
            require_developer_user(_authorized_payload(rol=other))
        assert exc_info.value.status_code == 403
        assert "developer" in str(exc_info.value.detail).lower()

    # missing rol -> 403 (regla 6 default-deny)
    with pytest.raises(HTTPException) as exc_info:
        require_developer_user(
            {"email": "u@e.com", "user_id": "u-1", "is_authorized": True}
        )
    assert exc_info.value.status_code == 403


def test_require_developer_user_propagates_unauthorized_redirect() -> None:
    """FOSTER-03 (#45): the developer dep must NOT raise when the upstream
    :func:`require_authorized_user` already returned a redirect.

    The composition mirrors :func:`require_writer_user`: a no-session /
    deactivated user should keep seeing ``/login`` or ``/unauthorized``,
    never a 403 (which would conflate "wrong rol" with "invalid session").
    """
    from fastapi.responses import RedirectResponse

    from app.core.auth_dependencies import require_developer_user  # noqa: PLC0415

    redirect = RedirectResponse(url="/login", status_code=302)
    assert require_developer_user(redirect) is redirect

    redirect_unauth = RedirectResponse(url="/unauthorized", status_code=302)
    assert require_developer_user(redirect_unauth) is redirect_unauth


# ---------------------------------------------------------------------------
# Issue #146: extract require_developer_user_redirect + audit log of denials
#
# The three admin routes (``/admin``, ``/admin/users``,
# ``/admin/users/{id}/deactivate``) used to inline a rol check against the
# string ``"developer"`` after depending on ``require_authorized_user``.
# That duplicated the developer dep's logic, risked drift, and bypassed
# the audit trail. This slice replaces the inline check with
# ``require_developer_user_redirect`` (redirect variant) and emits a
# ``log_safe("auth.denied", ...)`` event from each auth dep on rejection.
# ---------------------------------------------------------------------------


def test_require_developer_user_redirect_developer_passes_and_others_get_302() -> None:
    """``require_developer_user_redirect`` allows ``developer``, redirects everyone else.

    Issue #146 — mirrors :func:`require_developer_user` but instead of
    raising 403, returns a 302 to ``/unauthorized`` so the three admin
    routes (``/admin``, ``/admin/users``, ``/admin/users/{id}/deactivate``)
    keep their pre-#146 redirect contract. ``admin``, ``key_user``,
    ``reader`` and a missing ``rol`` all land on /unauthorized.
    """
    from fastapi.responses import RedirectResponse

    from app.core.auth_dependencies import (  # noqa: PLC0415
        require_developer_user_redirect,
    )

    # developer -> payload returned unchanged
    payload = _authorized_payload(rol="developer")
    assert require_developer_user_redirect(payload) is payload

    # every other rol -> 302 /unauthorized
    for other in ("admin", "key_user", "reader"):
        result = require_developer_user_redirect(_authorized_payload(rol=other))
        assert isinstance(result, RedirectResponse), (
            f"non-developer rol {other!r} must produce a RedirectResponse, "
            f"got: {result!r}"
        )
        assert result.status_code == 302
        assert result.headers["location"] == "/unauthorized"

    # missing rol -> redirect too (regla 6 default-deny)
    result = require_developer_user_redirect(
        {"email": "u@e.com", "user_id": "u-1", "is_authorized": True}
    )
    assert isinstance(result, RedirectResponse)
    assert result.headers["location"] == "/unauthorized"


def test_require_authorized_user_logs_auth_denied_for_db_reval_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DB revalidation misses, ``require_authorized_user`` MUST emit ``auth.denied``.

    Issue #146 — every denial path emits a structured ``log_safe`` event
    so operators can audit which users were bounced when, without log
    scraping. The closed 12-field redaction list already covers email,
    so we pass ``user_id`` (non-PII) and a ``reason`` enum.
    """
    from app.core.auth_dependencies import require_authorized_user

    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **fields: object) -> None:
        captured.append((event, fields))

    monkeypatch.setattr("app.core.auth_dependencies.log_safe", _capture)

    # No active row in the DB → dep returns /unauthorized + memoizes the deny.
    spy = _RevalSpy([])
    result = require_authorized_user(
        request=_make_request(), payload=_authorized_payload(), client=spy
    )

    assert isinstance(result, _Response)
    assert result.headers["location"] == "/unauthorized"

    db_miss_events = [
        (event, fields)
        for event, fields in captured
        if event == "auth.denied" and fields.get("reason") == "db_reval_miss"
    ]
    assert db_miss_events, (
        f"expected at least one auth.denied event with reason=db_reval_miss, "
        f"got: {captured!r}"
    )
    # The user_id from the payload is propagated for traceability.
    fields = db_miss_events[0][1]
    assert fields.get("user_id") == "u-1"
    # No PII leaks via the log path.
    assert "email" not in fields


def test_require_writer_user_logs_auth_denied_when_role_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``require_writer_user`` MUST emit ``auth.denied`` with reason=writer_required."""
    from fastapi import HTTPException

    from app.core.auth_dependencies import require_writer_user

    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **fields: object) -> None:
        captured.append((event, fields))

    monkeypatch.setattr("app.core.auth_dependencies.log_safe", _capture)

    with pytest.raises(HTTPException) as exc_info:
        require_writer_user(user=_authorized_payload(rol="reader"))

    assert exc_info.value.status_code == 403

    denial_events = [
        (event, fields)
        for event, fields in captured
        if event == "auth.denied" and fields.get("reason") == "writer_required"
    ]
    assert denial_events, (
        f"expected auth.denied with reason=writer_required, got: {captured!r}"
    )
    assert denial_events[0][1].get("user_id") == "u-1"


def test_require_developer_user_logs_auth_denied_when_role_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``require_developer_user`` MUST emit ``auth.denied`` with reason=developer_required."""
    from fastapi import HTTPException

    from app.core.auth_dependencies import require_developer_user

    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **fields: object) -> None:
        captured.append((event, fields))

    monkeypatch.setattr("app.core.auth_dependencies.log_safe", _capture)

    with pytest.raises(HTTPException) as exc_info:
        require_developer_user(_authorized_payload(rol="key_user"))

    assert exc_info.value.status_code == 403

    denial_events = [
        (event, fields)
        for event, fields in captured
        if event == "auth.denied" and fields.get("reason") == "developer_required"
    ]
    assert denial_events, (
        f"expected auth.denied with reason=developer_required, got: {captured!r}"
    )
    assert denial_events[0][1].get("user_id") == "u-1"


# ---------------------------------------------------------------------------
# Issue #143 — issue-closure scenario coverage
#
# The unit tests above pin the dep machinery (cache hit/miss, deny
# paths, log emission). The five tests below pin the USER-VISIBLE
# SCENARIOS from issue #143 by name, so a future regression cannot
# silently break the "deactivation takes effect on the next request"
# promise without a failing test that grep ``#143`` finds. They use
# the same ``_RevalSpy`` and helper patterns the unit tests use
# (no real InsForge, no real OAuth, no real lifespan).
# ---------------------------------------------------------------------------


def test_deactivation_takes_effect_on_next_request() -> None:
    """Issue #143 scenario, framed by name: an admin deactivates a user;
    the user's *next* request — still using the same valid signed cookie
    — must be denied, not allowed.

    Before #143 the cookie was the only source of truth: an admin who
    deactivated a user via ``/admin/users/{id}/deactivate`` had to wait
    up to 7 days for the cookie to expire. After #143 the next request
    hits the DB and the deactivation lands immediately (within the TTL).

    The cookie here is fresh and valid (``is_authorized=True``, valid
    signature, valid timestamp); the DB spy returns no active row for
    the user's email — exactly what ``get_user_by_email`` does after
    the admin's ``UPDATE usuarios_autorizados SET activo = false``.
    """
    # Pre-fix regression safety net: the cookie is still valid (the dep
    # MUST NOT trust the cookie — the DB is the source of truth).
    payload = _authorized_payload(email="victim@example.com")
    spy = _RevalSpy([])  # SELECT ... WHERE email = $1 AND activo = true → 0 rows

    result = require_authorized_user(
        request=_make_request(), payload=payload, client=spy
    )

    assert isinstance(result, _Response), (
        f"deactivated user must be redirected, got: {result!r}"
    )
    assert result.status_code == 302
    assert result.headers["location"] == "/unauthorized", (
        "deactivated user must hit /unauthorized (the DB revalidation "
        "miss signal), NOT /login (which means 'no session at all')"
    )
    assert spy.query_count == 1, (
        "the dep MUST re-validate against the DB on every request; "
        "the cookie is not the truth"
    )


def test_role_revocation_takes_effect_on_next_request() -> None:
    """Issue #143 scenario, framed by name: an admin revokes a user's role;
    the user's *next* request — still using the cookie with the old role
    — must see the new role in the returned payload (or be denied if
    the role no longer authorizes the dep).

    For ``require_authorized_user`` the role refresh on the returned
    payload is the contract: callers that depend on ``current_user["rol"]``
    (e.g. the admin routes deciding whether to show /admin links) must
    see the post-revocation role without a re-login. Without #143 the
    cookie's frozen ``rol`` lingers for 7 days.
    """
    cookie_payload = _authorized_payload(email="victim@example.com", rol="key_user")
    spy = _RevalSpy(
        [{"id": "u-1", "email": "victim@example.com", "rol": "reader", "activo": True}]
    )

    result = require_authorized_user(
        request=_make_request(), payload=cookie_payload, client=spy
    )

    assert not isinstance(result, _Response), (
        f"reader is still an authorized user (revoked role = demoted, "
        f"not deactivated). Expected dict payload, got redirect: {result!r}"
    )
    assert result["rol"] == "reader", (
        f"require_authorized_user MUST refresh rol from the DB on every "
        f"request — cookie rol was 'key_user', DB says 'reader' (the "
        f"admin's revocation). The handler must see the latest value: "
        f"got {result.get('rol')!r}"
    )
    # Identity is preserved from the cookie (cookie signs identity,
    # DB signs authorization).
    assert result["email"] == "victim@example.com"
    assert result["user_id"] == "u-1"


def test_log_safe_emitted_on_deactivation_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #143 scenario, framed by name: a deactivated user hitting
    a protected route MUST produce an ``auth.denied`` audit-trail
    event with ``reason="db_reval_miss"`` so operators can grep for
    deactivation denials in the log without scraping access logs.

    The ``user_id`` from the cookie is included for traceability, but
    no PII (``email``) leaks — the 12-field redaction list already
    covers it. See AGENTS.md rule 9 and the closed-list in
    ``app/core/logging.py``.
    """
    from app.core.auth_dependencies import require_authorized_user

    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **fields: object) -> None:
        captured.append((event, fields))

    monkeypatch.setattr("app.core.auth_dependencies.log_safe", _capture)

    # DB has no active row for the user (deactivation took effect).
    spy = _RevalSpy([])
    result = require_authorized_user(
        request=_make_request(),
        payload=_authorized_payload(email="victim@example.com"),
        client=spy,
    )

    assert isinstance(result, _Response)
    assert result.headers["location"] == "/unauthorized"

    denial_events = [
        (event, fields)
        for event, fields in captured
        if event == "auth.denied"
    ]
    assert denial_events, (
        f"deactivation denial MUST emit auth.denied (issue #146 "
        f"audit trail contract); got: {captured!r}"
    )
    # The deactivation-specific reason is db_reval_miss (the DB row is
    # gone), not writer_required / developer_required / cookie_no_flag /
    # no_session / no_email. operators grep by reason to distinguish
    # the deactivation signal from other deny signals.
    db_miss = [
        fields for _event, fields in denial_events
        if fields.get("reason") == "db_reval_miss"
    ]
    assert db_miss, (
        f"deactivation denial MUST have reason=db_reval_miss; "
        f"got: {denial_events!r}"
    )
    fields = db_miss[0]
    assert fields.get("user_id") == "u-1", (
        "user_id is the operator-facing identifier — cookie-supplied, "
        "non-PII; must be present on the event for traceability"
    )
    # PII (email) MUST NOT leak through the audit log even though the
    # cookie carries it.
    assert "email" not in fields, (
        "email is on the closed 12-field redaction list and MUST NOT "
        "be passed to log_safe (rule 9 + REDACTED_FIELDS in "
        "app/core/logging.py)"
    )


def test_session_docstring_no_longer_lies() -> None:
    """Issue #143 scenario: ``app/core/session.py`` MUST NOT advertise
    behavior the code does not have. The pre-#143 docstring claimed:

        ``per-request authorization is enforced by the auth middleware
        by looking up the email in the authorized_users table``

    That sentence was a lie — the middleware never opened a DB
    connection. Now (post-#143) the cookie signs **identity** and the
    dep (``require_authorized_user``) re-validates authorization.

    This test parses ``app/core/session.py`` with ``ast``, reads the
    module docstring, and asserts the lying text is absent. It is a
    regression guard for the docstring fix: rule 10 of the
    web-security-quality-baseline forbids security docstrings that
    describe what the code does *not* do.
    """
    import ast
    from pathlib import Path

    session_path = Path(__file__).resolve().parents[1] / "app" / "core" / "session.py"
    tree = ast.parse(session_path.read_text(encoding="utf-8"))
    module_docstring = ast.get_docstring(tree)

    assert module_docstring is not None, (
        "app/core/session.py MUST have a module docstring — the cookie "
        "session model is the front door of the auth layer and a "
        "missing docstring would be a regression to a harder-to-debug "
        "state than a wrong one"
    )

    lying_text = (
        "per-request authorization is enforced by the auth middleware "
        "by looking up the email in the authorized_users table"
    )
    assert lying_text not in module_docstring, (
        f"app/core/session.py docstring still contains the lying claim "
        f"\"{lying_text}\" — that text described the pre-#143 (now-fixed) "
        f"middleware behavior the code never actually had. Rule 10 of the "
        f"web-security-quality-baseline requires security docstrings to "
        f"describe what the code DOES, not what it doesn't. The current "
        f"docstring already explains the post-#143 model (cookie = "
        f"identity, dep = per-request DB revalidation with TTL cache); "
        f"the old claim must not come back.\n"
        f"current docstring:\n{module_docstring}"
    )

    # Also pin the positive contract: the docstring must mention the
    # refactored authorization model so a sloppy future edit that
    # removes the lying text but accidentally drops the accurate
    # explanation still fails.
    assert "re-validated" in module_docstring or "re-validate" in module_docstring, (
        "post-#143 session.py docstring MUST explain that authorization "
        "is re-validated per request (the security-critical contract)."
    )


def test_no_regression_for_active_users() -> None:
    """Issue #143 scenario, regression guard: an active user with a
    valid cookie MUST still get through after the fix — the per-request
    revalidation must not turn the door into a wall for the legitimate
    happy path. ``require_authorized_user`` must return the dict payload
    with the DB-refreshed ``rol`` and the cookie's ``email`` /
    ``user_id`` preserved.
    """
    spy = _RevalSpy(
        [{"id": "u-1", "email": "u@e.com", "rol": "key_user", "activo": True}]
    )

    result = require_authorized_user(
        request=_make_request(), payload=_authorized_payload(), client=spy
    )

    assert not isinstance(result, _Response), (
        f"active user with valid cookie MUST be allowed through; got "
        f"redirect: {result!r}"
    )
    # The dep is a transparent wrapper — the payload that comes out
    # MUST carry the cookie's identity AND the DB's rol.
    assert result["email"] == "u@e.com"
    assert result["user_id"] == "u-1"
    assert result["rol"] == "key_user"
    assert spy.query_count == 1, (
        "first request from this email MUST consult the DB (cache was "
        "cleared by the autouse fixture); without that, the dep could "
        "short-circuit on a stale cache miss and skip re-validation"
    )
