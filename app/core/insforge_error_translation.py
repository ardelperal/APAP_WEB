"""Translate InsForge transport-layer errors to Protocol-level errors.

Lives in its own module so :mod:`app.core.insforge` can stay under the
700-line module-size budget (AGENTS.md rule 21) while still owning the
``execute_sql`` translation call site.

The translator is intentionally narrow: only the 409 unique-key
envelope is mapped to :class:`~app.core.data_access.DuplicateKeyError`
(``UniqueViolation`` for the canonical Postgres SQLSTATE ``23505``).
Every other transport failure surfaces as the original
:class:`~app.core.insforge.InsForgeError` so the generic exception
handler in :mod:`app.main` turns any unhandled error into a
non-leaking 502 (§32.P4 contract preserved after the InsForge
error-handler slice removal in issue #662).
"""

from __future__ import annotations

from typing import Any

from app.core.data_access import (
    DataAccessError,
    DuplicateKeyError,
    InsForgeError,
    UniqueViolationError,
)

# Body-shape markers that signal a Postgres unique-key violation when the
# upstream InsForge gateway wraps the SQLSTATE in a plain JSON envelope.
_DUPLICATE_KEY_BODY_HINTS = ("duplicate", "unique")

#: HTTP 409 Conflict — the only status this translator inspects; every
#: other status flows through :class:`InsForgeError` unchanged. Named
#: constant instead of a magic literal so PLR2004 doesn't flag every
#: comparison.
HTTP_STATUS_CONFLICT = 409


def _classify_409_body(body: Any) -> tuple[str | None, str | None]:
    """Inspect a 409 body and decide whether it signals a unique-key violation.

    InsForge's gateway returns one of two envelope shapes for a Postgres
    ``23505`` unique-violation:

    1. ``{"code": "23505", "message": "duplicate key ..."}`` — the SQLSTATE
       is in the ``code`` field (the documented PostgREST shape).
    2. ``{"message": "duplicate key value violates unique constraint ..."}``
       — only the message hints at the violation.

    Returns ``(sqlstate, lowered_message)``:

    - ``sqlstate`` is ``"23505"`` when the body's ``code`` field carries
      the canonical Postgres SQLSTATE, else ``None``.
    - ``lowered_message`` is the lower-cased ``message`` string when it
      mentions ``"duplicate"`` or ``"unique"``, else ``None``. String
      bodies that carry the same hints are normalised through the same
      field so the result shape is uniform.

    Callers combine the two: ``sqlstate == "23505"`` is the authoritative
    signal; ``lowered_message is not None`` is the heuristic fallback when
    the gateway stripped the SQLSTATE.
    """
    if isinstance(body, dict):
        raw_code = body.get("code", "")
        raw_message = body.get("message", "")
    elif isinstance(body, str):
        raw_code = ""
        raw_message = body
    else:
        return (None, None)

    sqlstate: str | None = raw_code if isinstance(raw_code, str) and raw_code == "23505" else None
    lowered_message: str | None = None
    if isinstance(raw_message, str) and raw_message:
        candidate = raw_message.lower()
        if any(hint in candidate for hint in _DUPLICATE_KEY_BODY_HINTS):
            lowered_message = candidate
    return (sqlstate, lowered_message)


def translate_post_error(exc: InsForgeError) -> DataAccessError:
    """Map a transport-layer ``execute_sql`` error to a Protocol-level error.

    Returns a Protocol exception when the 409 body signals a unique-key
    violation (Postgres SQLSTATE ``23505`` or a message containing
    ``"duplicate"`` / ``"unique"``). When the body does NOT signal a
    uniqueness violation, the original :class:`InsForgeError` is
    returned unchanged (still a :class:`DataAccessError` because
    :class:`InsForgeError` inherits from it). The caller is expected to
    ``raise`` the returned value with ``from exc`` so ``__cause__``
    preserves the original traceback when a translation happens.

    Only the 409-status path is translated today; every other status code
    keeps flowing through :class:`InsForgeError` so the generic exception
    handler in :mod:`app.main` turns any unhandled error into a
    non-leaking 502 (§32.P4 contract preserved).
    """
    if exc.status_code != HTTP_STATUS_CONFLICT:
        return exc
    sqlstate, lowered_message = _classify_409_body(exc.body)
    if sqlstate is None and lowered_message is None:
        return exc
    # Prefer the explicit SQLSTATE; the lowered message is the
    # best-effort fallback. Either way, the message on the raised
    # Protocol exception is the lower-cased upstream message so callers
    # that want to inspect it (e.g. to surface a flash) see something
    # stable and case-insensitive.
    detail = lowered_message if lowered_message is not None else "23505"
    if sqlstate == "23505":
        return UniqueViolationError(detail)
    return DuplicateKeyError(detail)
