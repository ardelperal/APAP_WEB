"""Tests for the M0 local backend (issue #641, self-host-backend-coolify).

The M0 milestone replaces InsForge (the managed BaaS) with a FastAPI
backend served by the same process, over Postgres. The tests below
pin the contract that ``InsForgeClient`` consumes regardless of whether
the backend is InsForge remote or the local one.

This file replaces the earlier in-process uvicorn tests (which proved
brittle because uvicorn's thread-based runner does not run the FastAPI
lifespan reliably — a previous in-session attempt at uvicorn threads
failed with ``SystemExit: 3``). The new approach is end-to-end
against a real ``create_app()`` FastAPI instance via
``httpx.AsyncClient(ASGITransport=app)``, with the FastAPI lifespan
driven explicitly via ``app.router.lifespan_context(app)`` because
``httpx.ASGITransport`` does not drive it on its own.

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): each atom builds its own state.
- Rule 4 (no humo): assertions on real behaviour (JSON shapes, status
  codes), never absence-of-error.
- Rule 8 (no production mutation): the local backend runs in-process
  via ASGITransport; no real InsForge is contacted.

M0 of the self-host-backend-coolify openspec (issue #641).
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.core.local_backend.app import create_app

# --- URL switching (unit-level) -------------------------------------------


def test_insforge_client_defaults_to_insforge_url() -> None:
    """When ``APAP_LOCAL_BACKEND`` is unset, the client targets InsForge."""
    from app.core.insforge import InsForgeClient

    client = InsForgeClient(
        base_url="https://insforge.example.com",
        service_key="dummy",
    )
    assert client._client.base_url == "https://insforge.example.com"


def test_insforge_client_uses_local_default_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``APAP_LOCAL_BACKEND=true`` and ``APAP_INSFORGE_URL`` is empty,
    the client targets ``http://localhost:8000`` (the local backend).

    Note: the ``base_url`` is intentionally without a trailing
    ``/api`` — ``InsForgeClient`` hardcodes the ``/api/...``
    prefix on every endpoint, so the base URL itself must NOT
    carry that prefix (otherwise every request would land on
    ``/api/api/...`` and 404).
    """
    from app.core.insforge import InsForgeClient

    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.delenv("APAP_INSFORGE_URL", raising=False)
    client = InsForgeClient(base_url="", service_key="dummy")
    # ``httpx.Client.base_url`` is a ``URL`` object; compare via ``str``
    # so the assertion works regardless of trailing-slash normalization.
    assert str(client._client.base_url).rstrip("/") == "http://localhost:8000"


def test_insforge_client_local_url_overrides_local_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APAP_INSFORGE_URL`` always wins over the local default."""
    from app.core.insforge import InsForgeClient

    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.setenv("APAP_INSFORGE_URL", "https://custom-insforge.example.com")
    client = InsForgeClient(
        base_url=os.environ["APAP_INSFORGE_URL"],
        service_key="dummy",
    )
    assert client._client.base_url == "https://custom-insforge.example.com"


# --- Local backend integration --------------------------------------------


@pytest.fixture
async def local_backend_client(self_host_schema):
    """Stand up the local backend in-process and yield an open httpx client.

    ``httpx.ASGITransport`` does **not** drive the FastAPI lifespan
    automatically — that is a known httpx limitation. The fixture
    invokes ``app.router.lifespan_context(app)`` explicitly so the
    handler-side ``request.app.state.local_postgres_executor`` is
    populated. Without this, the rawsql handler would raise
    ``AttributeError`` because the lifespan never set the executor.

    The fixture yields an already-open client; tests use the client
    directly (not via ``async with``) because httpx forbids double-open.
    Cleanup happens in the fixture's ``finally`` block.
    """
    os.environ["APAP_LOCAL_DB_URL"] = os.environ["APAP_TEST_POSTGRES_DSN"]
    os.environ["APAP_LOCAL_DB_SCHEMA"] = self_host_schema.schema

    app = create_app()
    async with app.router.lifespan_context(app):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        try:
            yield client
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_healthz_returns_200_and_db_status(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """``GET /healthz`` returns 200 with the expected body shape."""
    client = local_backend_client
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "db" in body
    assert body["db"] in ("up", "down")
    assert "storage" in body
    assert body["storage"] in ("up", "down")
    assert "oauth" in body
    assert body["oauth"] in ("configured", "missing")


# --- rawsql handler (M0 0.1.4) -----------------------------------------------


@pytest.mark.asyncio
async def test_rawsql_select_roundtrip(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """INSERT then SELECT via the rawsql endpoint returns the inserted row.

    Pins the contract that ``InsForgeClient.execute_sql`` consumes:
    ``{"rows": [{...}], "rowCount": N}``.
    """
    client = local_backend_client
    # Bootstrap a table for the round-trip (the executor does not
    # own migrations; tests use the conftest's ephemeral schema).
    await client.post(
        "/api/database/advance/rawsql",
        json={
            "query": (
                'CREATE TABLE IF NOT EXISTS "rawsql_roundtrip" ('
                "id INT PRIMARY KEY, label TEXT)"
            ),
            "params": [],
        },
    )
    await client.post(
        "/api/database/advance/rawsql",
        json={
            "query": (
                'INSERT INTO "rawsql_roundtrip" (id, label) '
                "VALUES ($1, $2)"
            ),
            "params": [1, "alpha"],
        },
    )
    r = await client.post(
        "/api/database/advance/rawsql",
        json={
            "query": 'SELECT id, label FROM "rawsql_roundtrip" ORDER BY id',
            "params": [],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == [{"id": 1, "label": "alpha"}]
    assert body["rowCount"] == 1


@pytest.mark.asyncio
async def test_rawsql_insert_returns_empty_rows(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """INSERT without RETURNING returns ``{"rows": [], "rowCount": 0}``.

    Pins the InsForge contract: non-SELECT queries return an empty
    rows list so the consumer (``InsForgeClient.execute_sql``) can
    safely call ``rows[0]`` after a SELECT.
    """
    client = local_backend_client
    await client.post(
        "/api/database/advance/rawsql",
        json={
            "query": (
                'CREATE TABLE IF NOT EXISTS "rawsql_insert" ('
                "id INT PRIMARY KEY)"
            ),
            "params": [],
        },
    )
    r = await client.post(
        "/api/database/advance/rawsql",
        json={
            "query": 'INSERT INTO "rawsql_insert" (id) VALUES ($1)',
            "params": [42],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["rowCount"] == 0


@pytest.mark.asyncio
async def test_rawsql_error_returns_4xx(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """A query-level error (syntax / unknown table) returns HTTP 4xx, not 5xx.

    Distinguishes caller mistakes (``QueryError`` → 400) from server
    failures (``DatabaseError`` → 5xx). The InsForge contract was
    4xx for query errors; this keeps that contract for the local
    backend.
    """
    client = local_backend_client
    r = await client.post(
        "/api/database/advance/rawsql",
        json={
            "query": "SELECT * FROM does_not_exist",
            "params": [],
        },
    )
    assert 400 <= r.status_code < 500, r.text


# --- storage handler (M0 0.1.5) -----------------------------------------------


@pytest.mark.asyncio
async def test_storage_list_buckets(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """``GET /api/storage/buckets`` returns the bucket-list shape.

    Pins the contract ``InsForgeClient.get_bucket`` consumes: a list of
    ``{"bucketName": ..., "isPublic": ..., "files": ...}`` dicts.
    """
    client = local_backend_client
    r = await client.get("/api/storage/buckets")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert body, "M0 stub exposes at least the apap-photos bucket"
    item = body[0]
    assert "bucketName" in item
    assert "isPublic" in item
    assert "files" in item
    assert item["bucketName"] == "apap-photos"
    assert item["isPublic"] is False


@pytest.mark.asyncio
async def test_storage_ensure_bucket_returns_bucket_shape(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """``POST /api/storage/buckets`` (with ``bucketName`` in body) returns
    the bucket shape used by ``InsForgeClient.ensure_bucket``.

    The InsForge contract is body-based (``{"bucketName": ..., "isPublic": ...}``),
    not path-based (``/buckets/{name}``), so the handler must accept the
    body form even though the tasks.md originally suggested the path
    form.
    """
    client = local_backend_client
    r = await client.post(
        "/api/storage/buckets",
        json={"bucketName": "test-bucket", "isPublic": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["bucketName"] == "test-bucket"
    assert body["isPublic"] is False
    assert "files" in body


@pytest.mark.asyncio
async def test_storage_get_bucket_finds_after_ensure(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """After POST ensure, GET list contains the new bucket.

    Pins the round-trip that ``ensure_bucket`` does: POST to create,
    then GET list to confirm visibility.
    """
    client = local_backend_client
    await client.post(
        "/api/storage/buckets",
        json={"bucketName": "roundtrip-bucket", "isPublic": False},
    )
    r = await client.get("/api/storage/buckets")
    assert r.status_code == 200
    body = r.json()
    names = [item["bucketName"] for item in body]
    assert "roundtrip-bucket" in names


# --- OAuth flow (M0 0.1.6) ---------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_google_start_returns_auth_url(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """``GET /api/auth/oauth/google`` returns the auth URL shape.

    Pins the contract ``InsForgeClient.start_google_oauth`` consumes:
    ``{"authUrl": "https://..."}``.
    """
    client = local_backend_client
    r = await client.get(
        "/api/auth/oauth/google",
        params={
            "redirect_uri": "http://localhost/callback",
            "code_challenge": "challenge-abc",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "authUrl" in body
    assert isinstance(body["authUrl"], str)
    assert body["authUrl"].startswith("https://")


@pytest.mark.asyncio
async def test_oauth_google_callback_returns_jwt(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """``POST /api/auth/oauth/google/callback`` returns ``token`` + ``user``.

    Pins the contract ``InsForgeClient.exchange_google_oauth_code``
    consumes: ``{"token": "<jwt>", "user": {"id": ..., "email": ...}}``.
    """
    client = local_backend_client
    r = await client.post(
        "/api/auth/oauth/google/callback",
        json={
            "code": "google-code-abc",
            "code_verifier": "verifier-abc",
            "redirect_uri": "http://localhost/callback",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "token" in body
    assert isinstance(body["token"], str)
    assert body["token"].count(".") == 2  # JWT has 3 parts
    user = body["user"]
    assert "id" in user
    assert "email" in user


@pytest.mark.asyncio
async def test_oauth_exchange_returns_jwt(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """``POST /api/auth/oauth/exchange?client_type=web`` returns ``user`` + ``accessToken``.

    Pins the contract ``InsForgeClient.exchange_insforge_oauth_code``
    consumes (the InsForge-hosted OAuth proxy): the body has at least
    ``user`` and ``accessToken`` keys; the test reads ``accessToken``
    as the session JWT.
    """
    client = local_backend_client
    r = await client.post(
        "/api/auth/oauth/exchange",
        params={"client_type": "web"},
        json={
            "code": "insforge-code-abc",
            "code_verifier": "verifier-abc",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "user" in body
    assert body["user"]["id"]
    assert body["user"]["email"]
    assert "accessToken" in body

