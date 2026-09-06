"""InsForge adapter implementing :class:`ErrorTranslationPort`.

The adapter is the ONLY file in the ``insforge_error_handler`` slice
that imports :class:`~app.core.data_access.InsForgeError` (rule §31:
domain depends on Protocol, never on a concrete client). The
application layer imports the :class:`ErrorTranslationPort` Protocol
and never sees this module.

The translation rule:

- Status: 502 Bad Gateway. The upstream transport failed — the
  request never reached a domain-meaningful outcome.
- Body: a generic non-leaking ``detail`` string. The original
  ``status_code`` and ``body`` of the ``InsForgeError`` are NEVER
  echoed to the client; they appear only in ``log_safe`` events
  where operators can see them.

The adapter is stateless and safe to share across requests — the
DI provider
(:func:`app.core.di.insforge_error_handler_di.get_insforge_error_handler_port`)
returns a single module-level singleton.
"""

# Deprecated 2026-09-06: this module is no longer the production
# transport. The Coolify-hosted local backend (LocalPostgresExecutor)
# is the only supported backend as of issue #641 closing the
# self-host umbrella. This file remains so the legacy InsForge-
# touching tests can run in CI; production deploys use the
# SqlExecutor-based adapter (a follow-up slice).



from __future__ import annotations

from app.core.data_access import InsForgeError
from app.core.ports.insforge_error_handler_port import ErrorUserResponse


class InsForgeErrorTranslation:
    """Translation rule for :class:`InsForgeError`.

    Implements :class:`ErrorTranslationPort` for the InsForge
    transport. Holds no state; the FastAPI request is forwarded by
    :func:`app.core.application.insforge_error_handler.register_insforge_error_handler`
    when the registered exception handler fires.
    """

    @property
    def target_exception_type(self) -> type[Exception]:
        """Return :class:`InsForgeError` — the class the global handler binds to.

        The application uses this as the first argument to
        ``@app.exception_handler(...)`` so the handler fires for
        every ``InsForgeError`` (and its subclasses —
        :class:`~app.core.data_access.DuplicateKeyError`,
        :class:`~app.core.data_access.UniqueViolationError`) that
        is not already caught locally by a route.
        """
        return InsForgeError

    def to_user_response(self, exc: BaseException) -> ErrorUserResponse:
        """Translate :class:`InsForgeError` to a non-leaking 502.

        Args:
            exc: The raised exception. The ``assert isinstance``
                check is a wiring sanity gate — the application
                binds the handler to :class:`InsForgeError`, so
                any other type reaching the handler is a bug.

        Returns:
            The 502 :class:`ErrorUserResponse` carrying a generic,
            non-leaking ``detail`` string. The original
            ``exc.status_code`` and ``exc.body`` are NOT echoed
            here — they appear only in the ``log_safe`` event
            emitted by the application layer's handler.
        """
        assert isinstance(exc, InsForgeError), (
            "InsForgeErrorTranslation only handles InsForgeError; "
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


__all__ = ["InsForgeErrorTranslation"]
