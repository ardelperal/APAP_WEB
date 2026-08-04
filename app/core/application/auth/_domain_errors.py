"""Domain errors raised by the auth adapter and translated by use cases.

These live in the application layer because they are domain concepts
("user not found", "last developer would be deactivated") rather
than transport concerns. The adapter raises them; the use cases
catch them and re-raise as ``ValueError`` to preserve the
pre-Phase-1 ``app.core.auth`` contract (the legacy callers catch
``ValueError``).

``DomainError`` is the universal base so a future
``except DomainError`` clause (e.g. in a global exception handler)
can catch all auth-domain failures without depending on a specific
transport or the legacy ``app.core.auth`` shim.
"""
from __future__ import annotations


class DomainError(Exception):
    """Universal base for auth-slice domain errors.

    Application-layer code (the use cases) translates each subclass
    into the ``ValueError`` the legacy ``app.core.auth`` shim
    contract promises. A future Phase 3 cleanup can collapse the
    use-case ``try/except`` to ``except DomainError`` once the
    callers migrate.
    """


class UserNotFoundError(DomainError):
    """The supplied user id does not match any row in ``usuarios_autorizados``."""


class LastActiveDeveloperError(DomainError):
    """The deactivation would leave the system without an active developer.

    Translates to ``ValueError("cannot deactivate the last active
    developer")`` in the use case.
    """


class UnexpectedDeactivateError(DomainError):
    """Defensive: the conditional UPDATE returned zero rows but the
    subsequent disambiguation did not classify the cause.

    In theory the conditional UPDATE + ``_has_other_active_developers``
    + ``get_user_by_id`` chain covers every zero-row outcome. In
    practice, the catch-all is here so a future refactor that drops
    one of the disambiguation branches does not silently deactivate
    nothing.
    """
