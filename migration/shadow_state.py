"""Shadow state repository for ``web_only_feature_shadow``.

PR 1 of ``web-only-feature-preservation``. The repository is the
CRUD-only sibling of the future derivation engine and semantic-events
pipeline: it stores per-row, per-column values that the legacy DB does
NOT own, so they survive a round-trip web→legacy→web without being
silently overwritten.

Architecture (design.md §3):

- One row per ``(table_name, legacy_pk, web_column)`` triple.
- ``strategy`` ∈ {``preserve``, ``fixed``, ``derived``} — read from the
  matching ``ColumnMapping.web_only_strategy``; the YAML is the source
  of truth for the strategy, this table only records the resulting
  state.
- ``reconciliation_status`` ∈ {``matched``, ``divergent``, ``needs_review``,
  ``pending``, ``migrated``} — set by the hook (PR 4) and the operator
  via the CLI (PR 5).
- The UNIQUE composite index on ``(table_name, legacy_pk, web_column)``
  makes ``lookup()`` an O(1) index scan (spec.md REQ-O(1) lookup).

The repository is a thin wrapper over ``InsForgeClient.execute_sql``
(``/api/database/advance/rawsql`` via PostgREST). The same testing
pattern as ``web_reader.load_web_snapshot`` applies: tests inject a
mock transport and assert the SQL emitted. PR 5 will introduce an
``apap-migrate reconcile`` CLI that drives this repository.

This module DOES NOT own the derivation logic — that lives in
``app/core.migration.derivation`` (PR 2). It only persists the
results of that derivation, plus the operator's reconciliation
choices.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.insforge import InsForgeClient

# --- Schema (T1.4) --------------------------------------------------------
#
# Exported so callers (and tests) can introspect / re-run the DDL. The
# UNIQUE composite index is the contract for O(1) lookup; do not rename
# its columns without updating spec.md and the legacy_reader wiring.

SHADOW_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS web_only_feature_shadow (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name TEXT NOT NULL,
    legacy_pk TEXT NOT NULL,
    web_pk UUID,
    web_column TEXT NOT NULL,
    preserved_value JSONB,
    strategy TEXT NOT NULL CHECK (strategy IN ('preserve', 'fixed', 'derived')),
    last_legacy_snapshot_at TIMESTAMPTZ,
    last_web_edit_at TIMESTAMPTZ,
    last_reconciled_at TIMESTAMPTZ,
    reconciliation_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (reconciliation_status IN
               ('matched', 'divergent', 'needs_review', 'pending', 'migrated')),
    review_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    derived_value JSONB,
    derived_at TIMESTAMPTZ,
    UNIQUE (table_name, legacy_pk, web_column)
)
"""

# Index optimised for the most common operator query — the ``list needs
# review`` dashboard — partial index on reconciliation_status='needs_review'.
# (The UNIQUE index above already covers point lookups; this index only
# exists to make bulk listings cheap. Safe to apply on a fresh install.)
SHADOW_NEEDS_REVIEW_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_shadow_needs_review
    ON web_only_feature_shadow (last_legacy_snapshot_at)
    WHERE reconciliation_status = 'needs_review'
"""


class ShadowStateRepository:
    """CRUD for ``web_only_feature_shadow``.

    Methods are intentionally narrow: the applier and the CLI are the
    only callers, and they need exactly the four operations
    ``upsert / lookup / list_needs_review / update_reconciliation_status``
    (PR 1) plus ``delete`` (mentioned in tasks.md 1.8 for cleanup).

    The repository NEVER writes a status that disagrees with the
    derivation engine's output; that authority lives in
    ``migration.derivation`` (PR 2). The CLI (PR 5) is the only
    path that flips ``needs_review`` → ``matched`` / ``divergent`` after
    operator intervention.
    """

    def __init__(self, client: InsForgeClient) -> None:
        self._client = client

    # --- write paths ----------------------------------------------------

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
    ) -> None:
        """Insert-or-merge a shadow row keyed by ``(table, pk, column)``.

        Uses ``ON CONFLICT ... DO UPDATE`` so a re-apply of the same
        row overwrites ``preserved_value`` and the timestamps without
        raising on duplicate. The UNIQUE composite index is the merge
        target; do NOT change ``ON CONFLICT`` columns without bumping
        the index definition in ``SHADOW_TABLE_SQL``.
        """
        sql = (
            "INSERT INTO web_only_feature_shadow ("
            "table_name, legacy_pk, web_pk, web_column, preserved_value,"
            " strategy, last_legacy_snapshot_at, reconciliation_status"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (table_name, legacy_pk, web_column) DO UPDATE SET "
            "web_pk = EXCLUDED.web_pk, "
            "preserved_value = EXCLUDED.preserved_value, "
            "strategy = EXCLUDED.strategy, "
            "last_legacy_snapshot_at = EXCLUDED.last_legacy_snapshot_at, "
            "reconciliation_status = EXCLUDED.reconciliation_status"
        )
        self._client.execute_sql(
            sql,
            [
                table_name,
                legacy_pk,
                web_pk,
                web_column,
                _to_jsonb(preserved_value),
                strategy,
                last_legacy_snapshot_at.isoformat() if last_legacy_snapshot_at else None,
                reconciliation_status,
            ],
        )

    def update_reconciliation_status(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
        status: str,
        review_reasons: list[str] | None = None,
        last_reconciled_at: datetime | None = None,
    ) -> None:
        """Flip the reconciliation_status of one shadow row.

        Scoped by the unique key so a typo never bleeds across rows.
        Sets ``last_reconciled_at`` to the supplied timestamp (or NULL)
        and replaces ``review_reasons`` with the supplied list (default
        empty).
        """
        sql = (
            "UPDATE web_only_feature_shadow "
            "SET reconciliation_status = %s, "
            "    review_reasons = %s, "
            "    last_reconciled_at = %s "
            "WHERE table_name = %s AND legacy_pk = %s AND web_column = %s"
        )
        self._client.execute_sql(
            sql,
            [
                status,
                _to_jsonb(review_reasons if review_reasons is not None else []),
                last_reconciled_at.isoformat() if last_reconciled_at else None,
                table_name,
                legacy_pk,
                web_column,
            ],
        )

    def update_derived_value(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
        derived_value: Any,
    ) -> None:
        """Persist the latest ``derived_value`` on a shadow row.

        PR 5 follow-up (web-only-feature-preservation): the CLI's
        ``--interactive`` ``(b) accept derived`` path pre-fills the
        operator's prompt with the stored ``derived_value`` so the
        operator does not have to retype the derivation result. The
        applier hook (``reconcile._reconcile_derived``) calls this
        after the derivation engine runs and before flipping the
        status to ``needs_review``.

        Scoped by the unique key so a typo never bleeds across rows.
        """
        sql = (
            "UPDATE web_only_feature_shadow "
            "SET derived_value = %s "
            "WHERE table_name = %s AND legacy_pk = %s AND web_column = %s"
        )
        self._client.execute_sql(
            sql,
            [
                _to_jsonb(derived_value),
                table_name,
                legacy_pk,
                web_column,
            ],
        )

    def update_derived_at(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
        derived_at: datetime | None,
    ) -> None:
        """Persist the timestamp of the latest derivation on a shadow row.

        PR 5 follow-up: companion to :meth:`update_derived_value`. The
        ``derived_at`` column lets the operator see "when did we last
        run the derivation engine on this column" — useful for cases
        where a legacy change happened long ago and the operator wants
        to know how stale the derived value is.
        """
        sql = (
            "UPDATE web_only_feature_shadow "
            "SET derived_at = %s "
            "WHERE table_name = %s AND legacy_pk = %s AND web_column = %s"
        )
        self._client.execute_sql(
            sql,
            [
                derived_at.isoformat() if derived_at else None,
                table_name,
                legacy_pk,
                web_column,
            ],
        )

    def delete(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
    ) -> None:
        """Remove a single shadow row, scoped by the unique key.

        Used by the cleanup job (out of scope for PR 1) and by the CLI
        ``reconcile --reset`` flag in PR 5.
        """
        sql = (
            "DELETE FROM web_only_feature_shadow "
            "WHERE table_name = %s AND legacy_pk = %s AND web_column = %s"
        )
        self._client.execute_sql(sql, [table_name, legacy_pk, web_column])

    # --- read paths -----------------------------------------------------

    def lookup(
        self,
        *,
        table_name: str,
        legacy_pk: str,
        web_column: str,
    ) -> dict[str, Any] | None:
        """Return the shadow row, or ``None`` if no row exists.

        The query filters by the UNIQUE composite index columns, so the
        planner performs an index lookup (O(1) amortised) rather than a
        seq scan (spec.md REQ-O(1) lookup).
        """
        sql = (
            "SELECT id, table_name, legacy_pk, web_pk, web_column, "
            "preserved_value, strategy, last_legacy_snapshot_at, "
            "last_web_edit_at, last_reconciled_at, reconciliation_status, "
            "review_reasons "
            "FROM web_only_feature_shadow "
            "WHERE table_name = %s AND legacy_pk = %s AND web_column = %s"
        )
        rows = self._client.execute_sql(sql, [table_name, legacy_pk, web_column])
        if not rows:
            return None
        return rows[0]

    def list_needs_review(
        self,
        *,
        table_name: str | None = None,
        since: str | None = None,
        origin_direction: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return shadow rows with ``reconciliation_status='needs_review'``.

        ``table_name`` and ``since`` are optional filters wired through
        the CLI (``--table``, ``--since``). ``since`` is an ISO-8601
        timestamp string parsed client-side and compared against
        ``last_legacy_snapshot_at`` so the operator can scope to "new
        divergences in the last run".

        ``origin_direction`` is the PR5 filter: ``"legacy-to-web"`` or
        ``"web-to-legacy"``. ``None`` (the default) returns rows from
        BOTH directions. PR5 stamps every row with an
        ``origin_direction`` field (default ``"legacy-to-web"`` since
        the forward path is the only producer until PR6); the CLI
        applies the filter on the stamped field so the flag is
        decoupled from the underlying SQL column. PR6 will start
        stamping ``"web-to-legacy"`` on the rows it produces — the
        CLI filter already understands that value.
        """
        clauses = ["reconciliation_status = 'needs_review'"]
        params: list[Any] = []
        if table_name is not None:
            clauses.append("table_name = %s")
            params.append(table_name)
        if since is not None:
            clauses.append("last_legacy_snapshot_at >= %s")
            params.append(since)
        where = " AND ".join(clauses)
        sql = (
            "SELECT id, table_name, legacy_pk, web_pk, web_column, "
            "preserved_value, strategy, last_legacy_snapshot_at, "
            "last_web_edit_at, last_reconciled_at, reconciliation_status, "
            "review_reasons "
            "FROM web_only_feature_shadow "
            f"WHERE {where} "
            "ORDER BY last_legacy_snapshot_at ASC NULLS LAST"
        )
        rows = list(self._client.execute_sql(sql, params))
        # Stamp ``origin_direction`` on every row so the CLI filter
        # has a uniform surface. PR5: the forward applier is the only
        # producer of needs_review rows; the shadow row itself does
        # not carry an ``origin_direction`` column yet (that lands in
        # PR6 when reverse-path rows start arriving). The default
        # "legacy-to-web" keeps the PR5 listing complete; the CLI
        # filter narrows by the stamped value.
        for row in rows:
            row.setdefault("origin_direction", "legacy-to-web")
        if origin_direction is not None:
            rows = [r for r in rows if r.get("origin_direction") == origin_direction]
        return rows

    # --- DDL helpers ----------------------------------------------------

    def ensure_table(self) -> None:
        """Idempotently create the shadow table and the needs-review index.

        Call once at app startup (or from the bootstrap path). Safe to
        run repeatedly; both statements are IF NOT EXISTS.
        """
        self._client.execute_sql(SHADOW_TABLE_SQL)
        self._client.execute_sql(SHADOW_NEEDS_REVIEW_INDEX_SQL)


# --- helpers --------------------------------------------------------------


def _to_jsonb(value: Any) -> str:
    """Serialise a Python value into a JSON string accepted by PostgREST.

    ``None`` becomes JSON ``null`` (which Postgres casts to a JSONB null
    literal). Lists and dicts serialise normally; primitives become
    JSON literals. The result is a string because PostgREST expects a
    JSON-encoded value when the column type is ``jsonb`` and the
    InsForgeClient's param-binding does not do type-aware packing.
    """
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


__all__ = [
    "SHADOW_NEEDS_REVIEW_INDEX_SQL",
    "SHADOW_TABLE_SQL",
    "ShadowStateRepository",
]
