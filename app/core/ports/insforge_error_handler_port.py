"""Hexagonal port for the global transport-error handler.

The :class:`ErrorTranslationPort` is the abstract surface the application
layer depends on. The InsForge adapter implements it for
:class:`~app.core.data_access.InsForgeError`; future adapters (the
legacy Access adapter, a future Redis-cache adapter, ...) would
implement the same Protocol against their own exception types and
register alongside.

The split between :class:`TranslatableError` (the exception shape)
and :class:`ErrorTranslationPort` (the translation rule) keeps the
Protocol boundary honest: the application layer only needs to know
the abstract exception attributes (``status_code``, ``message``)
and the abstract translation contract (``to_user_response``). The
adapter owns the wiring between a concrete exception class and the
HTTP response shape.

Hexagonal taxonomy:

- Domain   :class:`~app.core.domain.*` — pure entities and rules,
  no I/O. The transport-error domain is intentionally left as a
  Protocol-only surface here: a full domain package would only
  host an error hierarchy, not a translation rule.
- Port    (this module) — abstract surface.
- Application :mod:`app.core.application.insforge_error_handler` —
  use case (the global handler registration).
- Adapter :mod:`app.core.adapters.insforge.insforge_error_handler_insforge_adapter`
  — InsForge impl (the only file in this slice that imports
  :class:`InsForgeError`).
- DI      :mod:`app.core.di.insforge_error_handler_di` — wiring.

Rule §31 (domain services depend on Protocol abstractions): every
type and method here is transport-free. No import from
:mod:`app.core.insforge` (the transport client), nor from
:mod:`app.core.data_access` (the transport-shaped exception
class). The adapter owns both.
"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ErrorUserResponse:
    """The HTTP response shape an adapter returns for an unhandled transport error.

    The application layer wraps the values in a
    :class:`fastapi.responses.JSONResponse`. Adapters do not import
    FastAPI types — the dataclass is the contract.

    Attributes:
        http_status: The HTTP status code to return. The InsForge
            adapter returns ``502`` (Bad Gateway) because the
            transport failure means the request never reached a
            domain-meaningful outcome.
        body: The JSON body to return. Kept as a free-form
            ``dict[str, Any]`` so adapters can include arbitrary
            keys (``detail``, ``code``, ...) without coupling the
            Protocol to one body shape. The InsForge adapter
            returns ``{"detail": "..."}`` — non-leaking, no
            upstream status echoed to the client.
    """

    http_status: int
    body: dict[str, Any]


@runtime_checkable
class TranslatableError(Protocol):
    """The minimal attribute surface an exception must expose to be translatable.

    Any exception class that satisfies these two attributes can be
    the target of an :class:`ErrorTranslationPort` implementation.
    Marked :func:`typing.runtime_checkable` so the application
    layer can ``isinstance(exc, TranslatableError)`` to safely read
    ``status_code`` without an :class:`AttributeError` when an
    unrelated exception somehow reaches the handler.

    Attributes:
        status_code: The original transport status code (e.g. the
            InsForge HTTP status). ``None`` when the exception is
            not a transport-status wrapper.
        message: A human-readable description used in structured
            log events. Operators see it; clients do not (the
            non-leaking ``detail`` lives in
            :class:`ErrorUserResponse.body` instead).
    """

    status_code: int | None
    message: str


class ErrorTranslationPort(Protocol):
    """Adapter-specific translation rule for one transport error type.

    An adapter (e.g. InsForge) implements this Protocol to declare
    two things:

    1. WHICH exception class to register the global FastAPI handler
       against (``target_exception_type``).
    2. HOW to translate a raised instance into an HTTP response
       (``to_user_response``).

    The application layer reads ``target_exception_type`` to bind
    ``@app.exception_handler(...)`` and calls ``to_user_response``
    to produce the JSON body. The application never inspects the
    concrete exception class — the Protocol boundary is what keeps
    rule §31 (domain depends on Protocol abstractions) honest.

    Implementations:

    - :class:`~app.core.adapters.insforge.insforge_error_handler_insforge_adapterBackendErrorTranslation`
      — production adapter for :class:`~app.core.data_access.BackendError`.
    """

    @property
    def target_exception_type(self) -> type[Exception]:
        """The exception class to bind the global FastAPI handler against.

        The application passes this to ``@app.exception_handler(...)``
        so the handler fires only for instances of the returned
        class. A second adapter that translates a different
        exception would register a separate handler with its own
        ``target_exception_type`` — FastAPI supports multiple
        ``@app.exception_handler`` decorators on the same app.

        The return type is ``type[Exception]`` (not
        ``type[BaseException]``) because FastAPI's
        ``exception_handler`` decorator accepts only
        ``int | type[Exception]`` — handlers fire for ``Exception``
        subclasses and their descendants, not for
        ``BaseException`` subclasses like ``KeyboardInterrupt``.
        """
        ...

    def to_user_response(self, exc: BaseException) -> ErrorUserResponse:
        """Translate the raised exception into an HTTP response.

        Args:
            exc: The exception that reached the global handler.
                Implementations may ``assert isinstance(exc,
                self.target_exception_type)`` to surface adapter /
                wiring mismatches early — the application layer
                binds the handler to ``target_exception_type`` so
                any other type reaching the handler is a bug.

        Returns:
            The :class:`ErrorUserResponse` carrying the HTTP status
            and JSON body. The application wraps it in a
            :class:`fastapi.responses.JSONResponse` — adapters do
            not import FastAPI types.
        """
        ...


__all__ = [
    "ErrorTranslationPort",
    "ErrorUserResponse",
    "TranslatableError",
]
