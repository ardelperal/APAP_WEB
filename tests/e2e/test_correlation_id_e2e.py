"""E2E pinning of the ``X-Request-ID`` HTTP contract.

The contract is documented in ``docs/canonical-logs.md`` § "Inbound-to-outbound
lifecycle":

- A request without ``X-Request-ID`` triggers ``CorrelationIdMiddleware`` to
  mint a fresh 16-char UUID hex and echo it on the response.
- A request with ``X-Request-ID`` is honoured verbatim and echoed back, so
  tracing propagates through upstream gateways (load balancer, reverse proxy).

The middleware logic itself is pinned by ``tests/integration/test_canonical_logs.py``
at the unit level; this file asserts the round-trip across a real HTTP server
bound to ``BASE_URL``. Skipping when the server is unavailable matches the
existing E2E pattern in ``tests/e2e/conftest.py``.
"""

from __future__ import annotations

import re

from playwright.sync_api import BrowserContext

X_REQUEST_ID_HEADER = "X-Request-ID"
_UUID_HEX_16 = re.compile(r"^[0-9a-f]{16}$")


def test_healthz_response_carries_generated_request_id(
    browser_context: BrowserContext,
    base_url: str,
) -> None:
    """``/healthz`` (no inbound header) returns a fresh UUID hex in ``X-Request-ID``.

    Scenario: an upstream gateway does NOT propagate a correlation id, so
    the middleware must mint one. The id must be the documented shape —
    16 lowercase hex chars — so downstream log-matching is positional, not
    regex magic.
    """
    response = browser_context.request.get(f"{base_url}/healthz")
    assert response.status == 200, (
        f"/healthz must remain public for this contract pin; got {response.status}"
    )
    request_id = response.headers.get(X_REQUEST_ID_HEADER, "")
    assert request_id, (
        f"missing {X_REQUEST_ID_HEADER} header on /healthz response; the middleware "
        "must always stamp the header even on public probes"
    )
    assert _UUID_HEX_16.match(request_id), (
        f"X-Request-ID={request_id!r} does not match the documented UUID hex-16 shape; "
        "see docs/canonical-logs.md § 'Inbound-to-outbound lifecycle'"
    )


def test_inbound_request_id_is_echoed_back_verbatim(
    browser_context: BrowserContext,
    base_url: str,
) -> None:
    """An inbound ``X-Request-ID`` propagates unchanged into the response.

    Scenario: a load balancer in front of the app injects ``X-Request-ID``
    with its own trace id. The middleware must NOT regenerate it — the
    upstream trace must survive intact so operators can join client-side
    and server-side logs across the gateway boundary.
    """
    upstream_id = "0" * 16
    response = browser_context.request.get(
        f"{base_url}/healthz",
        headers={X_REQUEST_ID_HEADER: upstream_id},
    )
    assert response.status == 200
    echoed = response.headers.get(X_REQUEST_ID_HEADER, "")
    assert echoed == upstream_id, (
        f"middleware regenerated the inbound {X_REQUEST_ID_HEADER}; "
        f"upstream={upstream_id!r} echoed={echoed!r}; the contract requires verbatim echo"
    )


def test_two_requests_get_distinct_generated_ids(
    browser_context: BrowserContext,
    base_url: str,
) -> None:
    """Two requests without an inbound header receive distinct ids.

    Scenario: the middleware mints a fresh id per request (not a single
    process-wide id) so concurrent users' logs stay distinguishable. A
    static-id regression would make /healthz useless for tracing.
    """
    first = browser_context.request.get(f"{base_url}/healthz")
    second = browser_context.request.get(f"{base_url}/healthz")
    assert first.status == 200 and second.status == 200
    first_id = first.headers.get(X_REQUEST_ID_HEADER, "")
    second_id = second.headers.get(X_REQUEST_ID_HEADER, "")
    assert first_id and second_id, (
        "one of the requests missed the X-Request-ID header — middleware skipped a request"
    )
    assert first_id != second_id, (
        f"middleware reused id={first_id!r} across requests; the contract requires "
        "a fresh id per request so concurrent logs stay distinguishable"
    )
