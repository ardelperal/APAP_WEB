"""Slice B — UA-based template selection (engram obs #15705).

Slice A (``UADetectionMiddleware``) introduced
``request.state.is_mobile``. This slice adds the Jinja context
processor that turns that flag into a ``base_template`` variable
that templates ``extend``: ``base_mobile.html`` when mobile,
``base.html`` otherwise.

Test layers:

1. **Direct unit tests** of the helper and processor with a minimal
   fake ``Request``. Verifies the selector is a pure function of
   ``request.state.is_mobile`` (slice A's contract).

2. **HTTP-level sentinels** on ``GET /login`` with desktop vs
   mobile User-Agent. The mobile template carries the
   ``viewport-fit=cover`` meta marker and omits the desktop
   burger landmark; the desktop template does the inverse. This
   is the integration contract: a real request flows through the
   middleware → context processor → Jinja → response body.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.requests import Request

# Imports below are exercised by the test bodies. They reference
# symbols that DO NOT EXIST yet at the time these tests are
# authored — that is the TDD red step.
from app.core.middleware import (  # noqa: F401
    _select_base_template,
    base_template_context_processor,
)
from app.main import app

# --- Helpers --------------------------------------------------------------


def _make_request_with_state(*, is_mobile: bool | None) -> Request:
    """Build a minimal ``Request`` with optional ``state.is_mobile``.

    Mirrors the pattern in ``tests/test_middleware.py`` /
    ``tests/test_csrf_rejected_log_event.py``. The scope shape is
    the minimum Starlette needs; we don't include a User-Agent
    header because these unit tests assert behaviour directly off
    ``request.state``, not via UA classification.

    Args:
        is_mobile: When ``True`` or ``False``, the flag is set on
            ``request.state``. When ``None``, the flag is left
            absent so default-deny paths can be exercised.
    """
    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("testserver", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
    }
    request = Request(scope=scope)  # type: ignore[arg-type]
    if is_mobile is not None:
        request.state.is_mobile = is_mobile
    return request


# --- Helper unit tests ----------------------------------------------------


def test_base_template_resolves_to_base_mobile_html_for_mobile_ua() -> None:
    """Helper returns ``base_mobile.html`` when ``is_mobile`` is True.

    Direct unit test of ``_select_base_template`` with a fake
    request whose ``state.is_mobile`` is True. No UA parsing
    happens here — that belongs to ``app.core.ua.is_mobile`` and is
    covered separately. This test pins the slice B contract: the
    selector reads ``request.state.is_mobile`` and returns the
    mobile base template name.
    """
    request = _make_request_with_state(is_mobile=True)

    assert getattr(request.state, "is_mobile", None) is True
    assert _select_base_template(request) == "base_mobile.html"


def test_base_template_resolves_to_base_html_for_desktop_ua() -> None:
    """Helper returns ``base.html`` (desktop) when ``is_mobile`` is False.

    Mirrors the mobile case: same helper, opposite state, opposite
    template name. Together with the mobile test this is the
    symmetry that guarantees the selector is genuinely binary.
    """
    request = _make_request_with_state(is_mobile=False)

    assert getattr(request.state, "is_mobile", None) is False
    assert _select_base_template(request) == "base.html"


def test_base_template_uses_request_state() -> None:
    """Processor reads ``request.state.is_mobile`` (slice A's flag).

    Same UA, different ``state.is_mobile`` → different
    ``base_template``. This proves the binding is to ``state``,
    not to the User-Agent header; a future refactor that moves the
    flag (e.g. to a header or cookie) would still satisfy this
    contract as long as ``state.is_mobile`` ends up correct.
    """
    mobile_request = _make_request_with_state(is_mobile=True)
    desktop_request = _make_request_with_state(is_mobile=False)

    mobile_result = base_template_context_processor(mobile_request)
    desktop_result = base_template_context_processor(desktop_request)

    assert mobile_result == {"base_template": "base_mobile.html"}
    assert desktop_result == {"base_template": "base.html"}


def test_base_template_defaults_to_base_html_when_state_missing() -> None:
    """Default-deny: missing ``state.is_mobile`` → ``base.html``.

    Mirrors the slice A default-deny posture in
    ``UADetectionMiddleware.dispatch``. Tests that build a
    ``Request`` without running the middleware (or render paths
    that bypass the chain) must not crash and must not silently
    select mobile.
    """
    request = _make_request_with_state(is_mobile=None)

    assert not hasattr(request.state, "is_mobile")
    assert _select_base_template(request) == "base.html"


# --- HTTP-level sentinels (GET /login) ------------------------------------


@pytest.fixture(autouse=True)
def _stub_local_backend_for_reval() -> None:
    """``GET /`` revalidates auth; the unit-level deps spy covers it.

    ``GET /login`` does not hit LocalBackend but ``require_authorized_user``
    on ``GET /`` and the auto-dependency cache mean the stub from
    ``tests/test_pages.py`` is the safest defensive fixture. We
    don't need it for ``/login`` itself, but installing it keeps the
    global dep cache clean across the test session.
    """
    from app.core.di.local_postgres_di import get_local_postgres_executor_dep
    from tests.conftest import auth_reval_rows

    class _RevalOnlySpy:
        def execute_sql(self, query, params=None):  # type: ignore[no-untyped-def]
            rows = auth_reval_rows(query if isinstance(query, str) else "", params)
            return rows if rows is not None else []

        def close(self) -> None:
            return None

    app.dependency_overrides[get_local_postgres_executor_dep] = lambda: _RevalOnlySpy()
    yield
    app.dependency_overrides.pop(get_local_postgres_executor_dep, None)


_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
    "Mobile/15E148 Safari/604.1"
)


async def test_login_renders_with_base_template_for_desktop(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop UA → ``GET /login`` renders ``base.html``.

    Sentinels:
    - ``id="nav-burger"`` is present (desktop template's burger
      landmark from issue #147).
    - ``viewport-fit=cover`` is absent (mobile-only marker).
    """
    monkeypatch.setenv("APAP_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("APAP_GOOGLE_CLIENT_SECRET", "test-client-secret")

    response = await client.get("/login", headers={"User-Agent": _DESKTOP_UA})

    assert response.status_code == 200, response.text
    assert 'id="nav-burger"' in response.text, (
        "desktop UA did not render base.html (burger landmark missing)"
    )
    assert "viewport-fit=cover" not in response.text, (
        "desktop UA rendered base_mobile.html (viewport-fit=cover marker should not appear)"
    )


async def test_login_renders_with_base_template_for_mobile(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mobile UA → ``GET /login`` renders ``base_mobile.html``.

    Sentinels:
    - ``viewport-fit=cover`` is present in ``<meta name="viewport">``
      (mobile template's safe-area marker).
    - ``id="nav-burger"`` is absent (mobile template has no
      desktop-style burger disclosure — it uses a single touch
      target).
    """
    monkeypatch.setenv("APAP_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("APAP_GOOGLE_CLIENT_SECRET", "test-client-secret")

    response = await client.get("/login", headers={"User-Agent": _MOBILE_UA})

    assert response.status_code == 200, response.text
    assert "viewport-fit=cover" in response.text, (
        "mobile UA did not render base_mobile.html (viewport-fit=cover marker missing)"
    )
    assert 'id="nav-burger"' not in response.text, (
        "mobile UA rendered base.html (burger landmark should not appear in mobile template)"
    )
