"""Tests for the Google OAuth login flow (/login, /auth/callback, /logout).

The InsForge REST client is replaced with a fake via FastAPI's
``app.dependency_overrides[get_insforge_client]`` mechanism, so the
tests run in-process without HTTP and without needing real Google
credentials.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.main import app, get_insforge_client


class _FakeInsForge(InsForgeClient):
    """In-process InsForge stand-in. Pre-programmed responses per test."""

    def __init__(self) -> None:
        # Skip the parent __init__; we override every method.
        self.start_google_oauth_response: str = "https://accounts.google.com/o/oauth2/v2/auth?code_challenge=abc"
        self.exchange_result: dict = {
            "token": "jwt-from-insforge",
            "user_id": "u-from-insforge",
            "email": "ardelperal@gmail.com",
        }
        self.get_user_by_email_response: dict | None = {
            "id": "u-db",
            "email": "ardelperal@gmail.com",
            "rol": "developer",
            "activo": True,
        }
        self.list_users_response: list[dict] = []
        self.add_user_response: dict = {
            "id": "u-new",
            "email": "new@example.com",
            "rol": "key_user",
            "activo": True,
            "fecha_alta": "2026-06-17T00:00:00Z",
        }
        self.deactivate_user_response: dict | None = {
            "id": "u-1",
            "email": "a@b.com",
            "rol": "key_user",
            "activo": False,
        }

    # We override the methods used by the routes; everything else is a
    # deliberate no-op so accidental calls are loud AttributeErrors.
    def start_google_oauth(
        self,
        redirect_uri: str,
        code_challenge: str,
    ) -> str:  # type: ignore[override]
        return self.start_google_oauth_response

    def exchange_google_oauth_code(  # type: ignore[override]
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ):
        from app.core.insforge import InsForgeUser, OAuthExchangeResult

        return OAuthExchangeResult(
            token=self.exchange_result["token"],
            user=InsForgeUser(
                id=self.exchange_result["user_id"],
                email=self.exchange_result["email"],
            ),
        )

    def execute_sql(self, query, params=None):  # type: ignore[override]
        # Dispatch on the SQL shape; each test sets the matching
        # ``*_response`` attribute on this fake.
        if "ORDER BY fecha_alta DESC" in query:
            return list(self.list_users_response)
        if "INSERT INTO usuarios_autorizados" in query and "VALUES" in query:
            return [dict(self.add_user_response)]
        if "SET activo = false" in query:
            row = self.deactivate_user_response
            return [dict(row)] if row else []
        if "SELECT id, email, rol, activo" in query and "FROM usuarios_autorizados" in query:
            row = self.get_user_by_email_response
            return [dict(row)] if row else []
        return []


@pytest.fixture
def fake_insforge() -> _FakeInsForge:
    """Replace the InsForge dependency with a fake for the duration of the test."""
    fake = _FakeInsForge()
    app.dependency_overrides[get_insforge_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_insforge_client, None)


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


async def test_login_redirects_to_google_with_pkce(
    client: httpx.AsyncClient,
    fake_insforge: _FakeInsForge,
    google_configured: None,
) -> None:
    """``GET /login`` returns a 302 to the Google auth URL from InsForge."""
    fake_insforge.start_google_oauth_response = (
        "https://accounts.google.com/o/oauth2/v2/auth?code_challenge=xyz&scope=openid+email+profile"
    )

    response = await client.get("/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == fake_insforge.start_google_oauth_response
    # A short-lived PKCE cookie must be set.
    assert "apap_pkce" in response.cookies


async def test_login_returns_503_when_google_not_configured(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge, monkeypatch
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
) -> None:
    """If the PKCE cookie is missing, the callback redirects to /login."""
    response = await client.get(
        "/auth/callback", params={"code": "abc"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_callback_with_tampered_pkce_cookie_redirects_to_login(
    client: httpx.AsyncClient,
) -> None:
    """A PKCE cookie signed with a different secret is rejected."""
    client.cookies.set("apap_pkce", "definitely-not-a-valid-token")
    response = await client.get(
        "/auth/callback", params={"code": "abc"}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_callback_with_unauthorized_email_redirects_to_unauthorized(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    """If the email is not in usuarios_autorizados, the callback redirects to /unauthorized."""
    fake_insforge.get_user_by_email_response = None

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
    fake_insforge: _FakeInsForge,
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
    print("DEBUG session_cookie:", repr(session_cookie))
    assert session_cookie
    decoded = read_session(session_cookie, secret=settings.session_secret)
    print("DEBUG decoded:", decoded)
    assert decoded == {
        "email": "ardelperal@gmail.com",
        "rol": "developer",
        "user_id": "u-db",
    }


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
