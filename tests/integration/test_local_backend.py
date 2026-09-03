"""F1 acceptance tests for the local FastAPI/Postgres backend."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.local_backend.app import create_app
from app.core.local_backend.db import _safe_table
from app.core.local_backend.oauth_google import oauth_router as oauth_router_obj
from app.core.local_backend.storage import storage_router as storage_router_obj

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


# ---------------------------------------------------------------------------
# F2 — healthz + storage + OAuth stubs (R1, R3, R4 acceptance scenarios)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_as1_healthz_db_up_oauth_configured(
    ephemeral_postgres: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AS1: db up + oauth configured produces the documented envelope."""
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", ephemeral_postgres.schema)
    monkeypatch.setenv("APAP_GOOGLE_CLIENT_ID", "test-client-id")
    application = create_app(
        db_dsn=ephemeral_postgres.dsn, oauth_configured=True
    )
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["db"] == "up"
    assert body["storage"] == "up"
    assert body["oauth"] == "configured"


@pytest.mark.asyncio
async def test_as2_healthz_oauth_missing(
    ephemeral_postgres: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AS2: when APAP_GOOGLE_CLIENT_ID is unset, oauth reports 'missing'."""
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", ephemeral_postgres.schema)
    monkeypatch.delenv("APAP_GOOGLE_CLIENT_ID", raising=False)
    application = create_app(
        db_dsn=ephemeral_postgres.dsn, oauth_configured=False
    )
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["oauth"] == "missing"


@pytest.mark.asyncio
async def test_as6_storage_lists_seeded_bucket() -> None:
    """AS6: GET /api/storage/buckets returns the seeded apap-photos entry."""
    test_app = FastAPI()
    test_app.include_router(storage_router_obj, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/storage/buckets")
    assert response.status_code == 200
    body = response.json()
    assert any(
        entry["bucketName"] == "apap-photos"
        and entry["isPublic"] is False
        and entry["files"] == 0
        for entry in body
    )


@pytest.mark.asyncio
async def test_as7_storage_create_on_demand() -> None:
    """AS7: POST /api/storage/buckets/{newbucket} creates on demand."""
    test_app = FastAPI()
    test_app.include_router(storage_router_obj, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/storage/buckets/newbucket")
    assert response.status_code == 200
    body = response.json()
    assert body["bucketName"] == "newbucket"
    assert body["isPublic"] is False
    assert body["files"] == 0


@pytest.mark.asyncio
async def test_as8a_oauth_google_start_returns_auth_url() -> None:
    """AS8 (start): POST /api/auth/oauth/google returns the Google authUrl stub."""
    test_app = FastAPI()
    test_app.include_router(oauth_router_obj, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/auth/oauth/google",
            params={
                "code_challenge": "abc",
                "redirect_uri": "http://x/cb",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["authUrl"].startswith("https://accounts.google.com")


@pytest.mark.asyncio
async def test_as8b_oauth_google_callback_returns_jwt_envelope() -> None:
    """AS8 (callback): POST /api/auth/oauth/google/callback returns a JWT envelope."""
    test_app = FastAPI()
    test_app.include_router(oauth_router_obj, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/auth/oauth/google/callback",
            json={"code": "x", "code_verifier": "y", "redirect_uri": "z"},
        )
    assert response.status_code == 200
    body = response.json()
    token = body["token"]
    assert token.count(".") == 2  # header.payload.signature
    assert body["user"] == {"id": "local-user", "email": "local@apap"}


@pytest.mark.asyncio
async def test_as8c_oauth_exchange_with_valid_insforge_code() -> None:
    """AS8 (exchange): valid insforge_code returns the same envelope."""
    test_app = FastAPI()
    test_app.include_router(oauth_router_obj, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/auth/oauth/exchange?client_type=web",
            json={"code": "insforge_abcdef12", "code_verifier": "v"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["token"].count(".") == 2
    assert body["user"] == {"id": "local-user", "email": "local@apap"}


@pytest.mark.asyncio
async def test_as8c_neg_oauth_exchange_with_invalid_code() -> None:
    """AS8 (exchange, neg): an invalid code returns HTTP 401."""
    test_app = FastAPI()
    test_app.include_router(oauth_router_obj, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/auth/oauth/exchange?client_type=web",
            json={"code": "wrong", "code_verifier": "v"},
        )
    assert response.status_code == 401
