"""Reverse-apply package (PR6 / M2).

The reverse applier (``migration.apply_reverse.apply_web_to_legacy``)
was a single 1165-line module that exceeded the 700-line budget
(AGENTS.md rule 21). The package split:

- :mod:`migration.reverse_apply.orchestrator` — the public
  ``apply_web_to_legacy`` entry point + the bulk-legacy-snapshot
  read + the per-row loop + the ``sync_state.json`` advance.
- :mod:`migration.reverse_apply.per_row` — the per-row hot path
  (``_reverse_apply_one_row`` + ``_insert_legacy_row`` +
  ``_update_legacy_row``).
- :mod:`migration.reverse_apply.shadow` — preserve-column shadow
  state advance + drift-detection ``needs_review`` recorder.
- :mod:`migration.reverse_apply.lifecycle` — ``LIFECYCLE_REVERSED``
  event emission for changed derived columns.
- :mod:`migration.reverse_apply.lock_context` — advisory lock
  context manager + ``_write_or_check_snapshot`` + path defaults.
- :mod:`migration.reverse_apply.io_helpers` — case-insensitive PK
  matching + JSON hash + web→legacy row mapping + SELECT builder.
- :mod:`migration.reverse_apply.types` — ``_LocalBackendLike`` Protocol
  + ``ReverseApplyError`` exception hierarchy.

Backwards-compat: ``migration.apply_reverse`` is a thin shim that
re-exports the public API (and the private symbols the existing
14 reverse-apply atoms + 5 round-trip atoms import from there).
"""

from __future__ import annotations

from migration.reverse_apply.orchestrator import apply_web_to_legacy
from migration.reverse_apply.types import (
    ReverseApplyError,
    ReverseSyncStateRollbackError,
    _LocalBackendLike,
)

# Closed-vocabulary direction tags — also re-exported from
# ``migration.apply_reverse`` for tests that reach into the shim.
DIRECTION_WEB_TO_LEGACY = "web-to-legacy"
DIRECTION_LEGACY_TO_WEB = "legacy-to-web"

__all__ = [
    "DIRECTION_LEGACY_TO_WEB",
    "DIRECTION_WEB_TO_LEGACY",
    "ReverseApplyError",
    "ReverseSyncStateRollbackError",
    "_LocalBackendLike",
    "apply_web_to_legacy",
]
