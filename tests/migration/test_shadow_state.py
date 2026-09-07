"""PR2 / M0 infrastructure bootstrap atoms.

These tests cover the PR2 slice of ``live-data-migration-sandbox``:
``ShadowStateRepository.ensure_table()`` is the only schema-bootstrap
contract used by the apply path, and replaying the bootstrap is safe.
"""

from __future__ import annotations

from migration.apply import _bootstrap_shadow_state
from migration.shadow_state import ShadowStateRepository
from tests.migration.conftest import FakeLocalBackend  # noqa: TID251


def test_shadow_repository_ensure_table_replays_idempotent_ddl(
    web_client: FakeLocalBackend,
) -> None:
    """Two ensure calls emit only idempotent CREATE statements.

    The SQL-level ``IF NOT EXISTS`` contract means replaying bootstrap
    creates no duplicate state and never drops existing rows.
    """
    repo = ShadowStateRepository(web_client)

    repo.ensure_table()
    repo.ensure_table()

    table_ddl = [
        q for q, _ in web_client.queries if "CREATE TABLE" in q.upper()
    ]
    index_ddl = [
        q for q, _ in web_client.queries if "CREATE INDEX" in q.upper()
    ]
    assert len(table_ddl) == 2
    assert len(index_ddl) == 2
    assert all("IF NOT EXISTS" in q.upper() for q in table_ddl + index_ddl)
    assert not any(
        "DROP" in q.upper() or "DELETE" in q.upper()
        for q, _ in web_client.queries
    )


def test_apply_bootstrap_uses_shadow_repository_contract(
    monkeypatch,
    web_client: FakeLocalBackend,
) -> None:
    """The apply bootstrap delegates schema readiness to the repository.

    PR2's contract is that apply/reconcile do not duplicate the DDL
    wiring; they call the existing ``ShadowStateRepository.ensure_table``
    contract so the schema-plane mechanism has one owner.
    """
    calls: list[str] = []

    class SpyShadowStateRepository:
        def __init__(self, client: FakeLocalBackend) -> None:
            assert client is web_client

        def ensure_table(self) -> None:
            calls.append("ensure_table")

    monkeypatch.setattr(
        "migration.apply.ShadowStateRepository",
        SpyShadowStateRepository,
    )

    _bootstrap_shadow_state(web_client)

    assert calls == ["ensure_table"]
    assert web_client.queries == []
