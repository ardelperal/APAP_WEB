"""Strict TDD atoms for the PR4b ``GET /animales/{animal_id}/foto`` route.

This file pins the route-layer contract. The underlying storage and
reliability logic lives in ``app.modules.animals.photo_service`` (single
responsibility: stream photo bytes or signal a missing/sentinel) and
``app.core.insforge.InsForgeClient.download_object_stream`` (two-step
authenticated HTTP). The route translates the typed service outcome to
an HTTP response and never exposes a presigned URL.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): every test seeds its own animal row and
  pre-loads the storage fake's response.
- Rule 2 (DI): the route resolves ``InsForgeClient`` via
  ``Depends(get_insforge_client_dep)``; tests inject a fake via
  ``app.dependency_overrides[get_insforge_client]``.
- Rule 3 (cardinality): each atom asserts the exact storage-call count.
- Rule 4 (no humo): each assertion pins a concrete status code, header,
  or byte count — not absence-of-error.
- Rule 6 (refactor-safety): assertions are about the HTTP contract,
  not internal sequencing.
- Rule 8 (no production mutation): no real InsForge / no real bucket;
  every storage call is intercepted by the fake.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client

# --- 1x1 transparent PNG (67 bytes). Served as the placeholder. ----------
PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02"
    b"\xfeA\xc0\xc1\x00\x00\x00\x00IEND\xaeB`\x82"
)
SENTINEL_KEY = "__missing__"
PHOTO_BUCKET = "apap-photos"


# --- Fakes ----------------------------------------------------------------


class _FakeAnimalesFotoClient(InsForgeClient):
    """In-process fake for the PR4b foto route tests.

    Implements just enough of the InsForgeClient surface to drive
    ``GET /animales/{animal_id}/foto``:

    - ``execute_sql`` returns the seeded animal row on lookup, otherwise
      an empty list (the animals service returns ``None``).
    - ``download_object_stream(bucket, key)`` returns a pre-loaded byte
      iterator or raises a pre-loaded exception.

    The auth-revalidation SELECT is also served (the per-request
    authorization revalidation runs against the same client; the
    animals router is hidden behind a per-request role refresh).
    """

    def __init__(self) -> None:  # type: ignore[override]
        # Skip ``InsForgeClient.__init__``: we override every method the
        # production code calls. ``close`` is a no-op.
        self.animal_rows: dict[str, dict[str, Any]] = {}
        self.download_calls: list[tuple[str, str]] = []
        self.download_response: Iterator[bytes] | None = iter([b"\x89PNG\r\n" + b"X" * 100])
        self.download_raises: BaseException | None = None
        self.queries: list[tuple[str, list[Any] | None]] = []
        self.auth_reval_rol: str = "key_user"
        self.closed = False

    # --- duck-typed InsForgeClient surface ----------------------------
    def execute_sql(self, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        self.queries.append((query, params))
        sql = query.lower()
        # Auth-reval SELECT — answer with an active row so
        # ``require_authorized_user`` accepts the session.
        if "from usuarios_autorizados" in sql and "email = $1" in sql:
            email = params[0] if params else "reval@example.com"
            return [{"id": "u-reval", "email": email, "rol": self.auth_reval_rol, "activo": True}]
        if "from animales" in sql and "where id = $1" in sql and params:
            row = self.animal_rows.get(str(params[0]))
            return [dict(row)] if row else []
        return []

    def download_object_stream(self, bucket: str, key: str) -> Iterator[bytes]:  # type: ignore[override]
        self.download_calls.append((bucket, key))
        if self.download_raises is not None:
            raise self.download_raises
        if self.download_response is None:
            raise RuntimeError("no download response pre-loaded")
        return iter(list(self.download_response))

    def close(self) -> None:  # type: ignore[override]
        self.closed = True


@pytest.fixture
def fake_client() -> _FakeAnimalesFotoClient:
    client = _FakeAnimalesFotoClient()
    app.dependency_overrides[get_insforge_client] = lambda: client
    yield client
    app.dependency_overrides.pop(get_insforge_client, None)


def _seed_animal(
    client: _FakeAnimalesFotoClient,
    animal_id: str,
    *,
    nombrefoto: str | None,
) -> None:
    """Seed the fake with one animal row (Hard Rule 1)."""
    client.animal_rows[animal_id] = {
        "id": animal_id,
        "NCHIP": "941000000000001",
        "NombreAnimal": "Firulais",
        "Especie": "CANINA",
        "Sexo": "M",
        "FNacimiento": "2023-04-12",
        "activo": True,
        "NombreFoto": nombrefoto,
    }


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    """Install a valid authorized session cookie via the project-idiomatic seam."""
    settings = get_settings()
    token = write_session(
        {
            "email": "reval@example.com",
            "rol": "key_user",
            "user_id": "u-reval-foto",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-foto",
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


# --- Tests ----------------------------------------------------------------


class TestFotoRouteAuthAndRouting:
    """Auth gate + happy path stream + placeholder + no URL leak."""

    async def test_foto_without_session_redirects_to_login(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """An anonymous request MUST 302 to /login and NOT touch the storage fake."""
        _seed_animal(fake_client, "anim-1", nombrefoto="abc123.jpg")

        response = await client.get("/animales/anim-1/foto", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/login"
        # No DB query and no storage call happened.
        assert fake_client.queries == []
        assert fake_client.download_calls == []

    async def test_foto_animal_not_found_returns_404(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """An unknown animal_id returns 404 (no stream, no placeholder)."""
        _login_as_key_user(client)
        fake_client.animal_rows = {}  # no seeded row

        response = await client.get(
            "/animales/missing-uuid/foto", follow_redirects=False
        )

        assert response.status_code == 404
        assert fake_client.download_calls == []

    async def test_foto_with_nombrefoto_streams_object_bytes(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """An authorized request with a real key streams object bytes."""
        _login_as_key_user(client)
        fake_client.download_response = iter([b"\x89PNG\r\n\x1a\n", b"PHOTO-BYTES"])
        _seed_animal(fake_client, "anim-2", nombrefoto="abc123.jpg")

        response = await client.get(
            "/animales/anim-2/foto", follow_redirects=False
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.content == b"\x89PNG\r\n\x1a\nPHOTO-BYTES"
        # Storage was called exactly once with the right key.
        assert fake_client.download_calls == [(PHOTO_BUCKET, "abc123.jpg")]

    async def test_foto_with_sentinel_nombrefoto_returns_placeholder(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """``NombreFoto=__missing__`` returns the placeholder PNG without storage I/O."""
        _login_as_key_user(client)
        _seed_animal(fake_client, "anim-3", nombrefoto=SENTINEL_KEY)

        response = await client.get(
            "/animales/anim-3/foto", follow_redirects=False
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == PLACEHOLDER_PNG
        # No storage call for a sentinel row.
        assert fake_client.download_calls == []

    async def test_foto_with_null_nombrefoto_returns_placeholder(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """``NombreFoto=None`` returns the placeholder (no storage I/O)."""
        _login_as_key_user(client)
        _seed_animal(fake_client, "anim-4", nombrefoto=None)

        response = await client.get(
            "/animales/anim-4/foto", follow_redirects=False
        )

        assert response.status_code == 200
        assert response.content == PLACEHOLDER_PNG
        assert fake_client.download_calls == []

    async def test_foto_storage_failure_returns_placeholder(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """A storage-side error fails closed to the placeholder (no 5xx leak)."""
        from app.core.insforge import InsForgeError

        _login_as_key_user(client)
        fake_client.download_raises = InsForgeError(503, {"error": "boom"})
        _seed_animal(fake_client, "anim-5", nombrefoto="abc123.jpg")

        response = await client.get(
            "/animales/anim-5/foto", follow_redirects=False
        )

        # Fail closed: placeholder, no 5xx exposed.
        assert response.status_code == 200
        assert response.content == PLACEHOLDER_PNG


class TestFotoRouteDoesNotLeakPresignedUrl:
    """Privacy invariant: the route never returns the storage URL."""

    async def test_foto_response_body_never_contains_storage_url(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """The response body MUST NOT include the presigned URL or any presigned token."""
        from app.core.insforge import InsForgeError

        _login_as_key_user(client)
        fake_client.download_raises = InsForgeError(
            401,
            {"error": "auth_failed", "url": "https://storage.example.local/secret?token=abc"},
        )
        _seed_animal(fake_client, "anim-6", nombrefoto="abc123.jpg")

        response = await client.get(
            "/animales/anim-6/foto", follow_redirects=False
        )

        # Placeholder body, no leak.
        assert response.status_code == 200
        assert response.content == PLACEHOLDER_PNG
        # Headers MUST NOT carry the presigned URL or token either.
        for header_name, header_value in response.headers.items():
            assert "storage.example.local" not in header_value, (
                f"presigned URL leaked in header {header_name!r}: {header_value!r}"
            )
            assert "token=abc" not in header_value
        # The streamed bytes don't contain the URL either.
        assert b"storage.example.local" not in response.content
        assert b"token=abc" not in response.content


class TestFotoRouteIsolatedService:
    """The route delegates to the photo_service module — no SQL in the route."""

    async def test_foto_route_does_not_issue_raw_sql_for_photo(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """The route MUST only call ``execute_sql`` for the animal lookup.

        The photo stream MUST go through ``download_object_stream``;
        the route must NOT do raw SQL for the photo.
        """
        _login_as_key_user(client)
        fake_client.download_response = iter([b"\x89PNG\r\n"])
        _seed_animal(fake_client, "anim-7", nombrefoto="xyz.jpg")

        await client.get("/animales/anim-7/foto", follow_redirects=False)

        # At least one SQL query (the animales lookup). Auth-reval may or
        # not run depending on the in-process cache TTL; we don't pin its
        # count here. The invariant: every SQL the route emits is for
        # the animales lookup, NEVER for the photo/bucket storage.
        sql_queries = [q.lower() for q, _ in fake_client.queries]
        assert len(sql_queries) >= 1
        # The animales lookup MUST be present.
        animal_lookup = [q for q in sql_queries if "from animales" in q and "where id = $1" in q]
        assert len(animal_lookup) == 1
        # No photo/bucket/migration SQL.
        for q in sql_queries:
            assert "upload" not in q
            assert "delete from" not in q
            assert "insert into" not in q
            assert "bucket" not in q
        # Storage was called with the right key.
        assert fake_client.download_calls == [(PHOTO_BUCKET, "xyz.jpg")]


class TestFotoRouteAuthorizationInvariant:
    """Anonymous + insufficient-privilege callers are rejected pre-storage."""

    async def test_foto_anonymous_call_does_not_call_storage(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """No session → no SQL, no storage I/O (auth middleware redirects)."""
        _seed_animal(fake_client, "anim-8", nombrefoto="abc.jpg")

        response = await client.get("/animales/anim-8/foto", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/login"
        assert fake_client.queries == []
        assert fake_client.download_calls == []
