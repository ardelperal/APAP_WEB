"""FastAPI wiring for the global transport-error handler port.

The :func:`get_insforge_error_handler_port` provider is the seam
between FastAPI's exception-handler registration and the hexagonal
:class:`ErrorTranslationPort` abstraction. Production wires the
:class:`BackendErrorTranslation` adapter; tests can substitute
their own adapter by passing a different port directly to
:func:`app.core.application.insforge_error_handler.register_insforge_error_handler`.

Pattern (mirrors :func:`app.core.di.oauth_di.get_oauth_port`):

- The adapter is stateless, so the provider returns a
  module-level singleton rather than a generator — there is no
  per-request state to yield.
- No transport resources are owned by this helper. The lifespan
  owns the database connection pool; the adapter
  is built once at module load and reused forever.

Rule §31 (domain services depend on Protocol abstractions): the
provider returns the :class:`ErrorTranslationPort` interface, not
the concrete :class:`BackendErrorTranslation` adapter. Future
multi-transport deployments would swap adapters here without
touching the application layer.
"""


from __future__ import annotations

from app.core.data_access import BackendError
from app.core.ports.insforge_error_handler_port import ErrorTranslationPort, ErrorUserResponse


class BackendErrorTranslation:
    """Translation rule for :class:`BackendError`.

    Implements :class:`ErrorTranslationPort` for the local backend
    transport (LocalPostgresExecutor, LocalBackendOAuthAdapter).
    Holds no state; the FastAPI request is forwarded by
    :func:`app.core.application.insforge_error_handler.register_insforge_error_handler`
    when the registered exception handler fires.
    """

    @property
    def target_exception_type(self) -> type[Exception]:
        """Return :class:`BackendError` — the class the global handler binds to.

        The application uses this as the first argument to
        ``@app.exception_handler(...)`` so the handler fires for
        every ``BackendError`` (and its subclasses) that is not
        already caught locally by a route.
        """
        return BackendError

    def to_user_response(self, exc: BaseException) -> ErrorUserResponse:
        """Translate :class:`BackendError` to a non-leaking 502.

        Args:
            exc: The raised exception. The ``assert isinstance``
                check is a wiring sanity gate — the application
                binds the handler to :class:`BackendError`, so
                any other type reaching the handler is a bug.

        Returns:
            The 502 :class:`ErrorUserResponse` carrying a generic,
            non-leaking ``detail`` string. The original
            ``exc.status_code`` and ``exc.body`` are NOT echoed
            here — they appear only in the ``log_safe`` event
            emitted by the application layer's handler.
        """
        assert isinstance(exc, BackendError), (
            "BackendErrorTranslation only handles BackendError; "
            f"got {type(exc).__name__}"
        )
        return ErrorUserResponse(
            http_status=502,
            body={
                "detail": (
                    "Upstream database error. Please retry; "
                    "if it persists, contact an operator."
                )
            },
        )


# Backward-compat alias — callers that import InsForgeErrorTranslation
# from this module keep working.
InsForgeErrorTranslation = BackendErrorTranslation


def get_insforge_error_handler_port() -> ErrorTranslationPort:
    """Return the production :class:`ErrorTranslationPort` for the global handler.

    The adapter is stateless — there is no per-request state to
    yield — so the function returns a module-level singleton
    rather than a generator.
    """
    return _INSFORGE_ERROR_HANDLER_PORT


_INSFORGE_ERROR_HANDLER_PORT: ErrorTranslationPort = BackendErrorTranslation()


__all__ = ["get_insforge_error_handler_port"]
