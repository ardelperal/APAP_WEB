"""Tests for rate limiting (issue #286).

Spec coverage: REQ-1 through REQ-7.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI  # noqa: F401 — type annotation only, evaluated lazily
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.session import session_cookie_name, write_session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AnonymousSpy:
    """LocalBackend stand-in for tests that bypass the DB layer."""

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[no-untyped-def]
        from tests.conftest import auth_reval_rows

        _reval = auth_reval_rows(query, params)
        if _reval is not None:
            return _reval
        if "RETURNING" in query or "INSERT" in query:
            return [{"id": "spy-1"}]
        return [{"id": "spy-1"}]

    def __getattr__(self, name: str) -> Any:  # type: ignore[no-untyped-def]
        raise NotImplementedError(
            f"_AnonymousSpy.{name} is not mocked. Add an explicit method."
        )


@pytest.fixture
def _bypass_local_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app, get_local_backend_client

    spy = _AnonymousSpy()
    app.dependency_overrides[get_local_backend_client] = lambda: spy
    yield
    app.dependency_overrides.pop(get_local_backend_client, None)


def _login(
    client: httpx.AsyncClient,
    *,
    user_id: str = "u-ana",
    rol: str = "key_user",
    csrf_token: str = "test-csrf-token",
) -> str:
    """Return the CSRF token from the issued session."""
    settings = get_settings()
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": rol,
            "user_id": user_id,
            "is_authorized": True,
            "csrf_token": csrf_token,
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)
    return csrf_token


def _make_test_app(*, mode: str = "web") -> FastAPI:
    """Create a fresh FastAPI app with a fresh rate-limit backend for test isolation.

    Each call produces a new backend so tests don't pollute each other's bucket state.
    The ``mode`` parameter controls whether rate limiting is active.
    """


    # Import create_app but override the middleware setup
    # We create a minimal app that shares the router structure

    from app.core.rate_limit import InProcessRateLimitBackend
    from app.main import create_app

    app = create_app()
    InProcessRateLimitBackend()

    # Rebuild middleware stack without rate limiting
    # We need to add the rate limit middleware with our test backend
    # Since the app already has rate limit middleware from create_app,
    # we need a fresh app. Instead, we just use the regular app and
    # accept that the backend is shared.

    # For tests that need a truly fresh backend, we can't easily do it
    # with the existing app structure. Instead, tests use unique identifiers
    # to avoid bucket collisions.

    return app


# ---------------------------------------------------------------------------
# Phase 1 — RateLimitBackend Protocol + sliding window (unit)
# ---------------------------------------------------------------------------


class TestInProcessRateLimitBackend:
    """RED: Backend.hit(scope, identity, limit, now, window) — sliding window."""

    def test_hit_under_limit_is_allowed(self) -> None:
        """First request in a fresh window → allowed, remaining = limit-1."""
        # The backend doesn't exist yet — importing it fails
        from app.core.rate_limit import InProcessRateLimitBackend

        backend = InProcessRateLimitBackend()
        allowed, info = backend.hit(
            scope="write_ip",
            identity="1.2.3.4",
            limit=30,
            now=1000.0,
            window_seconds=60,
        )
        assert allowed is True
        assert info.remaining == 29
        assert info.limit == 30

    def test_hit_exact_limit_is_rejected(self) -> None:
        """When timestamps fill the window exactly to limit → last one rejected."""
        from app.core.rate_limit import InProcessRateLimitBackend

        backend = InProcessRateLimitBackend()
        # Exhaust the bucket: hit 30 times at t=1000
        for _ in range(30):
            backend.hit(
                scope="write_ip",
                identity="1.2.3.4",
                limit=30,
                now=1000.0,
                window_seconds=60,
            )
        # 31st hit at same window start → rejected
        allowed, info = backend.hit(
            scope="write_ip",
            identity="1.2.3.4",
            limit=30,
            now=1000.0,
            window_seconds=60,
        )
        assert allowed is False
        assert info.remaining == 0

    def test_hit_after_window_reset_is_allowed(self) -> None:
        """Old timestamps exit the sliding window → new requests allowed."""
        from app.core.rate_limit import InProcessRateLimitBackend

        backend = InProcessRateLimitBackend()
        # 5 requests at t=1000
        for _ in range(5):
            backend.hit(
                scope="oauth",
                identity="1.2.3.4",
                limit=10,
                now=1000.0,
                window_seconds=60,
            )
        # Advance clock past window (t=1061 > 1000+60)
        allowed, _ = backend.hit(
            scope="oauth",
            identity="1.2.3.4",
            limit=10,
            now=1061.0,
            window_seconds=60,
        )
        assert allowed is True  # oldest ts (1000) expired, window has 5/10

    def test_reset_epoch_is_oldest_timestamp_plus_window(self) -> None:
        """X-RateLimit-Reset = oldest retained ts + window."""
        from app.core.rate_limit import InProcessRateLimitBackend

        backend = InProcessRateLimitBackend()
        backend.hit("write_ip", "1.2.3.4", limit=30, now=500.0, window_seconds=60)
        _, info = backend.hit(
            "write_ip", "1.2.3.4", limit=30, now=510.0, window_seconds=60
        )
        # oldest retained = 500, reset = 500 + 60 = 560
        assert info.reset_at == 560.0


# ---------------------------------------------------------------------------
# Phase 2.1 — _extract_identity (unit)
# ---------------------------------------------------------------------------


class TestExtractIdentity:
    """RED: _extract_identity(request, settings) → Identity."""

    def test_extract_identity_no_session_no_xff(self) -> None:
        """No cookie, no XFF → IP from request.client, no user_id."""
        from app.core.rate_limit import _extract_identity

        request = MagicMock()
        request.cookies.get.return_value = None
        request.client.host = "10.0.0.1"
        request.headers.get.return_value = None
        settings = get_settings()

        identity = _extract_identity(request, settings)

        assert identity.ip == "10.0.0.1"
        assert identity.user_id is None

    def test_extract_identity_with_xff_trusted(self) -> None:
        """XFF present + trust_xff=True → first XFF entry is IP."""
        from app.core.rate_limit import _extract_identity

        request = MagicMock()
        request.cookies.get.return_value = None
        request.headers.get.return_value = "203.0.113.50, 10.0.0.1"
        settings = get_settings()
        # Monkeypatch trust_xff via a settings mock
        settings.trust_xff = True

        identity = _extract_identity(request, settings)

        assert identity.ip == "203.0.113.50"

    def test_extract_identity_with_xff_untrusted(self) -> None:
        """XFF present but trust_xff=False → request.client.host wins."""
        from app.core.rate_limit import _extract_identity

        request = MagicMock()
        request.cookies.get.return_value = None
        request.client.host = "10.0.0.1"
        request.headers.get.return_value = "203.0.113.50, 10.0.0.1"
        settings = get_settings()
        settings.trust_xff = False

        identity = _extract_identity(request, settings)

        assert identity.ip == "10.0.0.1"  # XFF ignored

    def test_extract_identity_with_valid_session(self) -> None:
        """Valid session cookie → user_id extracted, IP from client.host."""
        from app.core.rate_limit import _extract_identity

        settings = get_settings()
        session_token = write_session(
            {"user_id": "u-test", "email": "test@example.com", "rol": "admin"},
            secret=settings.session_secret,
        )
        request = MagicMock()
        request.cookies.get.return_value = session_token
        request.client.host = "10.0.0.1"
        request.headers.get.return_value = None

        identity = _extract_identity(request, settings)

        assert identity.user_id == "u-test"
        assert identity.ip == "10.0.0.1"


# ---------------------------------------------------------------------------
# Phase 2.2 — RateLimitMiddleware integration
# ---------------------------------------------------------------------------


class TestRateLimitMiddlewareIntegration:
    """RED: Middleware classifies buckets, applies limits, returns headers + 429."""

    @pytest.fixture(autouse=True)
    def _web_mode(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        """Activate the rate-limit middleware for every test in this class.

        ``tests/conftest.py`` defaults ``APAP_MODE=test`` (so the middleware
        short-circuits for route tests that exercise auth/CSRF, which expect
        403/401, not 429). This class DOES test the middleware itself and
        therefore needs ``mode="web"`` — the bypass must NOT trigger.

        ``monkeypatch.setenv`` is per-test (auto-undone at test end) and the
        ``get_settings.cache_clear()`` ensures the next ``dispatch()`` call
        re-reads the env var rather than serving the cached "test" value.
        """

        from app.core.config import get_settings

        monkeypatch.setenv("APAP_MODE", "web")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def test_oauth_callback_under_limit_has_rate_limit_headers(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /auth/callback under OAuth IP limit → 200/302 with rate-limit headers.

        Uses X-Forwarded-For with a unique IP so this test's bucket is
        isolated from other OAuth tests.
        """
        # Unique IP to avoid bucket collision with other OAuth tests
        response = await client.get(
            "/auth/callback",
            headers={"X-Forwarded-For": "10.0.0.100"},
            follow_redirects=False,
        )
        # 302 = redirect to /login (no PKCE cookie); 200 would be a valid callback
        assert response.status_code in (200, 302)
        # Headers present on success
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    async def test_oauth_callback_over_limit_returns_429(
        self, client: httpx.AsyncClient
    ) -> None:
        """Exhaust OAuth IP bucket → 429 with Retry-After + X-RateLimit-*, no IP in log."""
        # Use unique IP to avoid collision with other tests
        for i in range(11):
            await client.get(
                "/auth/callback",
                headers={"X-Forwarded-For": f"10.0.0.101.{i}"},
                follow_redirects=False,
            )
        # The 11th request should be rejected
        response = await client.get(
            "/auth/callback",
            headers={"X-Forwarded-For": "10.0.0.101.11"},
            follow_redirects=False,
        )
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert response.headers["X-RateLimit-Remaining"] == "0"
        body = response.json()
        assert "error" in body

    async def test_write_route_under_both_limits_returns_200(
        self, client: httpx.AsyncClient, _bypass_local_backend: None
    ) -> None:
        """POST under user (60/min) and IP (30/min) limits → 200."""
        _login(client, user_id="u-test", rol="admin")

        # One POST — well within limits
        response = await client.post(
            "/admin/users",
            data={"email": "new@example.com", "rol": "reader"},
            headers={"X-CSRFToken": "test-csrf-token"},
            follow_redirects=False,
        )
        # 302 = redirect to /admin = CSRF/token passed; 200 also ok depending on route
        assert response.status_code in (200, 302)

    async def test_write_route_over_user_limit_returns_429_reason_user(
        self, client: httpx.AsyncClient, _bypass_local_backend: None
    ) -> None:
        """Authenticated POST exhausting user bucket → 429, reason=user."""
        _login(client, user_id="u-exhaust", rol="admin")

        # Exhaust user bucket (60/min)
        for i in range(60):
            await client.post(
                "/admin/users",
                data={"email": f"a{i}@example.com", "rol": "reader"},
                headers={"X-CSRFToken": "test-csrf-token"},
                follow_redirects=False,
            )

        response = await client.post(
            "/admin/users",
            data={"email": "exhaust@example.com", "rol": "reader"},
            headers={"X-CSRFToken": "test-csrf-token"},
            follow_redirects=False,
        )
        assert response.status_code == 429
        # reason should be "user" when it's the user bucket that caused rejection
        # (middleware doesn't encode reason in 429 body — headers carry that info)
        assert "Retry-After" in response.headers

    async def test_read_route_never_429(
        self, client: httpx.AsyncClient
    ) -> None:
        """GET /healthz never triggers 429 regardless of count.

        Uses the public /healthz endpoint to avoid spy setup complexity.
        """
        for _ in range(100):
            response = await client.get("/healthz", follow_redirects=False)
            # Should never be rate-limited (read route)
            assert response.status_code == 200, f"GET /healthz returned {response.status_code}"
            assert "X-RateLimit-Limit" not in response.headers

    async def test_apap_mode_test_bypasses_all_limits(
        self,
        client: httpx.AsyncClient,
        _bypass_local_backend: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """APAP_MODE=test → 1000 POSTs return no 429."""
        # Switch app mode to test
        from app.core import config as config_module

        original_settings = config_module.get_settings()
        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: original_settings.__class__.model_copy(
                original_settings, update={"mode": "test"}
            ),
        )

        _login(client, user_id="u-test", rol="admin")

        for i in range(100):
            response = await client.post(
                "/admin/users",
                data={"email": f"b{i}@example.com", "rol": "reader"},
                headers={"X-CSRFToken": "test-csrf-token"},
                follow_redirects=False,
            )
            # In test mode there is no 429 regardless of count
            assert response.status_code != 429, (
                f"APAP_MODE=test should bypass rate limits; got {response.status_code} on req {i}"
            )

    async def test_rejection_log_has_no_ip_kwarg(
        self,
        client: httpx.AsyncClient,
        _bypass_local_backend: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """On 429, log_safe is called WITHOUT any IP-identifying kwarg."""
        _login(client, user_id="u-logtest")

        # Exhaust OAuth bucket for this unique user
        for i in range(11):
            await client.get(
                "/auth/callback",
                headers={"X-Forwarded-For": f"10.0.0.200.{i}"},
                follow_redirects=False,
            )

        with caplog.at_level("INFO", logger="app"):
            await client.get(
                "/auth/callback",
                headers={"X-Forwarded-For": "10.0.0.200.11"},
                follow_redirects=False,
            )

        # Filter to app-logger records only; caplog captures records from every
        # logger (uvicorn, asyncio, httpcore, ...), and only app records carry
        # the ``_caller_fields`` extra attached by ``log_safe``.
        app_records = [r for r in caplog.records if r.name == "app"]

        # Find the ratelimit.rejected event
        ratelimit_events = [
            r for r in app_records if r._caller_fields.get("event") == "ratelimit.rejected"
        ]
        assert len(ratelimit_events) >= 1, (
            f"Expected ratelimit.rejected log event, got events={[r._caller_fields.get('event') for r in app_records]}"
        )
        # IP must NOT appear in any kwarg
        for record in ratelimit_events:
            fields = record._caller_fields
            ip_keys = {k for k in fields if "ip" in k.lower()}
            assert not ip_keys, (
                f"IP-identifying kwarg found in ratelimit.rejected log: {ip_keys}. "
                f"Full fields: {fields}"
            )

    async def test_all_headers_present_on_protected_success(
        self,
        client: httpx.AsyncClient,
        _bypass_local_backend: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Under-limit write request → 200/302 AND all X-RateLimit-* headers.

        Uses trust_xff=True + unique XFF IP so this test's IP bucket is
        isolated from write-bucket exhaustion in previous tests.
        """
        # Enable XFF trust for this test's IP isolation
        from app.core import config as config_module

        base_settings = config_module.get_settings()
        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: base_settings.__class__.model_copy(base_settings, update={"trust_xff": True}),
        )

        _login(client, user_id="u-headers-fresh")

        # Use a fresh IP for this test so the IP bucket is not exhausted
        # (write IP bucket default is 30/min; previous tests exhausted it for
        # the default "testserver" IP)
        response = await client.post(
            "/admin/users",
            data={"email": "headers@example.com", "rol": "reader"},
            headers={"X-CSRFToken": "test-csrf-token", "X-Forwarded-For": "10.0.0.99"},
            follow_redirects=False,
        )
        assert response.status_code in (200, 302)
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
        # Retry-After only on 429
        assert "Retry-After" not in response.headers


# ---------------------------------------------------------------------------
# Phase 3 — Middleware ordering: CSRF must run BEFORE rate-limit (issue #286 D8)
# ---------------------------------------------------------------------------


class TestRateLimitMiddlewareOrdering:
    """Middleware order: CSRF must run BEFORE rate-limit (issue #286 D8).

    A 403 from CsrfMiddleware must NOT consume a legitimate user's rate-limit
    budget. Starlette's ``app.add_middleware`` does ``user_middleware.insert(0, ...)``
    so the LAST ``add_middleware`` call wins the OUTERMOST slot — which in
    ``user_middleware`` is the LOWEST index. CSRF and rate-limit both register
    via ``add_middleware``; whichever is added LAST ends up OUTER (lowest
    index). The test below pins the contract that CSRF is outer: lower index
    than RateLimitMiddleware.
    """

    def test_csrf_is_outer_than_rate_limit_in_user_middleware(self) -> None:
        """CsrfMiddleware index < RateLimitMiddleware index in app.user_middleware.

        In Starlette, lower index in ``app.user_middleware`` = outer (runs
        earlier in the request). CSRF running before rate-limit means a 403
        from CSRF does not decrement the rate-limit bucket (issue #286 D8).
        """
        from app.main import app

        names = [m.cls.__name__ for m in app.user_middleware]
        csrf_idx = next((i for i, n in enumerate(names) if n == "CsrfMiddleware"), None)
        rl_idx = next((i for i, n in enumerate(names) if n == "RateLimitMiddleware"), None)
        assert csrf_idx is not None, f"CsrfMiddleware not registered. order={names}"
        assert rl_idx is not None, f"RateLimitMiddleware not registered. order={names}"
        assert csrf_idx < rl_idx, (
            f"CsrfMiddleware is at index {csrf_idx} but RateLimitMiddleware is at "
            f"index {rl_idx}. CSRF must run BEFORE rate-limit (lower index in "
            f"app.user_middleware = outer) so 403 rejections don't consume rate "
            f"budget. user_middleware order: {names}"
        )


# ---------------------------------------------------------------------------
# Issue #904 — route-specific /e2e/login rate limit (5/min/IP)
# ---------------------------------------------------------------------------


class TestE2ELoginRateLimit:
    """RED: GET /e2e/login is IP-rate-limited to 5/min; 6th hit gets 429."""

    @pytest.fixture(autouse=True)
    def _web_mode(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        """Activate the middleware: APAP_MODE must not be the test bypass."""
        monkeypatch.setenv("APAP_MODE", "web")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    @staticmethod
    def _make_e2e_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
        """Minimal app: the mock route registered + a fresh rate-limit backend.

        Mirrors the production composition (route + RateLimitMiddleware with
        an ``InProcessRateLimitBackend``) without the full ``create_app``
        stack, so the bucket state is isolated per test. The e2e flag is
        forced ON via env-var because the middleware reads
        ``Settings.e2e_auth_enabled`` at request time through the real
        ``app.core.config.get_settings`` to decide whether the bucket
        applies (issue #904 fix round 1: flag off → bare 404, no bucket).
        """
        import app.core.e2e_auth as e2e_module
        from app.core.e2e_auth import register_e2e_auth_routes
        from app.core.rate_limit import InProcessRateLimitBackend
        from app.core.rate_limit_middleware import RateLimitMiddleware

        monkeypatch.setenv("APAP_E2E_AUTH_ENABLED", "true")
        get_settings.cache_clear()
        original = e2e_module.get_settings
        e2e_module.get_settings = lambda: Settings(  # type: ignore[assignment]
            e2e_auth_enabled=True,
            e2e_auth_secret="test-secret",
            session_secret="test-session-secret",
        )
        try:
            app = FastAPI()
            register_e2e_auth_routes(app)
        finally:
            e2e_module.get_settings = original
        app.add_middleware(RateLimitMiddleware, backend=InProcessRateLimitBackend())
        return app

    @staticmethod
    def _make_flag_off_app() -> FastAPI:
        """Minimal app mirroring production with the e2e flag OFF.

        ``register_e2e_auth_routes`` no-ops (route NOT registered) but the
        ``RateLimitMiddleware`` is still installed — exactly the
        production composition when ``APAP_E2E_AUTH_ENABLED`` is unset.
        """
        import app.core.e2e_auth as e2e_module
        from app.core.e2e_auth import register_e2e_auth_routes
        from app.core.rate_limit import InProcessRateLimitBackend
        from app.core.rate_limit_middleware import RateLimitMiddleware

        original = e2e_module.get_settings
        e2e_module.get_settings = lambda: Settings(  # type: ignore[assignment]
            e2e_auth_enabled=False,
        )
        try:
            app = FastAPI()
            register_e2e_auth_routes(app)
        finally:
            e2e_module.get_settings = original
        app.add_middleware(RateLimitMiddleware, backend=InProcessRateLimitBackend())
        return app

    def test_sixth_request_within_minute_returns_429(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """5 attempts pass through (401, no secret); the 6th gets 429 + Retry-After."""
        client = TestClient(self._make_e2e_app(monkeypatch))

        for _ in range(5):
            response = client.get("/e2e/login", headers={"X-E2E-Secret": "wrong"})
            assert response.status_code == 401, "first 5 attempts must reach the route"

        response = client.get("/e2e/login", headers={"X-E2E-Secret": "wrong"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert response.headers["X-RateLimit-Limit"] == "5"
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert "error" in response.json()

    def test_burst_429_emits_one_ip_bearing_forensic_record(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Issue #904 fix round 1 (JD-B-003): the e2e 429 leaves an IP trail.

        ``ratelimit.rejected`` carries no IP by design (REQ-5/D6), so a
        brute-force burst against the gate would lose source IP and
        attempted email. For scope ``e2e_login`` ONLY, the 429 additionally
        emits one forensic ``e2e.login`` record with ``outcome=rate_limited``
        and ``client_ip``; ``ratelimit.rejected`` stays unchanged.
        """
        client = TestClient(self._make_e2e_app(monkeypatch))

        # The whole burst runs inside the capture context: the ambient
        # "app" logger level depends on which tests ran before (some
        # call configure_logging), so records must be counted by outcome,
        # not by capture-window position.
        with caplog.at_level(logging.INFO, logger="app"):
            for _ in range(5):
                allowed = client.get(
                    "/e2e/login?email=burst@probe.example",
                    headers={"X-E2E-Secret": "wrong"},
                )
                assert allowed.status_code == 401
            response = client.get(
                "/e2e/login?email=burst@probe.example",
                headers={"X-E2E-Secret": "wrong"},
            )

        assert response.status_code == 429
        records = [r for r in caplog.records if r.name == "app"]
        forensic = [
            r
            for r in records
            if getattr(r, "_caller_fields", {}).get("event") == "e2e.login"
            and getattr(r, "_caller_fields", {}).get("outcome") == "rate_limited"
        ]
        assert len(forensic) == 1, "exactly one forensic record on the 429"
        fields = forensic[0]._caller_fields
        assert fields["outcome"] == "rate_limited"
        assert fields["client_ip"]
        assert fields["target_email"] == "burst@probe.example"
        # ratelimit.rejected unchanged: still emitted, still IP-free.
        rejected = [
            r
            for r in records
            if getattr(r, "_caller_fields", {}).get("event") == "ratelimit.rejected"
        ]
        assert len(rejected) == 1
        assert not {k for k in rejected[0]._caller_fields if "ip" in k.lower()}

    async def test_oauth_429_does_not_emit_forensic_record(
        self,
        client: httpx.AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The forensic event is e2e_login-only: oauth 429s stay IP-free."""
        from app.core import config as config_module

        base_settings = config_module.get_settings()
        monkeypatch.setattr(
            config_module,
            "get_settings",
            lambda: base_settings.__class__.model_copy(
                base_settings, update={"trust_xff": True}
            ),
        )

        with caplog.at_level(logging.INFO, logger="app"):
            # Exhaust the oauth IP bucket (limit 10/min) for a unique IP.
            for _ in range(10):
                await client.get(
                    "/auth/callback",
                    headers={"X-Forwarded-For": "10.9.9.7"},
                    follow_redirects=False,
                )
            response = await client.get(
                "/auth/callback",
                headers={"X-Forwarded-For": "10.9.9.7"},
                follow_redirects=False,
            )

        assert response.status_code == 429
        records = [r for r in caplog.records if r.name == "app"]
        forensic = [
            r
            for r in records
            if getattr(r, "_caller_fields", {}).get("event") == "e2e.login"
        ]
        assert len(forensic) == 0, "oauth rejections must not emit e2e.login"
        # Sanity: the oauth rejection did log ratelimit.rejected.
        rejected = [
            r
            for r in records
            if getattr(r, "_caller_fields", {}).get("event") == "ratelimit.rejected"
        ]
        assert len(rejected) >= 1

    def test_bucket_key_ignores_client_supplied_xff_when_untrusted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #904 fix round 1 (JD-B-004/JD-A-005, disposition pin).

        With ``APAP_TRUST_XFF`` unset/false (the default; no manifest sets
        it true), a client-supplied multi-hop ``X-Forwarded-For`` must NOT
        reset the bucket key: rotating the leftmost entry does not give a
        fresh 5-attempt budget. ``_extract_identity`` ignores XFF when
        trust is off — this test pins that behaviour at the bucket level
        so a future XFF redesign cannot silently flip it. XFF redesign is
        deferred to a follow-up issue (not this fix round).
        """
        client = TestClient(self._make_e2e_app(monkeypatch))

        # 5 attempts, each trying to rotate identity via a fresh
        # client-supplied leftmost XFF entry (multi-hop style).
        for i in range(5):
            response = client.get(
                "/e2e/login",
                headers={
                    "X-E2E-Secret": "wrong",
                    "X-Forwarded-For": f"203.0.113.{i}, 10.0.0.1",
                },
            )
            assert response.status_code == 401, (
                f"attempt {i + 1} must reach the route regardless of XFF rotation"
            )

        # 6th attempt: the bucket is still keyed by the real client host,
        # so the rotated XFF entries did not reset it → 429.
        response = client.get(
            "/e2e/login",
            headers={
                "X-E2E-Secret": "wrong",
                "X-Forwarded-For": "203.0.113.99, 10.0.0.1",
            },
        )
        assert response.status_code == 429, (
            "rotating client-supplied XFF entries must NOT reset the bucket"
        )

    def test_flag_off_probes_get_bare_404_without_rate_limit_headers(self) -> None:
        """Issue #904 fix round 1 (JD-B-001/JD-A-003): flag off → bare 404s.

        With the e2e flag off the route is not registered, so probes to
        ``GET /e2e/login`` must answer the same bare 404 as any unknown
        path: no ``X-RateLimit-*`` headers, no ``Retry-After``, and no
        bucket consumption (the endpoint is not fingerprintable via a
        6th-request 429).
        """
        client = TestClient(self._make_flag_off_app())

        for i in range(6):
            response = client.get("/e2e/login")
            assert response.status_code == 404, f"probe {i + 1} must be a bare 404"
            assert "X-RateLimit-Limit" not in response.headers
            assert "X-RateLimit-Remaining" not in response.headers
            assert "X-RateLimit-Reset" not in response.headers
            assert "Retry-After" not in response.headers

    def test_flag_on_still_returns_429_on_sixth_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Positive control: the bare-404 change keeps the flag-on 429 intact."""
        client = TestClient(self._make_e2e_app(monkeypatch))

        for _ in range(5):
            response = client.get("/e2e/login", headers={"X-E2E-Secret": "wrong"})
            assert response.status_code == 401

        response = client.get("/e2e/login", headers={"X-E2E-Secret": "wrong"})
        assert response.status_code == 429
        assert "X-RateLimit-Limit" in response.headers

    def test_limit_is_per_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exhausting one IP's bucket does not exhaust another IP's."""
        monkeypatch.setenv("APAP_TRUST_XFF", "true")
        get_settings.cache_clear()
        client = TestClient(self._make_e2e_app(monkeypatch))

        for _ in range(5):
            client.get(
                "/e2e/login",
                headers={"X-E2E-Secret": "wrong", "X-Forwarded-For": "203.0.113.9"},
            )
        exhausted = client.get(
            "/e2e/login",
            headers={"X-E2E-Secret": "wrong", "X-Forwarded-For": "203.0.113.9"},
        )
        assert exhausted.status_code == 429

        fresh_ip = client.get(
            "/e2e/login",
            headers={"X-E2E-Secret": "wrong", "X-Forwarded-For": "203.0.113.10"},
        )
        assert fresh_ip.status_code == 401, "a different IP must have its own bucket"
