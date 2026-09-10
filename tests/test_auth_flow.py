"""Tests for the Google OAuth login flow (/login, /auth/callback, /logout).

The OAuth port and auth-users port are injected via app.state for tests,
so the tests run in-process without HTTP and without needing real Google
credentials.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.di.auth_di import get_auth_users_port
from app.core.di.oauth_di import get_oauth_port
from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser
from app.main import app


class _FakeAuthUsersPort:
    """In-process fake for the :class:`AuthUsersPort` Protocol.

    The OAuth callback use case only calls
    :meth:`get_user_by_email`; the rest of the Protocol is implemented
    as defensive ``NotImplementedError`` stubs so a future caller that
    reaches for one of them gets a clear failure instead of a silent
    empty list.

    The ``get_user_by_email_response`` attribute mirrors the legacy
    ``_FakeSqlExecutor`` test API so tests that flip it to ``None``
    keep simulating the unauthorized-email path. When the attribute is
    a dict, the fake builds the canonical :class:`AuthorizedUser`
    entity the application layer expects (the legacy ``SqlExecutor``
    fake returned raw rows that the (now-broken) adapter would map to
    ``AuthorizedUser.from_row`` — the DI fix means the test owns that
    mapping, so the fake exposes ``AuthorizedUser`` directly).
    """

    def __init__(self) -> None:
        self.get_user_by_email_response: dict | None = {
            "id": "u-db",
            "email": "ardelperal@gmail.com",
            "rol": "developer",
            "activo": True,
        }

    def _build_user(self, row: dict) -> AuthorizedUser:
        return AuthorizedUser(
            id=row["id"],
            email=row["email"],
            rol=Rol(row["rol"]),
            active=row["activo"],
        )

    def get_user_by_email(self, email: str) -> AuthorizedUser | None:
        row = self.get_user_by_email_response
        if row is None:
            return None
        if row.get("email") != email:
            return None
        return self._build_user(row)

    # --- Protocol surface: not exercised by the OAuth callback. -----

    def check_email_taken(self, email: str) -> bool:
        raise NotImplementedError

    def list_authorized_users(self) -> list[AuthorizedUser]:
        raise NotImplementedError

    def add_authorized_user(self, email: str, rol: Rol, added_by: str) -> AuthorizedUser:
        raise NotImplementedError

    def get_user_by_id(self, user_id: str) -> AuthorizedUser | None:
        raise NotImplementedError

    def deactivate_authorized_user(self, user_id: str) -> AuthorizedUser:
        raise NotImplementedError

    def ensure_schema_and_seed(self, initial_admin_email: str) -> None:
        raise NotImplementedError


class _FakeOAuthPort:
    """Fake OAuthPort for auth flow tests."""

    def __init__(self) -> None:
        self.start_google_oauth_response: str = "https://accounts.google.com/o/oauth2/v2/auth?code_challenge=abc"
        self.exchange_result: dict = {
            "token": "jwt-from-insforge",
            "user_id": "u-from-insforge",
            "email": "ardelperal@gmail.com",
        }

    def start_google_login(self, redirect_uri: str):
        from app.core.domain.oauth import PkcePair
        return self.start_google_oauth_response, PkcePair(
            code_verifier="test-verifier",
            code_challenge="test-challenge",
        )

    def exchange_oauth_code(self, oauth_code: str, code_verifier: str):
        from app.core.ports.oauth_port import OAuthUser
        return OAuthUser(
            id=self.exchange_result["user_id"],
            email=self.exchange_result["email"],
        )

    def exchange_google_oauth_code(self, code: str, code_verifier: str, redirect_uri: str):
        from app.core.ports.oauth_port import OAuthUser
        return OAuthUser(
            id=self.exchange_result["user_id"],
            email=self.exchange_result["email"],
        )


@pytest.fixture
def fake_insforge() -> tuple[_FakeAuthUsersPort, _FakeOAuthPort]:
    """Inject fake ports via app.state for the duration of the test.

    The fixture exposes the same two-tuple shape the legacy fixture
    used (``(auth_users_port, oauth_port)``). Tests mutate
    ``fake_insforge[0].get_user_by_email_response = None`` to drive
    the unauthorized-email branch; the DI providers
    (:func:`app.core.di.auth_di.get_auth_users_port` and
    :func:`app.core.di.oauth_di.get_oauth_port`) read ``app.state`` and
    yield these fakes verbatim.
    """
    fake_auth_port = _FakeAuthUsersPort()
    fake_oauth = _FakeOAuthPort()

    # Inject fakes via app.state; the DI providers check these first.
    app.state._auth_users_port = fake_auth_port
    app.state._oauth_port = fake_oauth

    yield fake_auth_port, fake_oauth

    # Cleanup
    if hasattr(app.state, "_auth_users_port"):
        delattr(app.state, "_auth_users_port")
    if hasattr(app.state, "_oauth_port"):
        delattr(app.state, "_oauth_port")


@pytest.fixture
def google_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate the Google OAuth settings so the /login route proceeds."""
    from app.core import config as config_module

    original_get_settings = config_module.get_settings

    def patched_get_settings():

        return original_get_settings().model_copy(
            update={
                "google_client_id": "test-client-id",
                "google_client_secret": "test-client-secret",
                "google_redirect_uri": "http://testserver/auth/callback",
            }
        )

    monkeypatch.setattr(config_module, "get_settings", patched_get_settings)


# --- /login -----------------------------------------------------------------


async def test_login_renders_apap_login_page(
    client: httpx.AsyncClient,
    google_configured: None,
    ) -> None:
    """``GET /login`` renders the magic-link login form.

    The InsForge-era "Entrar con Gmail" button has been removed
    (issue #728, Phase 2). The page now shows a magic-link form
    that POSTs to ``/auth/magic/start``.
    """

    response = await client.get("/login", follow_redirects=False)

    assert response.status_code == 200
    assert "/auth/magic/start" in response.text
    assert "Correo autorizado" in response.text
    assert "Enviar enlace" in response.text
    assert "Entrar con Gmail" not in response.text
    assert 'href="/auth/google"' not in response.text



async def test_auth_google_redirects_to_google_with_pkce(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
    google_configured: None,
) -> None:
    """``GET /auth/google`` returns a 302 to the Google auth URL from the OAuth port."""
    fake_insforge[1].start_google_oauth_response = (
        "https://accounts.google.com/o/oauth2/v2/auth?code_challenge=xyz&scope=openid+email+profile"
    )

    response = await client.get("/auth/google", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == fake_insforge[1].start_google_oauth_response
    # A short-lived PKCE cookie must be set.
    assert "apap_pkce" in response.cookies


async def test_login_returns_503_when_google_not_configured(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the Google client id/secret are not configured, /login returns 503 with a clear message."""

    from app.core import config as config_module

    original_settings = config_module.get_settings

    def fake_get_settings():
        return original_settings().model_copy(
            update={"google_client_id": "", "google_client_secret": ""}
        )

    monkeypatch.setattr(config_module, "get_settings", fake_get_settings)

    response = await client.get("/login", follow_redirects=False)

    assert response.status_code == 503
    assert b"Google OAuth" in response.content


# --- /auth/callback ----------------------------------------------------------


async def test_callback_without_pkce_cookie_redirects_to_login(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
) -> None:
    """If the PKCE cookie is missing, the callback redirects to /login."""
    response = await client.get(
        "/auth/callback", params={"code": "abc"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_callback_with_tampered_pkce_cookie_redirects_to_login(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
) -> None:
    """A PKCE cookie signed with a different secret is rejected."""
    client.cookies.set("apap_pkce", "definitely-not-a-valid-token")
    response = await client.get(
        "/auth/callback", params={"code": "abc"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_callback_with_unauthorized_email_redirects_to_unauthorized(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
) -> None:
    """If the email is not in usuarios_autorizados, the callback redirects to /unauthorized."""

    fake_insforge[0].get_user_by_email_response = None

    # Simulate a valid PKCE cookie issued by the /login flow.
    from app.core.config import get_settings
    from app.core.session import write_session

    settings = get_settings()
    token = write_session({"code_verifier": "verifier-123"}, secret=settings.session_secret)
    client.cookies.set("apap_pkce", token)

    response = await client.get(
        "/auth/callback", params={"code": "google-code"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"
    # The PKCE cookie is cleared.
    assert "apap_pkce" not in response.cookies or response.cookies.get("apap_pkce") == ""


async def test_callback_issues_session_cookie_and_redirects_home(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
    google_configured: None,
) -> None:
    """A valid exchange yields a session cookie and a redirect to the home page."""
    from app.core.config import get_settings
    from app.core.session import read_session, session_cookie_name, write_session

    settings = get_settings()
    pkce_token = write_session(
        {"code_verifier": "verifier-abc"}, secret=settings.session_secret
    )
    client.cookies.set("apap_pkce", pkce_token)

    response = await client.get(
        "/auth/callback", params={"code": "google-code"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    # The AsyncClient stores the cookies that the server sent; this is
    # the right place to read the value (httpx parses the Set-Cookie
    # header correctly here, where ``response.cookies`` can keep the
    # outer quotes around values that contain JSON).
    session_cookie = client.cookies.get(session_cookie_name())
    assert session_cookie
    decoded = read_session(session_cookie, secret=settings.session_secret)
    # ``is_authorized`` se escribe en el callback desde el campo
    # ``activo`` del registro de usuarios_autorizados (fix P0 de la
    # code review VOL-01). El fake expone ``activo: True``.
    #
    # PR-5B (REQ-AH-6) also adds ``csrf_token`` to the signed payload.
    # The token is generated via ``secrets.token_urlsafe(32)`` so it is
    # always >= 32 chars. We assert membership + shape instead of full
    # equality because the token is random per request.
    assert decoded is not None
    assert decoded["email"] == "ardelperal@gmail.com"
    assert decoded["rol"] == "developer"
    assert decoded["user_id"] == "u-db"
    assert decoded["is_authorized"] is True
    csrf_token = decoded.get("csrf_token")
    assert isinstance(csrf_token, str)
    assert len(csrf_token) >= 32


async def test_callback_exchanges_oauth_code_for_session(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
    google_configured: None,
) -> None:
    """LocalBackend's hosted OAuth proxy sends ``oauth_code`` (not ``code``)
    to the app callback. The handler must accept the new parameter,
    exchange it via the OAuth port with the PKCE verifier, and create a
    session exactly like the legacy Google code flow did.

    This is the contract test that pins the post-proxy callback spec
    (``app/core/application/oauth/callback.py`` -> ``OAuthPort.exchange_oauth_code``).
    """
    from app.core.config import get_settings
    from app.core.session import read_session, session_cookie_name, write_session

    settings = get_settings()
    pkce_token = write_session(
        {"code_verifier": "verifier-abc"}, secret=settings.session_secret
    )
    client.cookies.set("apap_pkce", pkce_token)

    response = await client.get(
        "/auth/callback", params={"oauth_code": "oauth-code-xyz"},
        follow_redirects=False,
    )

    assert response.status_code == 302, (
        f"oauth_code callback should succeed (302), got {response.status_code}: "
        f"{response.text[:200]}"
    )
    assert response.headers["location"] == "/"
    session_cookie = client.cookies.get(session_cookie_name())
    assert session_cookie
    decoded = read_session(session_cookie, secret=settings.session_secret)
    assert decoded is not None
    assert decoded["email"] == "ardelperal@gmail.com"
    assert decoded["is_authorized"] is True


async def test_login_apap_pkce_cookie_uses_samesite_lax_for_oauth_callback(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
    google_configured: None,
) -> None:
    """``/login`` must issue ``apap_pkce`` with ``SameSite=Lax``.

    OAuth providers return to ``/auth/callback`` through a top-level
    cross-site GET. ``SameSite=Strict`` is not sent on that navigation,
    so the callback cannot recover the verifier and redirects to
    ``/login`` again, producing ERR_TOO_MANY_REDIRECTS in Chrome.
    ``Lax`` is the correct OAuth setting: it allows the callback GET
    while still withholding the cookie from cross-site subrequests and
    unsafe form posts.
    """
    login_response = await client.get("/auth/google", follow_redirects=False)
    set_cookie_headers = login_response.headers.get_list("set-cookie")
    pkce_cookies = [c for c in set_cookie_headers if c.startswith("apap_pkce=")]
    assert pkce_cookies, "expected /login to set apap_pkce cookie"
    # httpx normalizes the directive casing; check the lowercase token.
    pkce_cookie = pkce_cookies[0]
    assert "samesite=lax" in pkce_cookie.lower()


async def test_callback_apap_session_cookie_uses_samesite_strict(
    client: httpx.AsyncClient,
    fake_insforge: tuple[_FakeAuthUsersPort, _FakeOAuthPort],
    google_configured: None,
) -> None:
    """``/auth/callback`` issues ``apap_session`` with ``SameSite=Strict``.

    Per REQ-AH-5 the session cookie must ship ``SameSite=Strict`` so a
    cross-site form replay cannot use it as an implicit auth token.
    The CSRF middleware (REQ-AH-8) is the secondary defense for any
    browser that does not honor Strict.
    """
    from app.core.config import get_settings
    from app.core.session import write_session

    settings = get_settings()
    pkce_token = write_session(
        {"code_verifier": "verifier-session-strict"}, secret=settings.session_secret
    )
    client.cookies.set("apap_pkce", pkce_token)

    response = await client.get(
        "/auth/callback", params={"code": "google-code"}, follow_redirects=False
    )

    assert response.status_code == 302
    set_cookie_headers = response.headers.get_list("set-cookie")
    session_cookies = [c for c in set_cookie_headers if c.startswith("apap_session=")]
    assert session_cookies, "expected /auth/callback to set apap_session cookie"
    session_cookie = session_cookies[0]
    assert "samesite=strict" in session_cookie.lower()


# --- /logout ----------------------------------------------------------------


async def test_logout_clears_session_cookie_and_redirects_home(
    client: httpx.AsyncClient,
) -> None:
    """``GET /logout`` clears the session cookie and redirects to /."""
    response = await client.get("/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    # The response carries a Set-Cookie that expires the session
    # immediately (max-age=0 and a past Expires). httpx's client
    # cookie jar drops such cookies, so the right assertions are on
    # the raw header.
    set_cookies = response.headers.get_list("set-cookie")
    assert any(
        c.startswith("apap_session=") and "Max-Age=0" in c for c in set_cookies
    )
