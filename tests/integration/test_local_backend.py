"""F1 acceptance tests for the local FastAPI/Postgres backend."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.local_backend.app import create_app
from app.core.local_backend.db import _safe_table

pytestmark = pytest.mark.integration


class _FakeCursor:
    description = None
    rowcount = 0

    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> list[Any]:
        return []

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = _FakeCursor()
        self.commits = 0

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self, **kwargs: Any) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


def _patch_migration_seam(
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_hash: str = "a" * 64,
    snapshot: str = "snapshot",
    lock: str = "lock",
    released: str = "released",
    written: str = "written",
) -> None:
    """Patch the five migration.apply seam symbols used by the executor."""
    monkeypatch.setattr(
        "migration.apply.compute_accdb_hash",
        lambda _path: source_hash,
    )
    monkeypatch.setattr("migration.apply.read_snapshot", lambda _path: snapshot)
    monkeypatch.setattr("migration.apply.acquire_lock", lambda _path: lock)
    monkeypatch.setattr("migration.apply.release_lock", lambda _path: released)
    monkeypatch.setattr(
        "migration.apply.write_snapshot",
        lambda _path, **_kwargs: written,
    )


async def _post(
    client: httpx.AsyncClient,
    query: str,
    params: list[Any] | None,
) -> httpx.Response:
    return await client.post(
        "/api/database/advance/rawsql",
        json={"query": query, "params": params},
    )


@pytest.mark.asyncio
async def test_as3_rawsql_insert_select_roundtrip(
    ephemeral_postgres: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AS3: an INSERT and SELECT round-trip against the ephemeral schema."""
    with ephemeral_postgres.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS test_roundtrip "
                "(id INT, label TEXT)"
            )
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", ephemeral_postgres.schema)
    application = create_app(db_dsn=ephemeral_postgres.dsn, oauth_configured=False)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            inserted = await _post(
                client,
                "INSERT INTO test_roundtrip (id, label) VALUES ($1, $2)",
                [1, "alpha"],
            )
            assert inserted.status_code == 200
            selected = await _post(
                client,
                "SELECT id, label FROM test_roundtrip ORDER BY id",
                [],
            )
    assert selected.status_code == 200
    assert selected.json() == {"rows": [{"id": 1, "label": "alpha"}], "rowCount": 1}


@pytest.mark.asyncio
async def test_as4_unsafe_identifier_does_not_drop_table(
    ephemeral_postgres: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AS4: the injected DROP is rejected and the target table remains."""
    with ephemeral_postgres.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE users (id INT)")
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", ephemeral_postgres.schema)
    application = create_app(db_dsn=ephemeral_postgres.dsn, oauth_configured=False)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await _post(client, "DROP TABLE users; --", [])
    assert response.status_code == 400
    assert response.json()["error"] == "unsafe_sql_identifier"
    with ephemeral_postgres.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('users')")
            assert cursor.fetchone()["to_regclass"] == "users"


@pytest.mark.asyncio
async def test_as5_multiple_statements_are_rejected(
    ephemeral_postgres: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AS5: a semicolon cannot chain two statements."""
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", ephemeral_postgres.schema)
    application = create_app(db_dsn=ephemeral_postgres.dsn, oauth_configured=False)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await _post(client, "SELECT 1; SELECT 2", [])
    assert response.status_code == 400


def test_create_app_rejects_empty_dsn() -> None:
    """The DSN guard fails before FastAPI is constructed."""
    with pytest.raises(RuntimeError, match="db_dsn is required for the local backend"):
        create_app(db_dsn="", oauth_configured=False)


def test_safe_table_rejects_unsafe_and_multi_statement_values() -> None:
    """Identifier validation covers segments and obvious SQL terminators."""
    assert _safe_table("animals.owner_id") == "animals.owner_id"
    with pytest.raises(ValueError):
        _safe_table("users; --")
    with pytest.raises(ValueError):
        _safe_table("a.b;DROP")


@pytest.mark.asyncio
async def test_rawsql_lazily_uses_migration_hash_and_snapshot_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T1.4: patch targets on migration.apply are resolved at call time."""
    _patch_migration_seam(monkeypatch)
    application = create_app(db_dsn="test-dsn", oauth_configured=False)
    connection = _FakeConnection()
    async with application.router.lifespan_context(application):
        application.state.local_postgres_executor._connect = lambda: connection
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await _post(client, "SELECT 1", [])
    assert response.status_code == 200
    state = application.state.local_postgres_executor._migration_state
    assert state["source_hash"] == "a" * 64
    assert state["snapshot"] == "snapshot"
    assert state["written"] == "written"


@pytest.mark.asyncio
async def test_rawsql_lazily_uses_lock_and_release_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T1.4: lock acquisition and release also use the live seam."""
    _patch_migration_seam(monkeypatch, lock="acquired", released="done")
    application = create_app(db_dsn="test-dsn", oauth_configured=False)
    connection = _FakeConnection()
    async with application.router.lifespan_context(application):
        application.state.local_postgres_executor._connect = lambda: connection
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await _post(client, "SELECT 1", [])
    assert response.status_code == 200
    state = application.state.local_postgres_executor._migration_state
    assert state["lock_info"] == "acquired"
    assert state["released"] == "done"
