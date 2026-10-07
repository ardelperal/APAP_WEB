"""Backend-agnostic data-access contracts used by domain services.

This module exposes the :class:`SqlExecutor` Protocol (the surface every
backend client must satisfy) plus the cross-adapter exception types that
domain code may catch without coupling to a specific transport.

Adapter implementation rule
---------------------------

Each adapter (LocalBackend, the legacy Access adapter, ...) implements
:class:`SqlExecutor` AND translates its own transport-level errors into
the Protocol-level exceptions declared here. Domain code in
``app/core/`` and ``app/modules/`` only catches Protocol-level
exceptions; it never inspects ``status_code`` / ``body`` envelopes.

Inheritance note for Phase 1
----------------------------

:class:`BackendError` lives in this module so :class:`DuplicateKeyError`
can inherit from it cleanly — preserving backward compatibility with
the (pre-Phase-1) world where service-layer code catches
``except BackendError`` to inspect 409 bodies for uniqueness
violations. ``DuplicateKeyError`` inherits from both
:class:`DataAccessError` (the universal Protocol base) and
:class:`BackendError` (for backward compatibility during the
incremental migration). When the Legacy Access adapter lands in
Phase 3 the same pattern can be applied: its ``LegacyReaderError``
will inherit from :class:`DataAccessError` only.

§31 (Domain services depend on Protocol abstractions)
§32.P4 (Partial exception handling — fix by catching Protocol exceptions)
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SqlExecutor(Protocol):
    """Minimal SQL execution surface required by domain services."""

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class TransactionalSqlExecutor(SqlExecutor, Protocol):
    """A :class:`SqlExecutor` that can group several statements atomically.

    ``SqlExecutor`` itself stays unchanged (§ adapter implementation rule
    above) so existing test fakes that implement only ``execute_sql`` keep
    type-checking. Services that need multiple round trips to commit or
    roll back together (e.g. the A-02..A-04 adopciones/acogidas/lifecycle/
    chip-cascade flows, issues #914-#916) depend on this Protocol instead.

    Use ``transaction()`` when the atomic unit of work needs more than one
    ``execute_sql`` call — for example a Python loop that inserts several
    rows, or a read that must see writes from an earlier statement in the
    same unit of work. When the atomic unit is expressible as a SINGLE SQL
    statement, prefer a CTE instead: Postgres runs a CTE as one logical
    operation without needing a held-open connection at all, which is
    simpler and does not need this Protocol. See
    ``app/modules/entradas/batch_service.py::commit_batch`` for the CTE
    pattern (batch-staging rows copied into ``entradas`` in one statement).
    """

    def transaction(self) -> AbstractContextManager[SqlExecutor]:
        """Open one atomic unit of work and yield a bound ``SqlExecutor``.

        Implementations open a single connection, yield an executor bound
        to it, COMMIT on clean exit, ROLLBACK and re-raise on any
        exception, and always close the connection. Calling
        ``transaction()`` again on the yielded (bound) executor raises
        :class:`NestedTransactionError` — nesting is not supported, there
        are no savepoints.
        """
        ...


# --- Protocol-level exception hierarchy ---------------------------------
#
# Adapters translate transport-layer errors (HTTP status, ODBC error codes,
# raw bytes from a stale .accdb, etc.) into one of the exceptions below.
# Domain code only catches these — never the transport-layer error.
#
# The base class is intentionally narrow: only "what the domain needs to
# know" (the message and the optional cause). Adapters that need to
# preserve the original transport error keep it as ``__cause__`` via
# ``raise ProtocolError(...) from transport_error``.


class DataAccessError(Exception):
    """Base class for adapter-level errors translated to the Protocol surface.

    Adapters raise subclasses of this type when a transport-layer failure
    has a clear domain meaning. ``__cause__`` is reserved for the original
    transport error so an operator postmortem can still see it in the
    traceback without domain code having to know the transport shape.

    This is the universal Protocol base — the legacy Access adapter (when
    it lands) will subclass this directly, and the LocalBackend adapter's
    transport error (:class:`BackendError`) ALSO inherits from this so a
    future ``except DataAccessError`` clause catches everything at once.
    """


class BackendError(DataAccessError):
    """Raised when the LocalBackend API returns a non-2xx response.

    Lives in this module (rather than :mod:`app.core.local_backend`) so the
    Protocol-level :class:`DuplicateKeyError` can inherit from it
    without a circular import — the LocalBackend adapter translates 409
    uniqueness violations to ``DuplicateKeyError`` for domain code, but
    service-layer code that has not yet migrated to Protocol exceptions
    (Phase 3) keeps catching ``except BackendError`` and ``__cause__``
    preservation continues to work because ``DuplicateKeyError`` is
    ``isinstance``-equivalent to ``BackendError``.

    The class no longer subclasses :class:`RuntimeError` directly — that
    was the case while it lived in :mod:`app.core.local_backend` and is now
    redundant because ``DataAccessError`` is already an ``Exception``
    subclass. A repository-wide grep confirmed nothing depends on
    ``except RuntimeError`` for ``BackendError``.
    """

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"LocalBackend {status_code}: {body!r}")


class DuplicateKeyError(BackendError):
    """Raised when SQL INSERT/UPDATE violates a uniqueness constraint.

    The LocalBackend adapter catches 409 responses whose body carries the
    Postgres ``23505`` SQLSTATE or whose message contains the substring
    ``"duplicate"`` / ``"unique"`` and raises this exception. Domain
    code catches :class:`DuplicateKeyError` (or its more specific
    subclass :class:`UniqueViolation`) without knowing the transport
    envelope shape.

    Backward compatibility: ``DuplicateKeyError`` inherits from
    :class:`BackendError` (via the linear chain ``DataAccessError`` →
    ``BackendError`` → ``DuplicateKeyError``) so the existing
    ``except BackendError`` clauses in service-layer code (translated
    to ``MaterialConflictError`` / ``EntradaConflictError`` / ...) keep
    matching until Phase 3 ports those clauses to
    :class:`DataAccessError` directly.

    The exception's ``str()`` carries the upstream message (lowercased
    for case-insensitive substring matching) so a domain caller that
    wants to inspect the message can do so without re-fetching it from
    the original transport error.

    The ``__init__`` overrides :class:`BackendError`'s transport-shaped
    constructor so callers raise :class:`DuplicateKeyError` (or its
    subclass) with a plain message — no need to pass a fake status
    code or body. ``status_code`` is set to ``409`` (the upstream
    status for any uniqueness violation) and ``body`` is left as
    ``None``; callers that need the original envelope inspect
    ``__cause__`` instead.
    """

    def __init__(self, message: str = "") -> None:
        self.status_code = 409
        # ``body`` is shaped as a single-key ``message`` dict so the
        # legacy ``_is_duplicate_error`` / ``_is_unique_violation``
        # checks in service-layer code (which lower-case ``str(body)``
        # and substring-match ``"duplicate"`` / ``"unique"``) keep
        # working until Phase 3 ports them to Protocol exceptions.
        # Phase 3 drops these checks; ``body`` will then be free to
        # become ``None``.
        self.body = {"message": message or "duplicate key"}
        super(BackendError, self).__init__(message or "duplicate key")


class NestedTransactionError(DataAccessError):
    """Raised when ``transaction()`` is called on an already-bound executor.

    The executor yielded by :meth:`TransactionalSqlExecutor.transaction`
    runs on the single connection the outer transaction opened; there is
    no savepoint support, so nesting is rejected explicitly instead of
    silently starting a second, independent transaction.
    """


class UniqueViolationError(DuplicateKeyError):
    """Postgres SQLSTATE ``23505`` specifically — a unique-constraint violation.

    A subclass of :class:`DuplicateKeyError` so existing
    ``except DuplicateKeyError`` handlers keep working; code that wants
    to differentiate "PK duplicate" from "any uniqueness violation"
    can catch :class:`UniqueViolationError` first.

    The name carries the ``Error`` suffix required by ruff N818 to
    match the rest of the project's exception hierarchy (DataAccessError,
    BackendError, DuplicateKeyError, ...). The shorter
    ``UniqueViolation`` was the Phase 1 task-spec draft; the suffix is
    what survived into the actual implementation.

    Inherits the message-only ``__init__`` from :class:`DuplicateKeyError`;
    callers raise :class:`UniqueViolationError` with the lower-cased
    upstream message and nothing else.
    """
