"""Global FastAPI exception handler for InsForgeError.

§32.P4 (issues #277, #278): a route that catches only its domain error
(``ValueError``) and lets transport errors (network failures, upstream
5xx, timeouts) propagate uncaught becomes a 500. A global handler
registered after the application is built short-circuits every
``InsForgeError`` that is not already caught locally and surfaces it as
a non-leaking 502.

This module owns the registration so ``app/main.py`` does not grow past
the §21 module-size budget. ``register_insforge_error_handler(app)`` is
a single call from ``create_app``'s call site — a 31-line ``app/main.py``
delta instead of a 60+ line block.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.insforge import InsForgeError
from app.core.logging import log_safe


def register_insforge_error_handler(app: FastAPI) -> None:
    """Register a global handler that converts unhandled InsForgeError into 502.

    The duplicate-email path translates ``InsForgeError`` to ``ValueError``
    inside ``add_authorized_user`` so the admin route renders it as a
    friendly flash. Every OTHER ``InsForgeError`` reaching this handler is
    a transport / server failure from the upstream database — surface it
    as 502 Bad Gateway with a non-leaking ``detail`` message and log full
    context via ``log_safe``.

    Without this handler, the route's narrow ``except ValueError`` would
    let ``InsForgeError`` propagate to a generic 500 page (the §32.P4
    anti-pattern judgment-day flagged as BLOCKER on PR #308).
    """

    @app.exception_handler(InsForgeError)
    async def _insforge_error_handler(
        request: Request, exc: InsForgeError
    ) -> JSONResponse:
        log_safe(
            "insforge.unhandled_error",
            path=request.url.path,
            method=request.method,
            status_code=exc.status_code,
        )
        return JSONResponse(
            status_code=502,
            content={
                "detail": (
                    "Upstream database error. Please retry; "
                    "if it persists, contact an operator."
                )
            },
        )
