"""DNI collision routing for web-only and reverse-path scopes (PR5/M1).

The PR5 spec (``live-migration-pii-controls/spec.md``) re-scopes
the DNI collision contract: forward legacy→web apply NEVER
produces a DNI collision (legacy has no DNI column — verified by
Dysflow ``get_schema`` 2026-07-11). Collisions arise only in two
scopes:

1. **Web-only manual collisions** — an operator manually INSERTs
   two web ``voluntarios`` rows with the same DNI. The second
   INSERT fails on ``voluntarios_dni_key``; the applier or web UI
   catches the rejection and routes the rejected row to
   ``web_only_feature_shadow`` with
   ``reconciliation_status="needs_review"`` and
   ``review_reasons=["dni_collision"]``.

2. **Reverse-path (web→legacy) collisions** — the reverse applier
   (PR6 scope) tries to push a web ``DNI`` back to legacy, but
   legacy has no column to receive it. The shadow table records
   the row with the same routing; the counter increments by 1.

In both scopes the first INSERT wins; subsequent collisions do NOT
overwrite. Counts only (never values) appear in
``MigrationReport.collisions["dni_collisions"]`` (per-table counter).

This module exposes two surfaces:

- :func:`record_dni_collision` — the per-row router. Callers
  (applier / web UI / future PR6 reverse applier) invoke it once
  per collision with the rejected row's natural key + web UUID.
- :class:`DniCollisionCounter` — a tiny mutable counter that the
  apply pipeline bumps once per collision and reads at the end
  to populate ``MigrationReport.collisions``. The counter starts
  at 0 in the forward direction (the helper is never called there).

Why this lives in its own module: the spec calls out the
collision policy as a deterministic + auditable invariant, and
the helper is consumed by three call sites (forward apply,
reverse apply, web UI form). Co-locating the constant
``DNI_COLLISION_REVIEW_REASON`` with the routing logic keeps the
closed vocabulary single-sourced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

# Categorical reason tag stashed on ``web_only_feature_shadow.review_reasons``.
# Kept short + searchable so the operator can grep the migration
# reports and the ``needs_review`` listing. Mirrors the
# ``REVIEW_REASON_WEB_MANUAL_OVERRIDE`` constant in
# ``migration.reconcile`` (different scope, same naming convention).
DNI_COLLISION_REVIEW_REASON = "dni_collision"


# --- protocol surface ----------------------------------------------------


class _ShadowStateWriter(Protocol):
    """Minimal surface required by :func:`record_dni_collision`.

    Mirrors the two methods :func:`record_dni_collision` calls on
    the production ``ShadowStateRepository``:

    - ``upsert`` writes the shadow row with the canonical metadata
      (preserved_value=None, strategy="preserve",
      reconciliation_status="needs_review", ``origin_direction``
      stamped from the caller's ``direction``).
    - ``update_reconciliation_status`` stamps the categorical
      ``review_reasons`` (a separate write because the closed
      ``upsert`` signature does not carry ``review_reasons``).

    Defined as a Protocol so callers can pass either the concrete
    ``ShadowStateRepository`` (production) or a fake (tests).
    """

    def upsert(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_pk: str | None,
        web_column: str,
        preserved_value: Any,
        strategy: str,
        last_legacy_snapshot_at: datetime | None = None,
        reconciliation_status: str = "pending",
        origin_direction: str = "legacy-to-web",
    ) -> None: ...

    def update_reconciliation_status(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
        status: str,
        review_reasons: list[str] | None = None,
        last_reconciled_at: datetime | None = None,
    ) -> None: ...


# --- public API ----------------------------------------------------------


def record_dni_collision(
    *,
    shadow_state: _ShadowStateWriter,
    table_name: str,
    legacy_pk: str,
    web_pk: str | None,
    web_column: str = "dni",
    direction: Literal["web-only", "web-to-legacy"],
    now: datetime | None = None,
) -> None:
    """Route a single DNI collision to ``web_only_feature_shadow``.

    Two scopes can produce a DNI collision:

    - ``direction="web-only"`` — operator manually INSERTed a second
      web ``voluntarios`` row with the same DNI; the UNIQUE
      constraint rejected it. Caller is the applier / web UI that
      caught the rejection. The shadow row is stamped with
      ``origin_direction="web-only"`` so the operator can distinguish
      it from forward/reverse-path collisions via
      ``--filter-direction web-only`` (the closed vocabulary
      accepts the three scopes).
    - ``direction="web-to-legacy"`` — the reverse applier (PR6)
      tried to push a web DNI back to legacy; legacy has no
      column to receive it. Caller is the PR6 reverse pipeline.
      The shadow row is stamped with
      ``origin_direction="web-to-legacy"`` (matches the closed
      ``MigrationReport.collisions`` vocabulary).

    Both scopes produce the same shadow-row shape (the spec's
    "first INSERT wins" rule). The function is intentionally narrow:
    it routes ONE row. Callers loop over their collision list and
    bump :class:`DniCollisionCounter` after each call.

    Args:
        shadow_state: writer that persists the shadow row. Must
            expose ``upsert`` + ``update_reconciliation_status``
            (see the ``_ShadowStateWriter`` protocol).
        table_name: web table the collision was on (e.g.
            ``"voluntarios"``).
        legacy_pk: the rejected row's identifier. For
            ``direction="web-only"`` this is the new web row's
            UUID (no legacy source); for
            ``direction="web-to-legacy"`` this is the legacy
            natural key.
        web_pk: the rejected row's web UUID (``None`` when the
            INSERT was rejected pre-INSERT — the web row never
            got created).
        web_column: PII column name; defaults to ``"dni"``. Kept
            as a parameter so future collisions on other PII
            columns (e.g. ``email`` if a UNIQUE constraint is
            added) reuse the same routing.
        direction: collision scope — ``"web-only"`` or
            ``"web-to-legacy"``. Persisted on the shadow row
            verbatim as ``origin_direction`` (the CHECK constraint
            in ``SHADOW_TABLE_SQL`` enforces the closed three-value
            vocabulary at the column level).
        now: UTC timestamp stamped on the shadow row
            (``last_legacy_snapshot_at`` and
            ``last_reconciled_at``). Defaults to
            ``datetime.now(UTC)``; tests pass a fixed value for
            determinism.

    Notes:
        The collision has no value to preserve (the row was
        rejected before the applier could write it), so
        ``preserved_value=None`` and ``strategy="preserve"`` (DNI
        is web-only shadow by ``migration/mappings/voluntario.yaml``).
        The operator resolves the row via
        ``apap-migrate reconcile --interactive`` — the same path
        used for any other ``needs_review`` case.
    """
    snapshot_at = now if now is not None else datetime.now(UTC)
    # ``origin_direction`` is stamped with the caller's ``direction``
    # value verbatim — the CHECK constraint on the column enforces
    # the closed three-value vocabulary
    # (``legacy-to-web`` / ``web-to-legacy`` / ``web-only``).
    shadow_state.upsert(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_pk=web_pk,
        web_column=web_column,
        preserved_value=None,
        strategy="preserve",
        last_legacy_snapshot_at=snapshot_at,
        reconciliation_status="needs_review",
        origin_direction=direction,
    )
    # The closed ``upsert`` signature does not carry
    # ``review_reasons``; a follow-up write stamps the categorical
    # tag. The two writes are not transactional at the row level
    # (Postgres serialisable isolation would handle that); the
    # row-level UNIQUE composite index keeps the second write
    # idempotent.
    shadow_state.update_reconciliation_status(
        table_name=table_name,
        legacy_pk=legacy_pk,
        web_column=web_column,
        status="needs_review",
        review_reasons=[DNI_COLLISION_REVIEW_REASON],
        last_reconciled_at=snapshot_at,
    )


class DniCollisionCounter:
    """Mutable counter for the migration report.

    ``MigrationReport`` is ``frozen=True`` (per
    ``migration/reporting.py``); counters are computed during the
    apply pipeline and attached to the report at the end. This
    helper lets the apply path bump the counter as it goes and
    read the final value when building the report.

    Usage::

        counter = DniCollisionCounter()
        for rejected_row in collisions:
            record_dni_collision(
                shadow_state=shadow,
                table_name="voluntarios",
                ...
            )
            counter.bump()
        # At the end of the apply:
        report.collisions.setdefault("voluntarios", {})["dni_collisions"] = counter.value

    The counter is intentionally process-local (no thread safety)
    because the apply pipeline is single-threaded; a future
    parallel applier would need to revisit this.
    """

    def __init__(self) -> None:
        self._value: int = 0

    @property
    def value(self) -> int:
        return self._value

    def bump(self) -> int:
        """Increment the counter by 1 and return the new value."""
        self._value += 1
        return self._value


__all__ = [
    "DNI_COLLISION_REVIEW_REASON",
    "DniCollisionCounter",
    "record_dni_collision",
]
