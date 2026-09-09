"""Global FastAPI exception handler that translates ``InsForgeError`` to a 502.

§32.P4 (issues #277, #278): a route that catches only its domain
error (``ValueError``) and lets transport errors (network failures,
upstream 5xx, timeouts) propagate uncaught becomes a 500. This
shim registers a global handler bound to the
:class:`ErrorTranslationPort`'s ``target_exception_type`` and
surfaces every unhandled transport error as a non-leaking 502.

This module owns the registration so ``app/main.py`` does not grow
past the §21 module-size budget. ``register_insforge_error_handler``
is a single call from ``create_app``'s call site.

Hexagonal taxonomy (issue #420):

- Port    :mod:`app.core.ports.insforge_error_handler_port` — abstract surface.
- Adapter :mod:`app.core.adapters.insforge.insforge_error_handler_insforge_adapter`
  — InsForge impl.
- DI      :mod:`app.core.di.insforge_error_handler_di` — wiring.
- THIS   (this module) — shim: FastAPI exception handler
  registration + ``log_safe`` observability.

This slice intentionally OMITS the ``application/`` layer. The use
case here is a single one-line delegation to
``port.to_user_response(exc)`` — there is no multi-step orchestration
worth extracting into its own package. The §33 layer checker forbids
infrastructure → application imports without a BASELINE ratchet entry,
and the BASELINE rule says "never add a new entry" — so the trivial
use case lives inline in this shim. Future requirements that add real
logic (rate-limited translation, per-exception rules, ...) can grow
an ``app/core/application/insforge_error_handler/`` package at that
time and wire it through ``app/main.py`` (delivery) without rewriting
the shim.
"""


from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import log_safe
from app.core.ports.insforge_error_handler_port import (
    ErrorTranslationPort,
    TranslatableError,
)


def register_insforge_error_handler(
    app: FastAPI, port: ErrorTranslationPort
) -> None:
    """Register a global handler that translates unhandled transport errors to 502.

    The duplicate-email path translates ``InsForgeError`` to
    ``ValueError`` inside the admin slice so the route renders it
    as a friendly flash. Every OTHER transport error reaching this
    handler is a transport / server failure from the upstream — it
    surfaces as a 502 with a non-leaking body and full context
    emitted via :func:`log_safe`.

    Without this handler, a route's narrow ``except ValueError``
    would let ``InsForgeError`` propagate to a generic 500 page
    (the §32.P4 anti-pattern judgment-day flagged as BLOCKER on
    PR #308).

    Args:
        app: The FastAPI application instance.
        port: The translation rule (which exception class to bind
            to and how to translate it). The DI layer
            (:mod:`app.core.di.insforge_error_handler_di`) provides
            the production
            :class:`~app.core.adapters.insforge.insforge_error_handler_insforge_adapter.BackendErrorTranslation`
            adapter.
    """
    target_cls = port.target_exception_type

    @app.exception_handler(target_cls)
    async def _insforge_error_handler(
        request: Request, exc: BaseException
    ) -> JSONResponse:
        # ``isinstance`` against the runtime-checkable Protocol is
        # safe — ``TranslatableError`` is marked
        # ``@runtime_checkable`` so an unrelated exception that
        # somehow reaches the handler falls through with
        # ``status_code=None`` instead of raising AttributeError.
        status_code = (
            exc.status_code
            if isinstance(exc, TranslatableError)
            else None
        )
        log_safe(
            "insforge.unhandled_error",
            path=request.url.path,
            method=request.method,
            status_code=status_code,
        )
        response = port.to_user_response(exc)
        return JSONResponse(
            status_code=response.http_status, content=response.body
        )


__all__ = ["register_insforge_error_handler"]
