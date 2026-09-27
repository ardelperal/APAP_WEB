"""Inbound X-Request-ID validation (issue #920, finding A-08).

The correlation middleware must only honour inbound ids matching
``[A-Za-z0-9._-]{1,128}``. Anything else — a 10 kB header, control
characters, an over-long id, empty — is replaced by a freshly generated
id so a hostile upstream cannot poison ``log_safe`` records or collide
correlation ids. Valid ids (including a 128-char boundary value) keep
being honoured, and the response echoes the sanitized id.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.request_context import X_REQUEST_ID_HEADER, CorrelationIdMiddleware

#: Shape of a freshly generated correlation id (16-char UUID4 hex).
_GENERATED_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class _InnerApp:
    """Minimal ASGI app capturing the correlation id inside the request."""

    def __init__(self) -> None:
        self.correlation_id: str | None = None

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        from app.core.request_context import get_correlation_id

        self.correlation_id = get_correlation_id()
        await send({"type": "http.response.start", "status": 200, "headers": []})


async def _run_middleware(headers: dict[str, str]) -> tuple[str | None, dict]:
    """Run CorrelationIdMiddleware over one synthetic HTTP scope.

    Returns the correlation id observed inside the request and the last
    ASGI message sent (the response start, with injected headers).
    """
    inner = _InnerApp()
    asgi_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in headers.items()
    ]
    scope = {"type": "http", "headers": asgi_headers}

    async def receive() -> dict[str, str]:
        return {"type": "http.request"}

    sent: dict = {}

    async def send(message: dict) -> None:
        sent.update(message)

    await CorrelationIdMiddleware(inner)(scope, receive, send)
    return inner.correlation_id, sent


class TestInboundRequestIdValidation:
    """Only ``[A-Za-z0-9._-]{1,128}`` inbound ids are honoured (issue #920)."""

    async def test_valid_inbound_id_is_honoured(self) -> None:
        correlation_id, _ = await _run_middleware(
            {X_REQUEST_ID_HEADER: "abc-123_XY.09"}
        )

        assert correlation_id == "abc-123_XY.09"

    async def test_boundary_128_char_id_is_honoured(self) -> None:
        valid = "a" * 128

        correlation_id, _ = await _run_middleware({X_REQUEST_ID_HEADER: valid})

        assert correlation_id == valid

    async def test_boundary_129_char_id_is_replaced(self) -> None:
        inbound = "a" * 129

        correlation_id, _ = await _run_middleware({X_REQUEST_ID_HEADER: inbound})

        assert correlation_id != inbound
        assert _GENERATED_ID_PATTERN.match(correlation_id or "")

    async def test_10kb_header_is_replaced(self) -> None:
        inbound = "x" * 10_000

        correlation_id, _ = await _run_middleware({X_REQUEST_ID_HEADER: inbound})

        assert correlation_id != inbound
        assert _GENERATED_ID_PATTERN.match(correlation_id or "")

    async def test_control_characters_and_non_ascii_are_replaced(self) -> None:
        for hostile in ("abc\n123", "a\tb", "a\x00b", "café", "id with spaces"):
            correlation_id, _ = await _run_middleware({X_REQUEST_ID_HEADER: hostile})

            assert correlation_id != hostile, f"id not rejected: {hostile!r}"
            assert _GENERATED_ID_PATTERN.match(correlation_id or "")

    async def test_empty_header_is_replaced(self) -> None:
        correlation_id, _ = await _run_middleware({X_REQUEST_ID_HEADER: ""})

        assert _GENERATED_ID_PATTERN.match(correlation_id or "")

    async def test_response_echoes_sanitized_id(self) -> None:
        _, sent = await _run_middleware({X_REQUEST_ID_HEADER: "abc\n123"})

        response_headers = {k.decode(): v.decode() for k, v in sent["headers"]}

        assert _GENERATED_ID_PATTERN.match(response_headers[X_REQUEST_ID_HEADER])
