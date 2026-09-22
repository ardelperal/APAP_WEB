"""CSRF defense-in-depth tests for the magic-link exemption (M3.4, issue #651).

This file pins the contract of the ``CsrfMiddleware`` exemption granted
to the magic-link login flow. The exemption mirrors the auth-layer
``PUBLIC_PATHS`` whitelist merged in PR #855 (``/auth/magic/start`` and
``/auth/magic/verify`` are reachable without a session because the
single-use token in the email link IS the authorization for verify).

Hard rules (apap-security HR-10, apap-architecture HR-7):

- The exemption only covers the two paths in ``_CSRF_EXEMPT_PATHS``;
  any other POST MUST still be 403 without a session CSRF token.
- ``_populate_csrf_state`` must still run on the exempt path so a
  downstream template that reads ``request.state.csrf_token`` sees a
  populated value (defense-in-depth parity with safe methods).
- The constant is module-private (leading underscore) — the public
  surface is ``CsrfMiddleware`` only. A future PR that adds a public
  alias MUST first add a defensive rationale here.

The atoms exercise the module-level ``app`` via the ``client`` fixture
(the canonical pattern across ``tests/test_*.py``); the magic-link
router and its ports are wired onto ``app.state`` by the lifespan, so
no extra wiring is required for the shape tests. The verify atom
installs a fake ``magic_link_port`` so the route can complete without
a real DB; the start atom uses an empty JSON body and accepts either
a 200 (validation rejects the empty email) or a 422 (Pydantic
validation rejects the missing field) as proof the middleware did NOT
block the request. Both outcomes are NOT-403.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.core.csrf import _CSRF_EXEMPT_PATHS  # noqa: F401 — re-export for the atom below

# --- constant shape ------------------------------------------------------


def test_csrf_exempt_paths_has_exactly_two_entries() -> None:
    """``_CSRF_EXEMPT_PATHS`` contains exactly the two magic-link paths.

    Spec contract: the exemption covers ``/auth/magic/start`` and
    ``/auth/magic/verify`` only. Adding a third entry here MUST be
    justified by a matching security audit (and update this atom).
    A drift to a different path or an empty set fails the atom.
    """
    assert _CSRF_EXEMPT_PATHS == frozenset(
        {"/auth/magic/start", "/auth/magic/verify"}
    ), (
        f"_CSRF_EXEMPT_PATHS drifted from the verified set; "
        f"got {sorted(_CSRF_EXEMPT_PATHS)!r}. The magic-link "
        f"exemption is the only reason this frozenset exists — "
        f"every entry must be justified by a security audit and a "
        f"matching atom in this file."
    )
    assert len(_CSRF_EXEMPT_PATHS) == 2, (
        f"_CSRF_EXEMPT_PATHS must have exactly 2 entries; got "
        f"{len(_CSRF_EXEMPT_PATHS)}. A future slice that needs more "
        f"exempt paths must justify each one AND extend the shape "
        f"atom so the test surface tracks reality."
    )


# --- start endpoint exemption -------------------------------------------


async def test_post_auth_magic_start_with_empty_body_is_not_403(
    client: httpx.AsyncClient,
) -> None:
    """POST ``/auth/magic/start`` with an empty body MUST NOT be 403.

    The CSRF middleware short-circuits the request because the path
    is in ``_CSRF_EXEMPT_PATHS``. The handler then runs (FastAPI
    returns 400 on missing ``email`` key, or 422 on Pydantic
    validation; both are NOT-403). The atom proves the exemption
    works WITHOUT depending on the exact validation outcome.
    """
    response = await client.post(
        "/auth/magic/start", json={}, follow_redirects=False
    )
    assert response.status_code != 403, (
        f"middleware blocked /auth/magic/start with status "
        f"{response.status_code}; the path must be exempt. "
        f"Body: {response.text!r}"
    )


# --- verify endpoint exemption -----------------------------------------


class _OneShotMagicLinkPort:
    """In-process fake that consumes any token and returns an email.

    ``MagicLinkPort`` Protocol needs ``create_token``,
    ``consume_token`` and ``list_active``; the verify handler only
    calls ``consume_token``. The fake returns a deterministic email
    so the cookie payload is predictable.
    """

    def __init__(self, email: str = "ana@example.com") -> None:
        self._email = email

    def create_token(
        self,
        email: str,
        *,
        purpose: str = "login",
        ttl_seconds: int = 1800,
    ) -> str:
        return "raw-token-stub"

    def consume_token(self, raw_token: str) -> str | None:
        return self._email

    def list_active(self) -> list[dict[str, Any]]:
        return []


@pytest.fixture
def _fake_magic_link_port(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[_OneShotMagicLinkPort]:
    """Wire a fake ``MagicLinkPort`` onto ``app.state.magic_link_port``.

    The lifespan (``app.main.lifespan``) wires the real port + SMTP
    transport + session secret onto ``app.state``, but the unit-test
    client does NOT run the lifespan (per the ``client`` fixture in
    ``tests/conftest.py``). The verify handler reads
    ``app.state.magic_link_port`` AND ``app.state.session_secret``;
    without both set the route raises ``AttributeError`` before the
    302 redirect is returned. The fixture wires both.

    Annotated as ``Iterator[...]`` because the fixture is a generator
    (yield + no return value); mypy requires the annotation to
    reflect that. The yielded value (the fake port instance) is the
    type the test sees.
    """
    from app.core.config import get_settings
    from app.main import app as _app

    fake = _OneShotMagicLinkPort()
    _app.state.magic_link_port = fake
    _app.state.session_secret = get_settings().session_secret
    yield fake
    _app.state.__dict__.pop("magic_link_port", None)
    _app.state.__dict__.pop("session_secret", None)


async def test_get_auth_magic_verify_is_not_403(
    client: httpx.AsyncClient,
    _fake_magic_link_port: _OneShotMagicLinkPort,
) -> None:
    """GET ``/auth/magic/verify?token=...`` MUST NOT be 403.

    The middleware short-circuits because the path is in
    ``_CSRF_EXEMPT_PATHS``. The handler consumes the fake token,
    sets the ``apap_session`` cookie, and 302-redirects to ``/``.
    The atom proves the exemption works WITHOUT depending on the
    cookie payload shape (verified by the dedicated
    ``test_magic_link_routes.py`` integration atoms).
    """
    response = await client.get(
        "/auth/magic/verify?token=test-token",
        follow_redirects=False,
    )
    assert response.status_code != 403, (
        f"middleware blocked /auth/magic/verify with status "
        f"{response.status_code}; the path must be exempt. "
        f"Body: {response.text!r}"
    )
    # Sanity: the handler ran (the redirect was issued by the
    # route, not the auth middleware). The status is either 200/302
    # (happy path) or 422 (Pydantic validation); both are NOT-403
    # AND not the auth middleware's 302 to ``/login``.
    if response.status_code == 302:
        location = response.headers.get("location", "")
        # The auth middleware's redirect to ``/login`` would mean
        # the route was NOT reached; that's a regression.
        assert location != "/login", (
            f"/auth/magic/verify was redirected to /login "
            f"({location!r}); the magic-link handler did not run. "
            f"Either the exemption is not active or the magic_link_port "
            f"fixture did not wire correctly."
        )


# --- parametrized negative coverage -------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/animales"),
        ("POST", "/voluntarios"),
        ("POST", "/entradas"),
        ("POST", "/admin/users"),
        ("PUT", "/animales/abc-123"),
        ("DELETE", "/animales/abc-123"),
    ],
)
async def test_exemption_does_not_extend_to_other_routes(
    client: httpx.AsyncClient,
    method: str,
    path: str,
) -> None:
    """The CSRF exemption MUST NOT extend to any route outside ``_CSRF_EXEMPT_PATHS``.

    Defense-in-depth companion to the two atoms above: a regression
    that accidentally widens the exemption (e.g. by adding a ``not
    in`` reversal, or by including ``/animales`` in the set) is
    caught here. Every parametrized entry is a route the project
    ships with; the atom asserts the middleware still rejects the
    request without a CSRF token, even though the magic-link
    paths are exempt.

    The atom logs in first because ``protect_user_facing_routes``
    runs BEFORE ``CsrfMiddleware`` (outer middleware); without a
    session, the auth layer redirects to ``/login`` and the CSRF
    check never runs. With a session, the request reaches
    ``CsrfMiddleware`` which rejects with 403 because the supplied
    token does not match the session.
    """
    from app.core.config import get_settings
    from app.core.session import session_cookie_name, write_session

    settings = get_settings()
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "session-csrf-token",
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)

    response = await client.request(
        method,
        path,
        data={"csrf_token": "deliberately-wrong", "name": "x"},
        follow_redirects=False,
    )
    assert response.status_code == 403, (
        f"{method} {path} returned {response.status_code} (expected "
        f"403 — no CSRF token was sent). The magic-link exemption "
        f"must NOT extend to other routes. See app/core/csrf.py "
        f"and the _CSRF_EXEMPT_PATHS frozenset."
    )


# --- CSRF feature flag (lines 184-186 coverage) ------------------------


async def test_csrf_disabled_short_circuits_dispatch(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``Settings.csrf_enabled=False``, the middleware short-circuits.

    Coverage guard: lines 184-186 of ``app/core/csrf.py`` (the
    ``if not settings.csrf_enabled`` branch + ``log_safe`` call) are
    reachable only when ``csrf_enabled`` is False AND the request is
    not in ``_CSRF_EXEMPT_PATHS`` AND the method is not in
    ``SAFE_METHODS``. The pre-existing atom in
    ``test_csrf_middleware.py`` does NOT cover this branch because
    its ``monkeypatch.setattr(config_module, "get_settings", ...)``
    targets the source module, not ``csrf.get_settings`` (csrf.py
    imports the binding via ``from ... import get_settings`` so the
    local reference is independent of the source module's attribute).
    This atom patches ``app.core.csrf.get_settings`` directly so the
    branch is exercised, keeping the CRAP baseline pinned at 13.00.
    """
    from app.core import config as config_module
    from app.core import csrf as csrf_module
    from app.core.session import session_cookie_name, write_session

    # Patch csrf.py's local binding so the ``get_settings()`` call
    # inside ``dispatch`` returns ``csrf_enabled=False``. Also patch
    # ``config_module.get_settings`` for the helpers that read the
    # session secret (read_session_payload reads it via get_settings).
    def patched_get_settings():
        return config_module.Settings().model_copy(
            update={"csrf_enabled": False}
        )

    monkeypatch.setattr(csrf_module, "get_settings", patched_get_settings)
    monkeypatch.setattr(
        config_module, "get_settings", patched_get_settings
    )

    # Log in so the outer ``protect_user_facing_routes`` middleware
    # passes the request through to ``CsrfMiddleware.dispatch``.
    settings = patched_get_settings()
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "session-csrf-token",
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)

    response = await client.post(
        "/animales",
        data={"csrf_token": "no-token-needed-when-disabled", "name": "x"},
        follow_redirects=False,
    )
    # The csrf.disabled branch returned call_next without checking
    # the token. The response status depends on what the route does
    # downstream (the test bypasses the LocalBackend, so the exact
    # status is not the assertion; what matters is the response is
    # NOT 403 from the CSRF middleware).
    assert response.status_code != 403, (
        f"CsrfMiddleware rejected with 403 even though csrf_enabled "
        f"was False; the feature-flag short-circuit did not run. "
        f"Either the monkeypatch didn't reach csrf.get_settings or "
        f"the dispatch logic changed. status={response.status_code}, "
        f"body={response.text!r}"
    )


# --- CSRF happy path (line 231 coverage) --------------------------------


async def test_post_with_valid_csrf_token_passes_csrf(
    client: httpx.AsyncClient,
) -> None:
    """POST with a valid session-bound CSRF token reaches ``call_next``.

    Coverage guard for line 231 of ``app/core/csrf.py`` (the success
    branch — ``hmac.compare_digest`` matched and ``call_next`` is
    invoked). The dispatch CRAP ratchet (``BASELINE_CRAP``=13.00)
    requires 100% line coverage of the dispatch function; without
    this atom the success path is unexercised when ``test_csrf.py``
    is run in isolation (e.g. by ``pytest app/core/csrf.py
    tests/test_csrf.py`` in CI's per-file CRAP check), and CRAP ticks
    above the baseline to 13.01.
    """
    from app.core.config import get_settings
    from app.core.session import session_cookie_name, write_session

    settings = get_settings()
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "happy-path-csrf-token",
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)

    response = await client.post(
        "/animales",
        headers={"X-CSRFToken": "happy-path-csrf-token"},
        data={
            "NCHIP": "985112004409871",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
        },
        follow_redirects=False,
    )
    assert response.status_code != 403, (
        f"CsrfMiddleware rejected a valid token; the dispatch success "
        f"path did not run. status={response.status_code}, "
        f"body={response.text!r}"
    )
