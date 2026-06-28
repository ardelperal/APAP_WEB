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
from unittest.mock import patch

from fastapi import Request

from app.core.auth_dependencies import (
    get_current_user_optional,
    get_insforge_client_dep,
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
    """The implementation MUST be a generator (yields + finally closes).

    Without the ``yield`` + ``finally``, the InsForge client's
    httpx transport would leak on every request. This is a
    defence-in-depth check: even if the annotation changes, the
    body must still be a generator function.
    """
    assert inspect.isgeneratorfunction(get_insforge_client_dep), (
        "get_insforge_client_dep must be a generator function "
        "(uses yield + finally) so the InsForge client is closed "
        "even on handler exceptions."
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
