"""Unit tests for the chip-change saga adapter (issue #916, A-04).

Covers the saga helpers of
``app.modules.animals.adapters.local_backend.animals_local_backend_chip_cascade``
against a fake ``TransactionalSqlExecutor`` — no Postgres, no HTTP. The
real-schema atomicity contract is pinned separately in
``tests/integration/test_chip_cascade_integration.py``.
"""

from __future__ import annotations

from typing import Any

from app.modules.animals.adapters.local_backend.animals_local_backend_chip_cascade import (
    AnimalsLocalBackendChipCascade,
)

_OLD = "941000000000001"
_NEW = "941000000099999"
_PARAMS = {
    "animal_id": "animal-1",
    "old_chip": _OLD,
    "new_chip": _NEW,
    "reason": "chip reimplantado",
    "operador_user_id": "operator-1",
}


class _FakeBoundExecutor:
    """Executor bound to the fake transaction, recording every query."""

    def __init__(self, parent: _FakeTransactionalExecutor) -> None:
        self._parent = parent

    def execute_sql(self, query: str, params: Any = None) -> list[dict[str, Any]]:
        self._parent.calls.append(("tx", query.strip(), params))
        return self._parent.respond(query, params)


class _FakeTransactionalExecutor:
    """Fake ``TransactionalSqlExecutor`` with fault-injection hooks."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.duplicate_rows: list[dict[str, Any]] = []
        self.current_chip_rows: list[dict[str, Any]] = [{"NCHIP": _OLD}]
        self.update_rows: list[dict[str, Any]] = [{"id": "animal-1"}]
        self.fail_on: str | None = None  # "insert"
        self.transaction_opened = False
        self.committed = False
        self.rolled_back = False

    def respond(self, query: str, params: Any) -> list[dict[str, Any]]:
        q = " ".join(query.split()).lower()
        if "select id from animales where nchip" in q:
            return self.duplicate_rows
        if "select nchip as" in q:
            return self.current_chip_rows
        if q.startswith("update animales set nchip"):
            return self.update_rows
        if "insert into animal_lifecycle_events" in q:
            if self.fail_on == "insert":
                raise RuntimeError("forced event failure (issue #916)")
            return []
        raise AssertionError(f"unexpected query in saga: {query!r}")

    def execute_sql(self, query: str, params: Any = None) -> list[dict[str, Any]]:
        self.calls.append(("client", query.strip(), params))
        return self.respond(query, params)

    def transaction(self) -> _FakeTransactionalExecutor:
        self.transaction_opened = True
        return self

    def __enter__(self) -> _FakeBoundExecutor:
        return _FakeBoundExecutor(self)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is not None:
            self.rolled_back = True
            return False
        self.committed = True
        return False


def _run_saga(client: _FakeTransactionalExecutor) -> object:
    return AnimalsLocalBackendChipCascade(client).change_animal_chip(**_PARAMS)


def test_happy_path_runs_update_and_event_inside_one_transaction() -> None:
    """The saga issues UPDATE animales + INSERT event through the bound
    transaction executor and commits; no BEGIN/COMMIT/ROLLBACK statements
    travel through execute_sql."""
    client = _FakeTransactionalExecutor()

    result = _run_saga(client)

    assert result.success is True
    assert result.updated_tables == {"animals": 1}
    assert result.error is None
    assert client.committed is True
    assert client.rolled_back is False
    tx_queries = [q for scope, q, _ in client.calls if scope == "tx"]
    assert any(q.lower().startswith("update animales set nchip") for q in tx_queries)
    assert any("insert into animal_lifecycle_events" in q.lower() for q in tx_queries)
    for _, query, _ in client.calls:
        assert query.strip().lower() not in {"begin", "commit", "rollback"}


def test_preflight_duplicate_chip_short_circuits_before_the_transaction() -> None:
    """A taken new_chip fails closed without opening the transaction."""
    client = _FakeTransactionalExecutor()
    client.duplicate_rows = [{"id": "other-animal"}]

    result = _run_saga(client)

    assert result.success is False
    assert "ya está asignado a otro animal" in str(result.error)
    assert client.transaction_opened is False
    assert client.committed is False
    assert result.updated_tables == {}


def test_preflight_stale_old_chip_short_circuits_before_the_transaction() -> None:
    """A persisted chip different from old_chip fails closed pre-transaction."""
    client = _FakeTransactionalExecutor()
    client.current_chip_rows = [{"NCHIP": "changed-by-someone-else"}]

    result = _run_saga(client)

    assert result.success is False
    assert "recargue la ficha" in str(result.error)
    assert client.transaction_opened is False


def test_guarded_update_matching_no_row_fails_and_rolls_back() -> None:
    """A race between preflight and the transaction body aborts the unit:
    the guarded UPDATE raising means rollback and no audit event."""
    client = _FakeTransactionalExecutor()
    client.update_rows = []  # guarded UPDATE matched no row (lost race)

    result = _run_saga(client)

    assert result.success is False
    assert "recargue la ficha" in str(result.error)
    assert client.rolled_back is True
    assert client.committed is False
    assert result.updated_tables == {}
    # No CHIP_CHANGED event was attempted for a chip that never moved.
    insert_attempts = [
        q for _, q, _ in client.calls if "insert into animal_lifecycle_events" in q.lower()
    ]
    assert insert_attempts == []


def test_event_failure_rolls_back_and_reports_empty_updated_tables() -> None:
    """A failure after the animales UPDATE surfaces as a failure result
    with empty updated_tables — the real transaction rolled everything
    back, so nothing persisted."""
    client = _FakeTransactionalExecutor()
    client.fail_on = "insert"

    result = _run_saga(client)

    assert result.success is False
    assert "forced event failure (issue #916)" in str(result.error)
    assert result.updated_tables == {}
    assert client.rolled_back is True
    assert client.committed is False
