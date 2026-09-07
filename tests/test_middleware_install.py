"""Tests for the extracted auth-middleware installer (issue #204).

The refactor (closes #204) moves the auth-related middleware setup out
of ``app/main.py`` into :func:`app.core.middleware.install_auth_middleware`.

These tests pin the contract the installer must hold against the
running app:

1. ``install_auth_middleware`` exists and is callable with the original
   signature ``install_auth_middleware(app, settings)``.
2. After registration, ``app.user_middleware`` carries the same set of
   middleware classes (``CsrfMiddleware``, the protect middleware as a
   ``BaseHTTPMiddleware`` subclass from Starlette's ``@app.middleware``
   decorator, and ``UADetectionMiddleware``) in the SAME order as the
   pre-refactor ``create_app`` in ``app/main.py``.

   The order is observable on a request: Starlette's ``add_middleware``
   stores at the front of ``user_middleware`` and the LAST stored runs
   first on a request (outermost). The pre-refactor stack on a request
   is ``UADetection`` -> ``protect`` -> ``Csrf`` -> routes; the
   installer must reproduce this without inverting any pair.
3. When ``Settings.csrf_enabled=False``, ``CsrfMiddleware`` is omitted
   (matches the pre-refactor ``if settings.csrf_enabled`` guard).
4. The auth-redirect behavior (302 to ``/login`` for protected GETs)
   continues to work end-to-end after the installer runs.

The tests use the module-level ``app`` fixture's introspection surface
(``app.user_middleware``, ``app.middleware_stack`` after build) — same
shape as the existing ``tests/test_middleware.py`` smoke test.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.middleware import (
    UADetectionMiddleware,
    install_auth_middleware,
)
from app.main import app as _app

# --- shape -----------------------------------------------------------------


def test_install_auth_middleware_is_callable_from_app_core_middleware() -> None:
    """The installer lives at ``app.core.middleware.install_auth_middleware``.

    Contract for the refactor (issue #204): one function imports the
    full auth chain. The atom asserts the symbol exists and is callable
    so the rest of the module can import it.
    """
    assert callable(install_auth_middleware), (
        "app.core.middleware.install_auth_middleware must be callable; "
        "the refactor introduces this symbol as the single import surface"
    )


# --- middleware chain shape ------------------------------------------------


_EXPECTED_AUTH_ONLY_MIDDLEWARE_CLASS_NAMES: tuple[str, ...] = (
    # Order for a fresh app with ONLY install_auth_middleware called.
    # Starlette's add_middleware() prepends; LAST registered = FIRST in list.
    # install_auth_middleware registers (in order): CsrfMiddleware,
    # protect_user_facing_routes (BaseHTTPMiddleware), UADetectionMiddleware,
    # then SecurityHeadersMiddleware (OUTERMOST — added last, so runs first).
    # Final: ['SecurityHeadersMiddleware', 'UADetectionMiddleware',
    #         'BaseHTTPMiddleware', 'CsrfMiddleware']
    "SecurityHeadersMiddleware",
    "UADetectionMiddleware",
    "BaseHTTPMiddleware",
    "CsrfMiddleware",
)

_EXPECTED_MIDDLEWARE_CLASS_NAMES: tuple[str, ...] = (
    # Order in user_middleware list: FIRST item = OUTERMOST (wraps all others).
    # Registration sequence in create_app():
    #   1. CorrelationIdMiddleware added FIRST → appears LAST in list (innermost,
    #      catches requests AFTER auth chain; still sees auth-chain responses on the
    #      way back out, which is sufficient for issue #334).
    #   2. install_rate_limit_middleware adds RateLimitMiddleware.
    #   3. install_auth_middleware adds SecurityHeaders, UADetection, BaseHTTPMiddleware,
    #      CsrfMiddleware (last-registered inside install_auth = innermost of the auth chain).
    # Final list order (first=outermost): SecurityHeaders → UADetection → BaseHTTPMiddleware
    # → CsrfMiddleware → RateLimitMiddleware → CorrelationIdMiddleware (innermost).
    "SecurityHeadersMiddleware",
    "UADetectionMiddleware",
    "BaseHTTPMiddleware",
    "CsrfMiddleware",
    "RateLimitMiddleware",
    "CorrelationIdMiddleware",
)


def _registered_class_names(app) -> list[str]:
    """Return the names of every middleware class registered on ``app``.

    Matches the introspection pattern in
    ``tests/test_middleware.py::test_ua_detection_middleware_is_registered_in_app``.
    """
    return [descriptor.cls.__name__ for descriptor in app.user_middleware]


def test_install_auth_middleware_registers_full_chain_in_order() -> None:
    """``install_auth_middleware`` registers the same chain as pre-refactor main.py.

    The atom builds a fresh ``FastAPI`` app and runs the installer.
    No explicit ordering is asserted via Starlette's stored list; the
    invariant is the expected subsequence (insertion order via
    ``add_middleware`` -> the comment in ``main.py:296-302`` pins the
    runtime order).
    """
    from fastapi import FastAPI

    from app.core.config import get_settings as _gs

    fresh_app = FastAPI()
    install_auth_middleware(fresh_app, _gs())
    registered = _registered_class_names(fresh_app)
    assert registered == list(_EXPECTED_AUTH_ONLY_MIDDLEWARE_CLASS_NAMES), (
        f"install_auth_middleware must register the same chain in the "
        f"same order as the pre-refactor main.py. "
        f"expected={_EXPECTED_MIDDLEWARE_CLASS_NAMES!r}, "
        f"got={registered!r}"
    )


def test_install_auth_middleware_chain_includes_ua_detection() -> None:
    """``UADetectionMiddleware`` is registered by the installer.

    Defence-in-depth: smoke test against the specific class so a
    future refactor that drops UA detection from the installer fails
    here, not via a downstream UX regression.
    """
    from fastapi import FastAPI

    from app.core.config import get_settings as _gs

    fresh_app = FastAPI()
    install_auth_middleware(fresh_app, _gs())
    class_names = _registered_class_names(fresh_app)
    assert "UADetectionMiddleware" in class_names, (
        f"UADetectionMiddleware missing from install_auth_middleware output: "
        f"{class_names!r}"
    )


def test_install_auth_middleware_chain_includes_csrf_when_enabled() -> None:
    """``CsrfMiddleware`` is registered when ``Settings.csrf_enabled=True``.

    The default ``Settings()`` returns ``csrf_enabled=True``; that is
    the production posture. The atom catches a future refactor that
    forgets the conditional register block (issue #204 must NOT drop
    the feature flag — see ``app/main.py:256-257``).
    """
    from fastapi import FastAPI

    from app.core.config import get_settings as _gs

    fresh_app = FastAPI()
    settings = _gs().model_copy(update={"csrf_enabled": True})
    install_auth_middleware(fresh_app, settings)
    class_names = _registered_class_names(fresh_app)
    assert "CsrfMiddleware" in class_names, (
        f"CsrfMiddleware missing under csrf_enabled=True: {class_names!r}"
    )


def test_install_auth_middleware_omits_csrf_when_disabled() -> None:
    """``CsrfMiddleware`` is omitted when ``Settings.csrf_enabled=False``.

    Mirrors the pre-refactor ``if settings.csrf_enabled`` guard at
    ``app/main.py:256-257``. The atom must catch an installer that
    registers Csrf unconditionally.
    """
    from fastapi import FastAPI

    from app.core.config import get_settings as _gs

    fresh_app = FastAPI()
    settings = _gs().model_copy(update={"csrf_enabled": False})
    install_auth_middleware(fresh_app, settings)
    class_names = _registered_class_names(fresh_app)
    assert "CsrfMiddleware" not in class_names, (
        f"CsrfMiddleware must NOT register when csrf_enabled=False "
        f"(pre-refactor guard at app/main.py:256-257); got {class_names!r}"
    )


# --- end-to-end auth behavior ---------------------------------------------


@pytest.mark.asyncio
async def test_installed_chain_redirects_unauthenticated_to_login(
    client: httpx.AsyncClient,
) -> None:
    """After the installer runs, an unauthenticated GET to a protected
    route still returns 302 to ``/login``.

    The full main.py app is built and tested against the running fixture
    (canonical pattern across tests/test_*.py). The behaviour pins the
    end-to-end contract that the refactor preserves: the auth chain is
    identical, only the registration call moved.
    """
    response = await client.get("/voluntarios", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers.get("location") == "/login"


def test_main_app_middleware_chain_unchanged_after_refactor() -> None:
    """The module-level ``app`` carries the same middleware chain the
    pre-refactor main.py produced.

    Pins the public observable: nothing changed in the running app's
    middleware stack. The class-name tuple matches the
    ``create_app`` registration order at main.py:255-303 exactly.
    """
    assert _registered_class_names(_app) == list(_EXPECTED_MIDDLEWARE_CLASS_NAMES), (
        f"module-level app middleware chain drift after the refactor. "
        f"expected={_EXPECTED_MIDDLEWARE_CLASS_NAMES!r}, "
        f"got={_registered_class_names(_app)!r}"
    )


# --- UADetectionMiddleware re-export from middleware module --------------


def test_ua_detection_middleware_reexported_from_core_middleware() -> None:
    """``UADetectionMiddleware`` is importable from ``app.core.middleware``.

    Pre-refactor contract preserved: existing imports of this class
    (e.g. ``tests/test_middleware.py``) keep working without changes.
    """
    assert UADetectionMiddleware is not None
