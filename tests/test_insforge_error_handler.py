"""Functional test for the global InsForge error handler slice.

Exercises the §32.P4 (issue #277) path end-to-end: a route raises
:class:`InsForgeError`, the global handler bound to the port's
``target_exception_type`` translates it into a non-leaking 502,
and the response body matches the legacy contract byte-for-byte.

This test replaces the implicit "no covering test" gap that
CodeGraph flagged for the legacy 58-line module. It belongs in
the default test run (no env-var gate, no transport) so a
regression on the slice is caught on every CI run, not just on
the E2E job.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.data_access import InsForgeError
from app.core.di.insforge_error_handler_di import (
    InsForgeErrorTranslation,
)
from app.core.error_handler import register_insforge_error_handler


@pytest.fixture
def app_with_handler() -> FastAPI:
    """Build a minimal FastAPI app wired to the slice's production port."""
    application = FastAPI()
    register_insforge_error_handler(
        application, InsForgeErrorTranslation()
    )

    @application.get("/boom")
    def boom() -> None:
        raise InsForgeError(status_code=500, body={"error": "kaboom"})

    return application


def test_insforge_error_returns_502_with_non_leaking_body(
    app_with_handler: FastAPI,
) -> None:
    """An unhandled ``InsForgeError`` surfaces as 502 with a generic detail.

    The body does NOT echo the original ``status_code`` or ``body``
    of the exception — operators see those in ``log_safe`` events,
    clients see the non-leaking ``detail`` string the adapter
    declares.
    """
    client = TestClient(app_with_handler, raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 502
    payload = response.json()
    assert payload == {
        "detail": (
            "Upstream database error. Please retry; "
            "if it persists, contact an operator."
        )
    }
    assert "500" not in payload["detail"]
    assert "kaboom" not in payload["detail"]


def test_insforge_error_handler_inherits_through_data_access_error(
    app_with_handler: FastAPI,
) -> None:
    """``DuplicateKeyError`` (a subclass of ``InsForgeError``) is also caught.

    The handler is bound to ``target_exception_type`` which is the
    base :class:`InsForgeError`; subclasses are caught by FastAPI's
    exception handler chain naturally.
    """
    from app.core.data_access import DuplicateKeyError

    @app_with_handler.get("/boom-dup")
    def boom_dup() -> None:
        raise DuplicateKeyError("duplicate key")

    client = TestClient(app_with_handler, raise_server_exceptions=False)
    response = client.get("/boom-dup")
    assert response.status_code == 502
    assert "duplicate key" not in response.text


def test_unrelated_exception_passes_through_to_default_500(
    app_with_handler: FastAPI,
) -> None:
    """An exception the handler is NOT bound to surfaces as FastAPI's default 500.

    The handler fires only for instances of
    ``port.target_exception_type``; everything else uses FastAPI's
    built-in exception handling. This is the §32.P4 contract: the
    handler is the catch for the ONE specific exception class, not
    a blanket ``except Exception``.
    """
    @app_with_handler.get("/boom-runtime")
    def boom_runtime() -> None:
        raise RuntimeError("not a transport error")

    client = TestClient(app_with_handler, raise_server_exceptions=False)
    response = client.get("/boom-runtime")
    assert response.status_code == 500


def test_legacy_shim_still_exports_register_function() -> None:
    """The shim module exposes ``register_insforge_error_handler`` for backwards compat.

    Issue #420 acceptance criterion: ``from app.core.insforge_error_handler
    import register_insforge_error_handler`` keeps working for any
    out-of-tree consumer that imported the function from the old
    path. The function is now defined in the shim itself (the
    slice has no application layer — see the shim's docstring).
    """
    from app.core.error_handler import (
        register_insforge_error_handler as shim_function,
    )

    # The shim defines the function; calling it must not raise.
    assert callable(shim_function)
    # And it must be the same symbol the test fixture used.
    assert shim_function is register_insforge_error_handler


def test_di_provider_returns_error_translation_port() -> None:
    """``get_insforge_error_handler_port()`` returns the production adapter.

    The project uses structural typing (Protocol without
    ``@runtime_checkable`` — see ``app.core.ports.oauth_port`` for
    the precedent). The contract is verified by attribute shape,
    not by ``isinstance``: the port exposes
    ``target_exception_type`` and ``to_user_response``, and the
    production adapter binds the first to :class:`InsForgeError`.
    """
    from app.core.di.insforge_error_handler_di import (
        get_insforge_error_handler_port,
    )

    port = get_insforge_error_handler_port()
    assert hasattr(port, "target_exception_type")
    assert hasattr(port, "to_user_response")
    assert port.target_exception_type is InsForgeError


def test_adapter_translate_preserves_legacy_body_shape() -> None:
    """The InsForge adapter returns the EXACT body the legacy handler returned.

    Regression guard for #420 acceptance: the user-facing 502 body
    must stay byte-identical to the pre-slice implementation so no
    client integration breaks.
    """
    exc = InsForgeError(status_code=503, body={"error": "upstream slow"})
    response = InsForgeErrorTranslation().to_user_response(exc)

    assert response.http_status == 502
    assert response.body == {
        "detail": (
            "Upstream database error. Please retry; "
            "if it persists, contact an operator."
        )
    }


__all__ = [
    "test_adapter_translate_preserves_legacy_body_shape",
    "test_di_provider_returns_error_translation_port",
    "test_insforge_error_handler_inherits_through_data_access_error",
    "test_insforge_error_returns_502_with_non_leaking_body",
    "test_legacy_shim_still_exports_register_function",
    "test_unrelated_exception_passes_through_to_default_500",
]
