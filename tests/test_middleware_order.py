"""Tests for app/main.py::create_app middleware ordering (issue #336).

These tests pin the EXACT middleware order inside ``create_app()`` so
any reordering is caught immediately. The ordering is load-bearing:

- RateLimitMiddleware MUST be innermost (registered first via
  ``install_rate_limit_middleware`` called before ``install_auth_middleware``)
  so that CSRF rejections do NOT consume a legitimate user's rate budget.
- CsrfMiddleware MUST be second-to-last in the Starlette user_middleware
  list (registered inside ``install_auth_middleware``).
- SecurityHeadersMiddleware MUST be outermost (registered last inside
  ``install_auth_middleware`` via ``install_security_headers_middleware``).

The full order (outermost → innermost) is:
  SecurityHeadersMiddleware
  UADetectionMiddleware
  BaseHTTPMiddleware  (protect_user_facing_routes)
  CsrfMiddleware
  RateLimitMiddleware

Any change to this order is a BREAKING CHANGE that requires explicit
approval via a dedicated issue and PR — no silent reordering.
"""

from __future__ import annotations

from app.main import create_app


def test_create_app_middleware_order_is_pinned() -> None:
    """Middleware order in create_app() is load-bearing and MUST NOT change.

    Fails if anyone reorders the middleware registration calls or the
    internal ordering inside ``install_auth_middleware`` /
    ``install_rate_limit_middleware``.

    The order (outermost → innermost, Starlette ``add_middleware`` prepends):
      1. SecurityHeadersMiddleware  (added last via install_security_headers_middleware)
      2. UADetectionMiddleware     (added via install_auth_middleware, last)
      3. BaseHTTPMiddleware        (protect_user_facing_routes via @app.middleware("http"))
      4. CsrfMiddleware            (added via install_auth_middleware, first)
      5. RateLimitMiddleware       (added first, before install_auth_middleware)

    Rationale (issue #286 D8):
      - RateLimitMiddleware must be innermost so that a CSRF rejection (403)
        does NOT consume a legitimate user's rate budget.
      - SecurityHeadersMiddleware must be outermost so it wraps every response.
    """
    app = create_app()
    class_names = [descriptor.cls.__name__ for descriptor in app.user_middleware]

    expected = [
        "SecurityHeadersMiddleware",
        "UADetectionMiddleware",
        "BaseHTTPMiddleware",
        "CsrfMiddleware",
        "RateLimitMiddleware",
    ]
    assert class_names == expected, (
        f"create_app() middleware order changed — this is a BREAKING CHANGE. "
        f"expected={expected!r}, got={class_names!r}. "
        f"See tests/test_middleware_order.py for the load-bearing rationale."
    )
