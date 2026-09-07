"""Tests for the hexagonal OAuth login flow slice.

The OAuth slice (``app/core/domain/oauth/``,
``app/core/ports/oauth_port.py``,
``app/core/application/oauth/``,
``app/core/adapters/insforge/oauth_insforge_adapter.py``,
``app/core/di/oauth_di.py``) is the 4th vertical slice of the
hexagonal refactor. These tests pin the new pattern at the
same three levels as the catalogos slice:

1. **Use cases** — thin delegators over the :class:`OAuthPort`
   Protocol. Tests use a recording fake implementing the
   Protocol; assertions are on the call, not on the transport.
2. **Adapter** — the InsForge adapter delegates to
   :class:`InsForgeClient` and projects the
   :class:`OAuthExchangeResult` shape to the typed
   :class:`OAuthUser` value object. Tests cover both the call
   delegation (the adapter calls the right client method with
   the right kwargs) and the PKCE pair generation.
3. **DI helper** — the per-request port construction uses the
   pooled :class:`InsForgeClient` when the lifespan is active,
   and falls back to a lazily-created client when the transport
   bypasses the lifespan.

The OLD API in ``app/core/auth_flow.py`` keeps the same
``register_auth_flow_routes`` factory; the route bodies now
delegate to the new use cases. The existing
``tests/test_auth_flow.py`` keeps its 11 tests as the regression
net for the legacy route shape (cookie names, SameSite flags,
the 503 body, the redirect URLs).
"""


from __future__ import annotations

from typing import Any

import pytest

from app.core.adapters.insforge.oauth_insforge_adapter import (
    InsForgeOAuthAdapter,
)
from app.core.application.oauth import (
    ClearSessionParams,
)
from app.core.application.oauth import (
    callback as callback_uc,
)
from app.core.application.oauth import (
    login_page as login_page_uc,
)
from app.core.application.oauth import (
    logout as logout_uc,
)
from app.core.application.oauth import (
    start_google_login as start_google_login_uc,
)
from app.core.config import Settings
from app.core.data_access import BackendError
from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser
from app.core.domain.oauth import (
    AuthenticatedSession,
    CallbackInvalidError,
    OAuthNotConfiguredError,
    PkcePair,
    UserNotAuthorizedError,
)
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.local_backend.oauth_google import exchange_local_oauth_code
from app.core.ports.oauth_port import OAuthPort, OAuthUser

# --- helpers ---------------------------------------------------------------


def _settings(**overrides) -> Settings:
    """Build a Settings instance with the OAuth env vars pre-populated."""
    base = dict(
        app_name="APAP_WEB",
        version="0.1.0",
        insforge_url="https://example.insforge.app",
        insforge_anon_key="",
        insforge_service_key="ik_test",
        session_secret="a" * 64,
        google_client_id="gid",
        google_client_secret="gsec",
        google_redirect_uri="https://app.example.com/auth/callback",
    )
    base.update(overrides)
    return Settings(**base)


# --- use cases (delegation) -------------------------------------------------


class _RecordingOAuthPort:
    """Recording fake that implements :class:`OAuthPort`.

    Returns canned responses the test set up. Used to assert the
    use case is a thin delegator (the call reaches the port, the
    port returns the canned response, the use case returns it
    unchanged or translates it as documented).
    """

    def __init__(
        self,
        auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth",
        pkce: PkcePair | None = None,
        exchange_user: OAuthUser | None = None,
    ) -> None:
        self.auth_url = auth_url
        self.pkce = pkce or PkcePair("verifier-123", "challenge-456")
        self.exchange_user = exchange_user or OAuthUser(
            id="u-1", email="ardelperal@gmail.com"
        )
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def start_google_login(self, redirect_uri: str) -> tuple[str, PkcePair]:
        self.calls.append(("start_google_login", (redirect_uri,)))
        return self.auth_url, self.pkce

    def exchange_insforge_oauth_code(
        self,
        insforge_code: str,
        code_verifier: str,
    ) -> OAuthUser:
        self.calls.append(
            ("exchange_insforge_oauth_code", (insforge_code, code_verifier))
        )
        return self.exchange_user

    def exchange_google_oauth_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthUser:
        self.calls.append(
            (
                "exchange_google_oauth_code",
                (code, code_verifier, redirect_uri),
            )
        )
        return self.exchange_user


class _RecordingAuthPort:
    """Recording fake that implements :class:`AuthUsersPort`.

    Returns canned user rows (or None for the 'not found' case)
    so the callback use case can be exercised end-to-end. Only
    the methods the OAuth callback needs are implemented; the
    other six are deliberate no-ops.
    """

    def __init__(self, user: AuthorizedUser | None = None) -> None:
        self.user = user
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def get_user_by_email(self, email: str) -> AuthorizedUser | None:
        self.calls.append(("get_user_by_email", (email,)))
        return self.user

    # --- unused port methods (no-op stubs) ------------------------------

    def ensure_schema_and_seed(self, initial_admin_email: str) -> None:  # noqa: ARG002
        raise NotImplementedError

    def check_email_taken(self, email: str) -> bool:  # noqa: ARG002
        raise NotImplementedError

    def list_authorized_users(self) -> list[AuthorizedUser]:
        raise NotImplementedError

    def add_authorized_user(  # noqa: PLR0913
        self,
        email: str,
        rol: Rol,
        added_by: str,
    ) -> AuthorizedUser:
        raise NotImplementedError

    def get_user_by_id(self, user_id: str) -> AuthorizedUser | None:  # noqa: ARG002
        raise NotImplementedError

    def deactivate_authorized_user(self, user_id: str) -> AuthorizedUser:  # noqa: ARG002
        raise NotImplementedError


def _user(email: str = "ardelperal@gmail.com", rol: Rol = Rol.DEVELOPER) -> AuthorizedUser:
    return AuthorizedUser(
        id="u-1",
        email=email,
        rol=rol,
        active=True,
        added_by=None,
        added_at=None,
    )


# login_page


def test_login_page_returns_app_name_when_configured() -> None:
    settings = _settings()
    assert login_page_uc(settings) == "APAP_WEB"


def test_login_page_returns_none_when_client_id_missing() -> None:
    settings = _settings(google_client_id="")
    assert login_page_uc(settings) is None


def test_login_page_returns_none_when_client_secret_missing() -> None:
    settings = _settings(google_client_secret="")
    assert login_page_uc(settings) is None


# start_google_login


def test_start_google_login_delegates_to_port() -> None:
    """The use case passes the redirect_uri to the port and returns its (pair, url)."""
    port = _RecordingOAuthPort(
        auth_url="https://accounts.google.com/?code_challenge=abc",
        pkce=PkcePair("v", "c"),
    )
    settings = _settings()
    pkce, auth_url = start_google_login_uc(port, settings)
    assert port.calls == [("start_google_login", (settings.google_redirect_uri,))]
    assert pkce == PkcePair("v", "c")
    assert auth_url == "https://accounts.google.com/?code_challenge=abc"


def test_start_google_login_raises_when_unconfigured() -> None:
    """§32.P4: a missing config is a named-domain error, not a silent 503."""
    port = _RecordingOAuthPort()
    settings = _settings(google_client_id="")
    with pytest.raises(OAuthNotConfiguredError):
        start_google_login_uc(port, settings)
    # The port was never called (the precondition short-circuited).
    assert port.calls == []


# callback


def test_callback_uses_insforge_code_when_supplied() -> None:
    """The InsForge-hosted path is the production entry point."""
    port = _RecordingOAuthPort()
    auth_port = _RecordingAuthPort(user=_user())
    session = callback_uc(
        port,
        auth_port,
        insforge_code="insforge-code-xyz",
        code=None,
        code_verifier="v",
        redirect_uri="https://app/auth/callback",
    )
    assert port.calls == [
        ("exchange_insforge_oauth_code", ("insforge-code-xyz", "v")),
    ]
    assert auth_port.calls == [("get_user_by_email", ("ardelperal@gmail.com",))]
    assert session == AuthenticatedSession(
        email="ardelperal@gmail.com",
        rol=Rol.DEVELOPER,
        user_id="u-1",
        is_authorized=True,
    )


def test_callback_falls_back_to_legacy_code_path() -> None:
    """When only the legacy code is supplied, the Google direct path runs."""
    port = _RecordingOAuthPort()
    auth_port = _RecordingAuthPort(user=_user())
    session = callback_uc(
        port,
        auth_port,
        insforge_code=None,
        code="google-direct-code",
        code_verifier="v",
        redirect_uri="https://app/auth/callback",
    )
    assert port.calls == [
        (
            "exchange_google_oauth_code",
            ("google-direct-code", "v", "https://app/auth/callback"),
        ),
    ]
    assert session.is_authorized is True


def test_callback_prefers_insforge_code_over_legacy_code() -> None:
    """When both query params are present, the InsForge path wins."""
    port = _RecordingOAuthPort()
    auth_port = _RecordingAuthPort(user=_user())
    callback_uc(
        port,
        auth_port,
        insforge_code="insforge",
        code="google",
        code_verifier="v",
        redirect_uri="https://app/auth/callback",
    )
    assert port.calls[0][0] == "exchange_insforge_oauth_code"


def test_callback_raises_callback_invalid_when_no_code_supplied() -> None:
    """§32.P4: missing-code is a named-domain error, not a generic redirect."""
    port = _RecordingOAuthPort()
    auth_port = _RecordingAuthPort()
    with pytest.raises(CallbackInvalidError):
        callback_uc(
            port,
            auth_port,
            insforge_code=None,
            code=None,
            code_verifier="v",
            redirect_uri="https://app/auth/callback",
        )
    # Neither exchange method was called.
    assert port.calls == []


def test_callback_raises_user_not_authorized_when_email_unknown() -> None:
    """The user's email must resolve to a row in usuarios_autorizados."""
    port = _RecordingOAuthPort()
    auth_port = _RecordingAuthPort(user=None)
    with pytest.raises(UserNotAuthorizedError) as excinfo:
        callback_uc(
            port,
            auth_port,
            insforge_code="insforge",
            code=None,
            code_verifier="v",
            redirect_uri="https://app/auth/callback",
        )
    assert excinfo.value.email == "ardelperal@gmail.com"


def test_callback_propagates_insforge_error_from_exchange() -> None:
    """§32.P4: a transport failure surfaces as BackendError (NOT a
    bare-Exception catch). The use case does not swallow it; the
    route layer catches it and translates to a /login redirect.
    """


class _ExplodingOAuthPort:
    def start_google_login(self, redirect_uri: str) -> tuple[str, PkcePair]:  # noqa: ARG002
        raise NotImplementedError

    def exchange_insforge_oauth_code(
        self,
        insforge_code: str,  # noqa: ARG002
        code_verifier: str,  # noqa: ARG002
    ) -> OAuthUser:
        raise BackendError(401, {"error": "INVALID_CREDENTIALS"})

    def exchange_google_oauth_code(
        self,
        code: str,  # noqa: ARG002
        code_verifier: str,  # noqa: ARG002
        redirect_uri: str,  # noqa: ARG002
    ) -> OAuthUser:
        raise NotImplementedError


def test_callback_propagates_insforge_error_from_exchange_real() -> None:
    port: OAuthPort = _ExplodingOAuthPort()
    auth_port = _RecordingAuthPort()
    with pytest.raises(BackendError) as excinfo:
        callback_uc(
            port,
            auth_port,
            insforge_code="bad",
            code=None,
            code_verifier="v",
            redirect_uri="https://app/auth/callback",
        )
    assert excinfo.value.status_code == 401


def test_callback_is_authorized_defaults_to_false_when_user_inactive() -> None:
    """Rule §6: a missing/inactive flag defaults to the most restrictive value."""
    port = _RecordingOAuthPort()
    inactive = AuthorizedUser(
        id="u-2",
        email="ardelperal@gmail.com",
        rol=Rol.KEY_USER,
        active=False,
        added_by=None,
        added_at=None,
    )
    auth_port = _RecordingAuthPort(user=inactive)
    session = callback_uc(
        port,
        auth_port,
        insforge_code="insforge",
        code=None,
        code_verifier="v",
        redirect_uri="https://app/auth/callback",
    )
    assert session.is_authorized is False
    assert session.rol == Rol.KEY_USER


# logout


def test_logout_returns_clear_session_params() -> None:
    """The use case returns the cookie-clearing kwargs the route applies."""
    params = logout_uc()
    assert isinstance(params, ClearSessionParams)
    # The legacy helpers' contract: same key, empty value, max-age=0,
    # path='/', httponly, secure, samesite='strict'.
    assert params.kwargs == {
        "key": "apap_session",
        "value": "",
        "max_age": 0,
        "path": "/",
        "httponly": True,
        "secure": True,
        "samesite": "strict",
    }


# --- adapter (delegation to InsForgeClient) ---------------------------------


class _RecordingInsForge(InsForgeClient):
    """InsForgeClient subclass that records every OAuth call.

    Mirrors the existing _FakeInsForge in tests/test_auth_flow.py
    but is strictly a recorder (no canned data injection — the
    OAuth port methods are tested via the use cases).
    """

    def __init__(self) -> None:
        # Skip the parent __init__ (httpx.Client construction); we
        # override every method that matters for the OAuth slice.
        self.start_google_oauth_calls: list[tuple[str, str]] = []
        self.exchange_insforge_calls: list[tuple[str, str]] = []
        self.exchange_google_calls: list[tuple[str, str, str]] = []
        self._next_pkce_response = "https://accounts.google.com/o/oauth2/v2/auth"
        self._next_exchange_response = OAuthExchangeResult(
            token="jwt-from-insforge",
            user=InsForgeUser(id="u-1", email="ardelperal@gmail.com"),
        )

    def start_google_oauth(  # type: ignore[override]
        self,
        redirect_uri: str,
        code_challenge: str,
    ) -> str:
        self.start_google_oauth_calls.append((redirect_uri, code_challenge))
        return self._next_pkce_response

    def exchange_insforge_oauth_code(  # type: ignore[override]
        self,
        insforge_code: str,
        code_verifier: str,
    ) -> OAuthExchangeResult:
        self.exchange_insforge_calls.append((insforge_code, code_verifier))
        return self._next_exchange_response

    def exchange_google_oauth_code(  # type: ignore[override]
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthExchangeResult:
        self.exchange_google_calls.append((code, code_verifier, redirect_uri))
        return self._next_exchange_response


def test_adapter_start_google_login_mints_pkce_and_delegates() -> None:
    """The adapter generates the PKCE pair and passes the challenge to the client."""
    client = _RecordingInsForge()
    client._next_pkce_response = "https://google/?c=abc"
    auth_url, pkce = InsForgeOAuthAdapter(client).start_google_login(
        "https://app/callback"
    )
    assert auth_url == "https://google/?c=abc"
    # The challenge matches the verifier (RFC 7636) — the adapter
    # generated them as a pair via app.core.pkce.generate_pkce_pair.
    import hashlib

    expected_challenge = (
        hashlib.sha256(pkce.code_verifier.encode("ascii")).digest()
    )
    import base64

    expected_b64 = base64.urlsafe_b64encode(expected_challenge).decode("ascii").rstrip("=")
    assert pkce.code_challenge == expected_b64
    # The client received the same challenge.
    assert client.start_google_oauth_calls == [("https://app/callback", pkce.code_challenge)]


def test_adapter_exchange_insforge_oauth_code_projects_to_oauth_user() -> None:
    client = _RecordingInsForge()
    user = InsForgeOAuthAdapter(client).exchange_insforge_oauth_code(
        insforge_code="ins-1",
        code_verifier="v-1",
    )
    assert user == OAuthUser(id="u-1", email="ardelperal@gmail.com")
    assert client.exchange_insforge_calls == [("ins-1", "v-1")]


def test_adapter_exchange_google_oauth_code_projects_to_oauth_user() -> None:
    client = _RecordingInsForge()
    user = InsForgeOAuthAdapter(client).exchange_google_oauth_code(
        code="g-1",
        code_verifier="v-1",
        redirect_uri="https://app/callback",
    )
    assert user == OAuthUser(id="u-1", email="ardelperal@gmail.com")
    assert client.exchange_google_calls == [("g-1", "v-1", "https://app/callback")]


def test_adapter_propagates_insforge_error_untouched() -> None:
    """The adapter does NOT catch transport errors (the use case does)."""
    client = _RecordingInsForge()

    def boom(*_args, **_kwargs):
        raise BackendError(401, {"error": "INVALID_CREDENTIALS"})

    client.exchange_insforge_oauth_code = boom  # type: ignore[method-assign]
    with pytest.raises(BackendError) as excinfo:
        InsForgeOAuthAdapter(client).exchange_insforge_oauth_code("x", "v")
    assert excinfo.value.status_code == 401


def test_adapter_satisfies_oauth_port_protocol() -> None:
    """The adapter type-checks against :class:`OAuthPort`.

    mypy enforces this via the explicit base class; this test
    documents the contract at runtime: an instance of the adapter
    is a usable :class:`OAuthPort`.
    """
    client = _RecordingInsForge()
    adapter: OAuthPort = InsForgeOAuthAdapter(client)
    assert isinstance(adapter, InsForgeOAuthAdapter)
    for method in (
        "start_google_login",
        "exchange_insforge_oauth_code",
        "exchange_google_oauth_code",
    ):
        assert hasattr(adapter, method)
        assert callable(getattr(adapter, method))


# --- DI helper --------------------------------------------------------------


def test_get_oauth_port_uses_pooled_client_when_present() -> None:
    """The DI helper builds the adapter from the pooled ``app.state.insforge_client``."""
    from fastapi import FastAPI

    from app.core.di.oauth_di import get_oauth_port

    app = FastAPI()
    client = _RecordingInsForge()
    app.state.insforge_client = client

    gen = get_oauth_port(type("R", (), {"app": app})())
    adapter = next(gen)
    try:
        assert isinstance(adapter, InsForgeOAuthAdapter)
        assert adapter._client is client  # noqa: SLF001 — internal seam
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_get_oauth_port_falls_back_when_lifespan_skipped() -> None:
    """If ``app.state.insforge_client`` is missing, the helper creates a new client.

    This branch exists for lightweight ASGI test transports that
    bypass the lifespan. The exact fallback client is an
    :class:`InsForgeClient`; we only assert it is created and the
    adapter wraps it.
    """
    from fastapi import FastAPI

    from app.core.di.oauth_di import get_oauth_port

    app = FastAPI()
    assert not hasattr(app.state, "insforge_client")

    req = type("R", (), {"app": app})()
    gen = get_oauth_port(req)
    try:
        adapter = next(gen)
        assert isinstance(adapter, InsForgeOAuthAdapter)
        assert isinstance(adapter._client, InsForgeClient)  # noqa: SLF001
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# --- domain entities (no I/O) -----------------------------------------------


def test_pkce_pair_is_immutable_value_object() -> None:
    pkce = PkcePair("v", "c")
    with pytest.raises((AttributeError, Exception)):
        pkce.code_verifier = "mutated"  # type: ignore[misc]


def test_authenticated_session_is_immutable_value_object() -> None:
    session = AuthenticatedSession(
        email="a@b.com",
        rol=Rol.KEY_USER,
        user_id="u-1",
        is_authorized=True,
    )
    with pytest.raises((AttributeError, Exception)):
        session.email = "mutated"  # type: ignore[misc]


def test_authenticated_session_from_authorized_user_maps_fields() -> None:
    user = AuthorizedUser(
        id="u-99",
        email="a@b.com",
        rol=Rol.DEVELOPER,
        active=True,
        added_by="u-1",
        added_at=None,
    )
    session = AuthenticatedSession.from_authorized_user(user)
    assert session == AuthenticatedSession(
        email="a@b.com",
        rol=Rol.DEVELOPER,
        user_id="u-99",
        is_authorized=True,
    )


def test_oauth_not_configured_error_message_includes_env_var_names() -> None:
    err = OAuthNotConfiguredError()
    assert "APAP_GOOGLE_CLIENT_ID" in str(err)
    assert "APAP_GOOGLE_CLIENT_SECRET" in str(err)


def test_user_not_authorized_error_carries_email_attribute() -> None:
    err = UserNotAuthorizedError("a@b.com")
    assert err.email == "a@b.com"
    assert "a@b.com" in str(err)


# --- architectural rule pins ------------------------------------------------


def test_application_layer_does_not_import_insforge() -> None:
    """Rule §31: application layer depends on the Protocol, not on a concrete client."""
    import importlib

    pkg = importlib.import_module("app.core.application.oauth")
    for module_name in pkg.__all__:
        if module_name == "ClearSessionParams":
            # value object re-exported from logout; it is a dataclass,
            # not a use case — skip the per-module scan
            continue
        module = importlib.import_module(f"app.core.application.oauth.{module_name}")
        for attr in module.__dict__.values():
            attr_module = getattr(attr, "__module__", "") or ""
            assert "insforge" not in attr_module.lower() or attr_module.startswith(
                "tests"
            ), (
                f"application module {module_name!r} leaked InsForge import "
                f"from {attr_module!r}"
            )


def test_ports_package_does_not_import_insforge() -> None:
    """Rule §31: the port is the seam; the concrete client lives only in the adapter."""
    from app.core.ports import oauth_port

    for attr_name in oauth_port.__all__:
        attr = getattr(oauth_port, attr_name)
        attr_module = getattr(attr, "__module__", "") or ""
        assert "insforge" not in attr_module.lower(), (
            f"port module leaked InsForge import via {attr_name!r} from {attr_module!r}"
        )


def test_di_oauth_module_exports_only_di_factory() -> None:
    """The slice-scoped DI module re-exports ONLY the FastAPI dependency."""
    from app.core.di import oauth_di

    assert oauth_di.__all__ == ["get_oauth_port"]


def test_di_layer_does_not_export_domain_or_port() -> None:
    """DI exposes ONLY FastAPI dependencies — domain entities and ports are hidden.

    Mirrors the catalogos_slice invariant now extended to all four
    slices (auth_users, catalogos, oauth, schema_bootstrap). The
    test pins the structural property: every name exported from
    app.core.di is a callable whose defining module is NOT
    app.core.domain or app.core.ports.
    """
    import importlib

    di_pkg = importlib.import_module("app.core.di")
    for export_name in di_pkg.__all__:
        attr = getattr(di_pkg, export_name)
        attr_module = getattr(attr, "__module__", "") or ""
        assert "core.domain" not in attr_module, (
            f"app.core.di leaked a domain import via {export_name!r} from {attr_module!r}"
        )
        assert "core.ports" not in attr_module, (
            f"app.core.di leaked a port import via {export_name!r} from {attr_module!r}"
        )
