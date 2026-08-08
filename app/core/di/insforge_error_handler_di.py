"""FastAPI wiring for the global transport-error handler port.

The :func:`get_insforge_error_handler_port` provider is the seam
between FastAPI's exception-handler registration and the hexagonal
:class:`ErrorTranslationPort` abstraction. Production wires the
:class:`InsForgeErrorTranslation` adapter; tests can substitute
their own adapter by passing a different port directly to
:func:`app.core.application.insforge_error_handler.register_insforge_error_handler`.

Pattern (mirrors :func:`app.core.di.oauth_di.get_oauth_port`):

- The adapter is stateless, so the provider returns a
  module-level singleton rather than a generator — there is no
  per-request state to yield.
- No transport resources are owned by this helper. The lifespan
  owns the :class:`~app.core.insforge.InsForgeClient`; the adapter
  is built once at module load and reused forever.

Rule §31 (domain services depend on Protocol abstractions): the
provider returns the :class:`ErrorTranslationPort` interface, not
the concrete :class:`InsForgeErrorTranslation` adapter. Future
multi-transport deployments would swap adapters here without
touching the application layer.
"""


from __future__ import annotations

from app.core.adapters.insforge.insforge_error_handler_insforge_adapter import (
    InsForgeErrorTranslation,
)
from app.core.ports.insforge_error_handler_port import ErrorTranslationPort


def get_insforge_error_handler_port() -> ErrorTranslationPort:
    """Return the production :class:`ErrorTranslationPort` for the global handler.

    The adapter is stateless — there is no per-request state to
    yield — so the function returns a module-level singleton
    rather than a generator.
    """
    return _INSFORGE_ERROR_HANDLER_PORT


_INSFORGE_ERROR_HANDLER_PORT: ErrorTranslationPort = InsForgeErrorTranslation()


__all__ = ["get_insforge_error_handler_port"]
