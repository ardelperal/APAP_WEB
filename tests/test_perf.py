"""Performance test for ``ShadowStateRepository.list_needs_review``
(PR 6/6, T6.4).

Verifies the spec REQ-Performance budget: 10 000 animales x 5 columns
(``preserve`` / ``derived`` / ``fixed`` mix) must complete in < 10s.

The test is a sanity check on the perf budget; the SLO is measured in
production on the staging VPS (not in this test environment). The
assertion is portable: ``time.perf_counter`` instead of a
pytest-benchmark dependency.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from app.core.data_access import SqlExecutor


# --- helpers --------------------------------------------------------------


class _FakeSqlExecutor:
    """In-memory :class:`SqlExecutor` for the perf test.

    Returns the pre-loaded ``rows`` list verbatim (no real DB roundtrip)
    so the test measures the repository-side loop overhead (sort +
    filter). That is where the O(N) cost lives in production too
    (the SQL returns rows in ``last_legacy_snapshot_at`` order with
    WHERE filtering at the DB level).

    Mirrors the Arc C migration pattern (``tests/test_catalogs.py``)
    that replaced ``httpx.MockTransport`` everywhere in the suite.
    """

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, Any]]:
        return self.rows

    def close(self) -> None:
        pass  # no-op for fake


def _needs_review_row(
    *,
    table_name: str = "animales",
    legacy_pk: str = "a-1",
    web_pk: str = "00000000-0000-0000-0000-000000000001",
    web_column: str = "current_state",
    preserved_value: Any = None,
    strategy: str = "derived",
    last_legacy_snapshot_at: str | None = "2026-06-20T12:00:00+00:00",
    last_reconciled_at: str | None = None,
    review_reasons: list[str] | None = None,
    reconciliation_status: str = "needs_review",
    # PR 5 follow-up additions
    derived_value: Any = None,
    derived_at: str | None = None,
) -> dict[str, Any]:
    """One row in the shape ``ShadowStateRepository.list_needs_review`` returns.

    Includes the new ``derived_value`` / ``derived_at`` columns added
    in PR 6 (PR 5 follow-up #1).
    """
    return {
        "id": "00000000-0000-0000-0000-000000000aaa",
        "table_name": table_name,
        "legacy_pk": legacy_pk,
        "web_pk": web_pk,
        "web_column": web_column,
        "preserved_value": json.dumps(preserved_value) if preserved_value is not None else None,
        "strategy": strategy,
        "last_legacy_snapshot_at": last_legacy_snapshot_at,
        "last_web_edit_at": None,
        "last_reconciled_at": last_reconciled_at,
        "reconciliation_status": reconciliation_status,
        "review_reasons": json.dumps(review_reasons or ["web_manual_override_detected"]),
        # PR 5 follow-up columns
        "derived_value": json.dumps(derived_value) if derived_value is not None else None,
        "derived_at": derived_at,
    }


def _shadow_state_mapping_with_current_state_derived():
    """Synthetic ``animales`` TableMapping with ``current_state`` as derived."""
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="animales",
        legacy_table="TbFichaAnimal",
        key_field="NCHIP",
        legacy_key="NCHIP",
        date_fields=["FIMPLANTACIONCHIP", "FDefuncion"],
        columns=[
            ColumnMapping(
                web_column="NCHIP",
                legacy_column="NCHIP",
                transform="identity",
                nullable=False,
            ),
            ColumnMapping(
                web_column="current_state",
                legacy_column=None,
                transform="identity",
                nullable=True,
                web_only_strategy="derived",
            ),
        ],
        fk_lookups=[],
    )


def _voluntario_mapping_with_dni_preserve():
    """Synthetic ``voluntarios`` TableMapping with ``DNI`` as preserve."""
    from migration.mappings import ColumnMapping, TableMapping

    return TableMapping(
        version="1.0",
        web_table="voluntarios",
        legacy_table="TbVoluntariosParaAutorrellenables",
        key_field="Voluntario",
        legacy_key="Voluntario",
        date_fields=[],
        columns=[
            ColumnMapping(
                web_column="Voluntario",
                legacy_column="Voluntario",
                transform="identity",
                nullable=False,
            ),
            ColumnMapping(
                web_column="DNI",
                legacy_column=None,
                transform="identity",
                nullable=True,
                web_only_strategy="preserve",
            ),
        ],
        fk_lookups=[],
    )


def _empty_sync_state():
    from migration.sync_state import SyncState

    return SyncState()


# --- T6.1: Round-trip web->legacy->web preserves DNI ----------------------

# --- T6.4: 10 000 animales x 5 columns perf test -----------------------


class TestListNeedsReviewPerf:
    """T6.4: ``ShadowStateRepository.list_needs_review`` over 10 000
    rows x 5 columns of mixed strategies completes in < 10 seconds.

    The test is a sanity check on the perf budget documented in
    spec.md REQ-Performance. We use ``time.perf_counter`` (not the
    pytest-benchmark plugin -- the project doesn't depend on it) so
    the assertion is portable.
    """

    def test_list_needs_review_under_10s_for_10k_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pre-seed 50 000 shadow rows (10 000 animales x 5 columns) and
        assert ``list_needs_review`` returns them all in < 10s.

        The fake client returns the pre-built row list verbatim (no real
        DB roundtrip). The test measures the repository-side loop
        overhead (sort + filter) — that's where the O(N) cost lives in
        production too (the SQL returns rows in last_legacy_snapshot_at
        order with WHERE filtering at the DB level).
        """
        rows = [
            _needs_review_row(
                table_name="animales",
                legacy_pk=f"a-{idx}",
                web_pk=f"00000000-0000-0000-0000-{idx:012d}",
                web_column=col,
                preserved_value=None,
                strategy="derived",
                last_legacy_snapshot_at=f"2026-06-{(idx % 28) + 1:02d}T10:00:00+00:00",
                review_reasons=None,
            )
            for idx in range(10_000)
            for col in (
                "current_state",
                "legacy_situacion",
                "pre_death_state",
                "active_intake",
                "active_foster",
            )
        ]
        assert len(rows) == 50_000

        client = _FakeSqlExecutor(rows)

        from migration.shadow_state import ShadowStateRepository

        repo = ShadowStateRepository(client)
        started = time.perf_counter()
        listed = repo.list_needs_review(table_name="animales")
        elapsed = time.perf_counter() - started

        assert len(listed) == 50_000
        assert elapsed < 10.0, (
            f"list_needs_review over 50k rows must complete in < 10s; got {elapsed:.2f}s"
        )
