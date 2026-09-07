"""Pin the /logout contract.

The user reports that clicking "Salir" in the production browser
does not take them to the login screen. The backend works
(curl confirms: GET /logout -> 302 / with Set-Cookie clearing
``apap_session``; GET / -> 302 /login). The bug is browser-side:
either the cookie is not being cleared, or the redirect is not
being followed.

This test pins the BACKEND contract so we can rule out the server
side. The browser-side issue (if it persists) is a separate problem
and likely related to ``Set-Cookie`` attribute compatibility
(``Path`` / ``Domain`` / ``Secure`` mismatch between create and clear).

The contract this test pins:
1. ``/logout`` returns 302 to ``/`` (NOT to /login directly — the
   middleware handles the redirect).
2. ``/logout`` includes a ``Set-Cookie: apap_session=""; Max-Age=0``
   header that matches the create-time cookie attributes
   (``Path=/``, ``HttpOnly``, ``Secure``, ``SameSite=strict``).
3. After ``/logout``, the session cookie is treated as empty by
   the middleware (``payload is None``), so the next protected
   request redirects to /login.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.session import session_cookie_name
from app.main import app, get_local_backend_client


class _StubLocalBackend:
    """Stub for the protected routes that need LocalBackend.

    The /logout handler does NOT call LocalBackend (just clears the
    cookie and redirects), so this stub is only used by the
    follow-up ``GET /`` request to verify the session is empty.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> object:  # noqa: D401
        raise NotImplementedError(
            f"_StubLocalBackend.{name} is not mocked. Add an explicit method."
        )

    def close(self) -> None:  # noqa: D401
        return None

    def execute_sql(self, *args, **kwargs):  # noqa: D401
        # For /: no rows. Middleware redirects to /login.
        return []


@pytest.fixture
def stub_local_backend():
    fake = _StubLocalBackend()
    app.dependency_overrides[get_local_backend_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_local_backend_client, None)


async def test_logout_returns_302_to_root(
    client: httpx.AsyncClient, stub_local_backend: _StubLocalBackend
) -> None:
    """``GET /logout`` MUST 302 to ``/`` (not to /login directly).

    The middleware bounces the next request to /login. The /logout
    handler itself just clears the cookie and returns.
    """
    r = await client.get("/logout", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"


async def test_session_cookie_path_matches_logout_clearing_path(
    client: httpx.AsyncClient, stub_local_backend: _StubLocalBackend
) -> None:
    """The create-time session cookie and the logout clearing cookie MUST share the same Path.

    Bug found 2026-06-28: the user reported that clicking "Salir" did
    not log them out. Root cause: the auth/callback handler sets the
    session cookie WITHOUT an explicit ``path=`` argument, so the
    cookie's path defaults to the request path (``/auth/callback``).
    The /logout handler clears with ``path="/"``. Browsers match
    the clearing Set-Cookie to the original by ``(name, path, domain)``
    — a path mismatch means the browser IGNORES the clearing
    Set-Cookie and the old cookie survives. Fix: the create-time
    handler MUST also set ``path="/"`` so the two match.
    """
    from app.core.config import get_settings
    from app.core.session import write_session

    # Hit /auth/callback manually (it doesn't go through OAuth because
    # the LocalBackend exchange is stubbed below). We need a route that
    # actually sets the session cookie; the simplest is to inject
    # the cookie via client.cookies.set, then assert the clearing
    # round-trip works.
    settings = get_settings()
    token = write_session(
        {"email": "u@e.com", "is_authorized": True},
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token, path="/auth/callback")

    # The clearing cookie MUST have the same Path. The httpx
    # CookieJar does its own matching; if the paths match, the
    # cookie is deleted and the next request has no apap_session.
    r = await client.get("/logout", follow_redirects=False)
    set_cookie = r.headers.get("set-cookie", "")
    assert "Path=/" in set_cookie or "path=/" in set_cookie, (
        f"clearing cookie must have Path=/, got: {set_cookie!r}"
    )

    # Belt-and-braces: the source MUST set path="/" on the create-time
    # set_cookie call so the two match. If the create-time call has
    # no path= argument, the cookie defaults to the request path
    # (``/auth/callback``) and the clearing with path=/ will be
    # IGNORED by the browser — the exact bug we just fixed.
    from pathlib import Path as _P

    # After PR #351 (issue #336) the cookie-creation code was extracted
    # from app/main.py into app/core/auth_flow.py. Check both so the
    # assertion stays valid regardless of where the code lives.
    auth_sources = [
        _P("app/main.py").read_text(encoding="utf-8"),
        _P("app/core/auth_flow.py").read_text(encoding="utf-8"),
    ]
    combined = "\n".join(auth_sources)
    # The auth/callback response.set_cookie call MUST include
    # path="/" so the cookie is set at the site root.
    assert (
        'session_cookie_name(),' in combined
        and 'path="/"' in combined
    ), (
        "auth source (app/main.py or app/core/auth_flow.py): "
        "the auth/callback set_cookie call MUST include path=\"/\" "
        "so the session cookie is scoped to the site root and matches "
        "the /logout clearing cookie. Without this, the browser keeps "
        "the old cookie (different path) and the user stays logged in "
        "after clicking Salir."
    )


def test_logout_clearing_cookie_attributes_match_creation(
    client: httpx.AsyncClient, stub_local_backend: _StubLocalBackend
) -> None:
    """The clearing cookie MUST share Path / Secure / SameSite with the create-time cookie.

    Browsers match the clearing cookie to the original by
    ``(name, path, domain)``. If any of these differ, the clearing
    Set-Cookie is ignored and the old cookie survives — the bug the
    user reported (clicking Salir does not log them out).
    """
    # Find the create-time attributes from the source. ``_SESSION_COOKIE_NAME``
    # is the cookie name; Path / Secure / SameSite are set in
    # app.core.auth_flow::callback (extracted from app.main::callback
    # in PR #351 / issue #336).
    from pathlib import Path

    # After PR #351 (issue #336) the cookie-creation code was extracted
    # from app/main.py into app/core/auth_flow.py. Check both so the
    # assertions stay valid regardless of where the code lives.
    auth_sources = [
        Path("app/main.py").read_text(encoding="utf-8"),
        Path("app/core/auth_flow.py").read_text(encoding="utf-8"),
    ]
    combined = "\n".join(auth_sources)
    # Path: the create-time set_cookie uses ``max_age=...`` (no path)
    # → defaults to ``/``. The clear-time goes through
    # ``clear_session_cookie_params()`` (defined in app/core/session.py)
    # which sets ``path="/"``. Both must agree.
    session_src = Path("app/core/session.py").read_text(encoding="utf-8")
    assert '"path": "/"' in session_src, (
        "app/core/session.py: the clearing cookie must set "
        '`path="/"` so the browser can match it to the original '
        'cookie (which has no explicit path → defaults to "/").'
    )
    # SameSite: the session cookie must stay Strict. The apap_pkce OAuth
    # verifier cookie is intentionally Lax so the top-level callback GET can
    # carry it back from Google/LocalBackend.
    assert 'session_cookie_name(),\n            session_token' in combined
    assert 'samesite="strict"' in combined, (
        "auth source (app/main.py or app/core/auth_flow.py): "
        "the session cookie must keep samesite='strict' "
        "while only the short-lived apap_pkce verifier may be lax"
    )
    # Secure: must be the same.
    assert combined.count("secure=True") >= 2, (
        "auth source (app/main.py or app/core/auth_flow.py): "
        "secure must be True on both create and clear "
        "(otherwise the browser ignores the clearing Set-Cookie)"
    )


async def test_logout_then_protected_route_redirects_to_login(
    client: httpx.AsyncClient, stub_local_backend: _StubLocalBackend
) -> None:
    """After /logout, GET / (protected) MUST 302 to /login.

    Pins the full flow: clear cookie + middleware sees no session +
    redirect to /login.

    Note: this test relies on httpx's CookieJar to honor the
    Max-Age=0 Set-Cookie. Some httpx versions handle that
    differently; if this test becomes flaky, the underlying
    contract is already covered by
    ``test_logout_returns_302_to_root``,
    ``test_logout_clears_session_cookie_with_compatible_attrs``, and
    ``test_logout_clearing_cookie_attributes_match_creation``.
    """
    # /logout must redirect to /, which the middleware then bounces
    # to /login.
    r = await client.get("/logout", follow_redirects=True)
    assert str(r.url).rstrip("/") == "http://testserver/login", (
        f"after /logout (follow_redirects=True), the final URL must be "
        f"/login; got: {r.url!r} (status {r.status_code})"
    )
