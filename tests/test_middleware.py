"""Integration tests for ``UADetectionMiddleware`` (slice A wiring).

Two layers of coverage:

1. **Unit-test the dispatch logic** with a minimal fake Request
   (mirroring the pattern in ``tests/test_csrf_rejected_log_event.py``).
   This validates the middleware does what the helper says it does:
   populate ``request.state.is_mobile`` per request, default False
   when the UA header is missing.

2. **Smoke-test the registration**: the module-level ``app`` must
   have ``UADetectionMiddleware`` in its middleware stack. This is
   the only test that survives a future refactor where the helper
   logic moves to a different layer (e.g. context processor). If
   someone removes the ``add_middleware(UADetectionMiddleware)``
   line from ``app/main.py``, this test fails.

Note: the middleware is purely additive — it never short-circuits,
never raises, never logs. So we don't exercise error paths
(no 5xx, no rejection).
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.middleware import UADetectionMiddleware
from app.main import app as _app

# --- Helpers ---------------------------------------------------------------


class _OkResponse:
    """Minimal response stub returned by ``_call_next``.

    We don't construct a full ``Response`` (it requires a body and
    a media type), so a duck-typed object with ``status_code``
    suffices: the middleware returns whatever ``call_next`` returns.
    """

    status_code = 200


def _make_request(user_agent: str | None) -> Request:
    """Build a minimal fake ``Request`` with the given User-Agent.

    The scope shape mirrors ``tests/test_csrf_rejected_log_event.py`` —
    enough to satisfy Starlette's ``Request(...)`` constructor. We
    pass a list of header tuples so we can include the
    ``user-agent`` header conditionally. UTF-8 bytes per the ASGI spec.
    """
    headers: list[tuple[bytes, bytes]] = [(b"host", b"testserver")]
    if user_agent is not None:
        headers.append((b"user-agent", user_agent.encode("utf-8")))

    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("testserver", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
    }
    return Request(scope=scope)  # type: ignore[arg-type]


async def _capture_is_mobile(
    request: Request,
) -> int:
    """Side-effect capture: read ``request.state.is_mobile`` and echo it back.

    Used as ``call_next`` in the unit tests below. The middleware's
    contract is "the next handler sees ``request.state.is_mobile``" —
    this helper proves it.
    """
    # Stash on a private attribute the test can read after dispatch.
    _capture_is_mobile.captured = getattr(request.state, "is_mobile", None)  # type: ignore[attr-defined]
    return 200


# --- Middleware dispatch unit tests ---------------------------------------


@pytest.mark.asyncio
async def test_ua_detection_middleware_sets_is_mobile_true_for_mobile_ua() -> None:
    """Mobile UA → ``request.state.is_mobile`` is ``True`` at call_next."""
    request = _make_request(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
        "Mobile/15E148 Safari/604.1"
    )
    captured: dict[str, object] = {}

    async def call_next(req: Request) -> int:
        captured["is_mobile"] = req.state.is_mobile
        return 200

    middleware = UADetectionMiddleware(app=None)  # type: ignore[arg-type]
    # type: ignore reason: BaseHTTPMiddleware's ``app`` is the ASGI app
    # downstream of this middleware; we don't exercise the chain here,
    # only the dispatch logic.

    response = await middleware.dispatch(request, call_next)

    assert captured["is_mobile"] is True
    assert response == 200


@pytest.mark.asyncio
async def test_ua_detection_middleware_sets_is_mobile_false_for_desktop_ua() -> None:
    """Desktop UA → ``request.state.is_mobile`` is ``False`` at call_next."""
    request = _make_request(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    captured: dict[str, object] = {}

    async def call_next(req: Request) -> int:
        captured["is_mobile"] = req.state.is_mobile
        return 200

    middleware = UADetectionMiddleware(app=None)  # type: ignore[arg-type]
    response = await middleware.dispatch(request, call_next)

    assert captured["is_mobile"] is False
    assert response == 200


@pytest.mark.asyncio
async def test_ua_detection_middleware_sets_is_mobile_false_for_missing_ua() -> None:
    """Missing User-Agent header → ``request.state.is_mobile`` is ``False``.

    Default-deny posture: a missing header means we don't know if the
    caller is mobile, so we treat it as desktop. False positives
    (showing mobile layout to desktop users) are user-visible
    regressions; false negatives (showing desktop to mobile users)
    are recoverable by adding a friendlier UA. Defaults to the
    safer side.
    """
    request = _make_request(None)
    captured: dict[str, object] = {}

    async def call_next(req: Request) -> int:
        captured["is_mobile"] = req.state.is_mobile
        return 200

    middleware = UADetectionMiddleware(app=None)  # type: ignore[arg-type]
    response = await middleware.dispatch(request, call_next)

    assert captured["is_mobile"] is False
    assert response == 200


@pytest.mark.asyncio
async def test_ua_detection_middleware_sets_is_mobile_false_for_ipad() -> None:
    """iPad UA → ``request.state.is_mobile`` is ``False`` (tablet guard).

    Sanity check that the dispatch path agrees with ``is_mobile``:
    the helper's tablet exclusion must reach the request.state.
    """
    request = _make_request(
        "Mozilla/5.0 (iPad; CPU OS 13_2 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0 "
        "Mobile/15E148 Safari/604.1"
    )
    captured: dict[str, object] = {}

    async def call_next(req: Request) -> int:
        captured["is_mobile"] = req.state.is_mobile
        return 200

    middleware = UADetectionMiddleware(app=None)  # type: ignore[arg-type]
    response = await middleware.dispatch(request, call_next)

    assert captured["is_mobile"] is False
    assert response == 200


# --- Registration smoke test -----------------------------------------------


def test_ua_detection_middleware_is_registered_in_app() -> None:
    """The module-level ``app`` registers ``UADetectionMiddleware``.

    This guards against accidental removal of ``add_middleware``
    from ``app/main.py``. ``app.user_middleware`` is a list of
    Starlette middleware descriptors; we read the ``cls`` attribute
    and compare by class name to avoid coupling to the exact
    registration order or the ``BaseHTTPMiddleware`` subclass wrapping.
    """
    middleware_class_names = {
        descriptor.cls.__name__ for descriptor in _app.user_middleware
    }
    assert "UADetectionMiddleware" in middleware_class_names, (
        "UADetectionMiddleware is not registered in app.main:create_app. "
        "Add `application.add_middleware(UADetectionMiddleware)` so "
        "request.state.is_mobile is populated per request."
    )
