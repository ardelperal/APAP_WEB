"""Request correlation context via ContextVar (issue #334).

Provides a per-request correlation id that is automatically included in every
``log_safe(...)`` JSON log record. The id is:

- Generated fresh (UUID4 hex, 16 chars) on each incoming request by
  ``CorrelationIdMiddleware``.
- Stored in a ``ContextVar`` so it is accessible anywhere in the call stack
  without threading through function arguments.
- Echoed back on the response as ``X-Request-ID`` for operator correlation.
- Reset in the middleware's ``finally`` block so context does not leak between
  requests in async runners.

Usage
-----
``get_correlation_id()`` is the primary API. It returns the current correlation
id (or ``""`` when called outside any request context). It is read by
``app/core/logging.py::JsonFormatter`` on every log record.

No ``print(...)`` or ``logging.getLogger(...)`` calls in this module.
``log_safe()`` is the only allowed logging entry point in ``app/`` (AGENTS.md §9).
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

#: Module-level ContextVar holding the current request's correlation id.
#: Default is empty string so ``log_safe`` emits ``request_id: ""`` outside
#: any request context rather than raising a ``LookupError``.
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def set_correlation_id(value: str) -> contextvars.Token[str]:
    """Set the correlation id for the current context.

    Parameters
    ----------
    value:
        The correlation id to store (e.g. a 16-char UUID4 hex string).

    Returns
    -------
    contextvars.Token
        Token needed to reset the variable to its previous state via
        ``reset_correlation_id``.
    """
    return correlation_id_var.set(value)


def get_correlation_id() -> str:
    """Return the current correlation id for this context.

    Returns the value set by ``set_correlation_id`` in the current async
    context, or ``""`` when called outside any request context.

    Returns
    -------
    str
        The current correlation id (never ``None``).
    """
    return correlation_id_var.get()


def reset_correlation_id(token: contextvars.Token[str]) -> None:
    """Reset the correlation id to its previous value.

    Parameters
    ----------
    token:
        The token returned by the matching ``set_correlation_id`` call.
        Typically called in a ``finally`` block to restore the prior state.
    """
    correlation_id_var.reset(token)


#: Header name for the inbound / outbound correlation id.
X_REQUEST_ID_HEADER: str = "X-Request-ID"

#: Number of hex characters to retain from the UUID4 (16 chars = 64 bits).
_CORRELATION_ID_LENGTH: int = 16


def _generate_correlation_id() -> str:
    """Generate a short UUID4 hex string for use as a correlation id."""
    return uuid.uuid4().hex[:_CORRELATION_ID_LENGTH]


class CorrelationIdMiddleware:
    """FastAPI middleware that stamps every request with a unique correlation id.

    On each request:
    1. Reads ``X-Request-ID`` from inbound headers — if present and non-empty,
       it is honoured (allows propagation from an upstream gateway).
    2. Otherwise generates a fresh 16-char UUID4 hex string.
    3. Stores it on ``request.state.correlation_id`` for downstream access.
    4. Sets it in the ``correlation_id_var`` ContextVar so ``log_safe`` can
       read it.
    5. Injects ``X-Request-ID`` into the response headers.
    6. Resets the ContextVar in the ``finally`` block so context does not
       leak between concurrent requests.

    The middleware is intentionally lightweight: no I/O, no DB access, no
    logging beyond one startup info event.
    """

    def __init__(self, app: object) -> None:
        self.app = app

    async def __call__(
        self, scope: dict, receive: object, send: object
    ) -> None:
        """Process the request, setting and resetting the correlation id."""
        # lazy-import: avoids importing starlette at module load time
        from starlette.requests import (
            Request,  # lazy-import: avoids circular import with logging (loaded early at startup)
        )
        # Cast from 'object' (BaseHTTPMiddleware dispatch signature) to
        # concrete ASGI callable types so mypy can follow the call chain.
        _receive = cast("Callable[[], Awaitable[dict[str, Any]]]", receive)
        _send = cast("Callable[[dict[str, Any]], Awaitable[None]]", send)
        _app = cast("Callable[..., Any]", self.app)

        request = Request(scope, _receive)

        # Honour inbound X-Request-ID header if present, otherwise generate.
        inbound = request.headers.get(X_REQUEST_ID_HEADER, "")
        correlation_id = inbound if inbound else _generate_correlation_id()

        # Store on request state for any downstream code that needs it.
        request.state.correlation_id = correlation_id

        # Set in ContextVar for the duration of this request.
        token = set_correlation_id(correlation_id)

        async def send_wrapper(message: dict) -> None:
            """Inject X-Request-ID into the response before passing it on."""
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                # Only inject if not already present from an upstream gateway.
                if X_REQUEST_ID_HEADER.lower().encode() not in headers:
                    message["headers"].append(
                        (X_REQUEST_ID_HEADER.encode(), correlation_id.encode())
                    )
            await _send(message)

        try:
            await _app(scope, _receive, send_wrapper)
        finally:
            # Always reset so context does not leak to other async tasks.
            reset_correlation_id(token)
