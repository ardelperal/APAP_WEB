"""Thin backward-compat shim for the reverse applier.

PR6 / M2's reverse applier lived here as a 1165-line module. The
implementation now lives in :mod:`migration.reverse_apply` (split
into 7 sub-modules to satisfy the 700-line module-size budget;
AGENTS.md rule 21 ratchet).

This shim re-exports:

- The public ``apply_web_to_legacy`` orchestrator.
- The closed-vocabulary direction tags (``DIRECTION_WEB_TO_LEGACY``
  / ``DIRECTION_LEGACY_TO_WEB``).
- The typed-exception hierarchy (``ReverseApplyError`` /
  ``ReverseSyncStateRollbackError``).
- The ``_InsForgeLike`` structural type.
- The private helpers the 14 ``test_reverse_apply.py`` atoms +
  5 ``test_round_trip.py`` atoms reach into via this module path:

  - ``_reverse_apply_one_row`` (per-row hot path)
  - ``_emit_reversed_lifecycle_events_for_changed_derived``
    (lifecycle event emitter)
  - ``_advance_preserve_shadow_state`` (preserve-column router)
  - ``_record_drift_needs_review`` (drift detector)
  - ``_case_insensitive_get`` (PK matching helper)
  - ``_web_to_legacy_row`` (column mapper)
  - ``_compute_source_hash`` (audit-log hash)
  - ``_LockContext`` (advisory lock context)
  - ``_write_or_check_snapshot`` (snapshot writer)
  - ``_skip_bootstrap_for_reverse`` (M0 no-op)

The shim is the module-attribute-lookup surface that PR6's
monkeypatchability discipline relies on: tests do
``monkeypatch.setattr(apply_reverse_mod, "_emit_...", fake)``,
then the orchestrator (and per-row) calls the patched callable
through ``migration.apply_reverse.<name>``.
"""

from __future__ import annotations

from migration.reverse_apply.io_helpers import (
    _case_insensitive_get,
    _compute_source_hash,
    _web_to_legacy_row,
)
from migration.reverse_apply.lifecycle import (
    _emit_reversed_lifecycle_events_for_changed_derived,
)
from migration.reverse_apply.lock_context import (
    _LockContext,
    _skip_bootstrap_for_reverse,
    _write_or_check_snapshot,
)
from migration.reverse_apply.orchestrator import apply_web_to_legacy
from migration.reverse_apply.per_row import _reverse_apply_one_row
from migration.reverse_apply.shadow import (
    _advance_preserve_shadow_state,
    _record_drift_needs_review,
)
from migration.reverse_apply.types import (
    ReverseApplyError,
    ReverseSyncStateRollbackError,
    _InsForgeLike,
)

# Closed-vocabulary direction tags.
DIRECTION_WEB_TO_LEGACY = "web-to-legacy"
DIRECTION_LEGACY_TO_WEB = "legacy-to-web"

__all__ = [
    "DIRECTION_LEGACY_TO_WEB",
    "DIRECTION_WEB_TO_LEGACY",
    "ReverseApplyError",
    "ReverseSyncStateRollbackError",
    "_InsForgeLike",
    "_LockContext",
    "_advance_preserve_shadow_state",
    "_case_insensitive_get",
    "_compute_source_hash",
    "_emit_reversed_lifecycle_events_for_changed_derived",
    "_record_drift_needs_review",
    "_reverse_apply_one_row",
    "_skip_bootstrap_for_reverse",
    "_web_to_legacy_row",
    "_write_or_check_snapshot",
    "apply_web_to_legacy",
]
