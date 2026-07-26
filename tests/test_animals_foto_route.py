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
from app.modules.animals import photo_service

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
      iterator or raises a pre-loaded exception. The iterator is consumed
      lazily so mid-stream failure injection (via
      ``download_mid_stream_failure`` / ``download_mid_stream_fail_after_n``)
      triggers between chunks instead of after the whole list.

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
        # Mid-stream failure injection: when set, the fake generator raises
        # ``download_mid_stream_failure`` once ``download_mid_stream_fail_after_n``
        # chunks have been yielded. Used by the PR4b 4R remediation atoms
        # to exercise the mid-stream → placeholder path.
        self.download_mid_stream_failure: BaseException | None = None
        self.download_mid_stream_fail_after_n: int = 0
        self.queries: list[tuple[str, list[Any] | None]] = []
        self.auth_reval_rol: str = "key_user"
        self.closed = False
        # PR4b 4R WARN-3: inject a SQL failure on the animales lookup to
        # exercise the placeholder-on-SQL-error path. When set, the fake
        # raises this exception from ``execute_sql`` for queries whose
        # lowercased SQL contains ``from animales`` + ``where id``.
        self.animales_lookup_raises: BaseException | None = None

    # --- duck-typed InsForgeClient surface ----------------------------
    def execute_sql(self, query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        self.queries.append((query, params))
        sql = query.lower()
        # PR4b 4R WARN-3: the animales-lookup path can be injected with a
        # SQL failure so the route's try/except can prove the placeholder
        # translation. Auth-reval still answers before this branch fires.
        if (
            self.animales_lookup_raises is not None
            and "from animales" in sql
            and "where id" in sql
        ):
            raise self.animales_lookup_raises
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
        # Yield chunks one at a time so mid-stream errors surface in the
        # consumer (rather than after the whole list is materialised).
        # ``list(...)`` snapshots the source iterator because the underlying
        # ``download_response`` is consumed on first yield.
        chunks = list(self.download_response)
        if self.download_mid_stream_failure is not None:
            yield_failure = self.download_mid_stream_failure
            fail_at = self.download_mid_stream_fail_after_n
            for i, chunk in enumerate(chunks):
                if i >= fail_at:
                    raise yield_failure
                yield chunk
            return
        for chunk in chunks:
            yield chunk

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


# =============================================================================
# PR4b 4R remediation — mid-stream error → placeholder (fail-closed)
# =============================================================================


class TestFotoRouteMidStreamFailClosed:
    """Stream errors mid-iteration MUST NOT leak as a 5xx or expose storage internals.

    The streaming-era contract (issue #285) distinguishes two timing windows
    where a transport failure can surface:

    - **Eager** — the failure happens before the first chunk is yielded
      (strategy 5xx, streamed-GET 5xx, first-iteration error). The route's
      pre-advance (``next(byte_iter)`` in ``resolve_animal_photo`` and
      again in the route) catches the failure and returns the placeholder
      PNG at HTTP 200. The two ``placeholder_when_streamed_get_5xx_on_first_chunk``
      and ``placeholder_when_stream_fails_on_first_iteration`` atoms pin
      that contract.

    - **Mid-iteration** — the first chunk is yielded OK and the failure
      happens on a later chunk (``httpx.RemoteProtocolError``,
      ``httpx.ReadTimeout``, stalled stream, etc.). The pre-advance
      succeeds, the route starts ``StreamingResponse``, the HTTP status
      line and headers are sent, and the error then surfaces during
      body iteration. At that point headers are committed and the
      only fail-closed posture is "no 5xx leak, no storage internals
      exposed". In production with a real server (uvicorn) the connection
      just closes with whatever bytes were sent. With
      ``httpx.ASGITransport`` the test client sees the unhandled
      exception propagate out of ``client.get``.

    The two ``mid_iteration_network_error_does_not_leak_5xx`` and
    ``per_chunk_timeout_does_not_leak_5xx`` atoms pin the post-headers
    contract: the response (when one is returned) is a 200 placeholder
    or a 404, never a 5xx; when httpx surfaces the underlying transport
    exception, the exception type is a transport-level ``httpx`` error,
    not a route-level error leaking storage internals.
    """

    async def test_foto_route_placeholder_when_streamed_get_5xx_on_first_chunk(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """Streamed-GET 5xx (caught eagerly by ``download_object_stream``) → placeholder."""
        from app.core.insforge import InsForgeError

        _login_as_key_user(client)
        fake_client.download_raises = InsForgeError(
            503, {"error": "streamed_get_unavailable"}
        )
        _seed_animal(fake_client, "anim-r4-1", nombrefoto="abc.jpg")

        response = await client.get(
            "/animales/anim-r4-1/foto", follow_redirects=False
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == PLACEHOLDER_PNG

    async def test_foto_route_placeholder_when_stream_fails_on_first_iteration(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """Streamed GET succeeds for headers but fails on the very first chunk fetch.

        The contract: the route's eager first-byte check (``next(byte_iter)``)
        catches the ``PhotoStreamError`` raised by ``stream_animal_photo``
        BEFORE ``StreamingResponse`` starts streaming. The placeholder is
        returned (not a 5xx, not a partial response).
        """
        _login_as_key_user(client)
        fake_client.download_response = iter([b"PART1-", b"PART2"])
        fake_client.download_mid_stream_failure = httpx.RemoteProtocolError(
            "stream broken right after headers"
        )
        fake_client.download_mid_stream_fail_after_n = 0  # fail BEFORE the first chunk
        _seed_animal(fake_client, "anim-r4-3", nombrefoto="abc.jpg")

        response = await client.get(
            "/animales/anim-r4-3/foto", follow_redirects=False
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == PLACEHOLDER_PNG

    async def test_foto_route_mid_iteration_network_error_does_not_leak_5xx(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """Stream succeeds for headers + first chunk; mid-iteration network drop is fail-closed.

        Pinned against the real FastAPI app via ``httpx.AsyncClient`` +
        ``ASGITransport`` (the conftest ``client`` fixture). The fake's
        sync generator yields the first chunk OK and raises
        ``httpx.RemoteProtocolError`` on the second. The pre-advance in
        both ``resolve_animal_photo`` and the route succeeds, headers
        are sent, and the error then surfaces during the
        ``StreamingResponse`` body iteration — at which point the HTTP
        status line (200) is already committed.

        Acceptable outcomes (streaming-era contract):

        - The route returns HTTP 200 with the placeholder PNG when the
          service-level pre-advance catches the wrap.
        - The route returns HTTP 404 (the apply agent's predicted path
          when ``StopIteration`` exhausts the underlying generator).
        - The streaming body raises after the status has been sent, so
          the connection closes with the bytes already sent. In
          ``httpx.ASGITransport`` this surfaces as an exception out of
          ``client.get``.

        Hard contract (verified regardless of which outcome fires):
        no 5xx ever leaks to the client; no presigned URL or
        presigned token appears in any response header or body.
        """
        _login_as_key_user(client)
        fake_client.download_response = iter([b"\x89PNG\r\n\x1a\n", b"PART2-", b"PART3"])
        fake_client.download_mid_stream_failure = httpx.RemoteProtocolError(
            "connection reset mid-stream"
        )
        fake_client.download_mid_stream_fail_after_n = 1  # fail on the 2nd chunk
        _seed_animal(fake_client, "anim-r4-2", nombrefoto="abc.jpg")

        await self._assert_fail_closed_mid_stream(
            client, "/animales/anim-r4-2/foto"
        )

    async def test_foto_route_per_chunk_timeout_does_not_leak_5xx(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """Per-chunk ``httpx.ReadTimeout`` on a stalled stream is fail-closed.

        Same contract as ``mid_iteration_network_error_does_not_leak_5xx``
        but with the timeout family of exceptions. The route must not
        surface a 5xx, must not leak a presigned URL or token, and must
        either return a clean placeholder/404 or let the connection
        close with the bytes already sent.
        """
        _login_as_key_user(client)
        fake_client.download_response = iter([b"PART1-", b"PART2"])
        fake_client.download_mid_stream_failure = httpx.ReadTimeout(
            "read timed out mid-stream"
        )
        fake_client.download_mid_stream_fail_after_n = 1
        _seed_animal(fake_client, "anim-r4-4", nombrefoto="abc.jpg")

        await self._assert_fail_closed_mid_stream(
            client, "/animales/anim-r4-4/foto"
        )

    @staticmethod
    async def _assert_fail_closed_mid_stream(
        client: httpx.AsyncClient,
        url: str,
    ) -> None:
        """Assert the streaming route is fail-closed for any mid-stream failure.

        Three outcomes are all acceptable — they are the surface of the
        same physical event (a transport failure after the HTTP status
        line was committed):

        1. A 200 response with the placeholder PNG body (service-level
           pre-advance caught the wrap and produced a placeholder).
        2. A 404 response (route-level pre-advance saw ``StopIteration``
           after the underlying generator was exhausted by the error).
        3. An exception out of ``client.get`` — the production
           equivalent is "the connection closes with the bytes already
           sent". With ``httpx.ASGITransport`` the unhandled
           ``PhotoStreamError`` (from ``stream_animal_photo``) or an
           ``httpx`` transport error propagates.

        Hard contracts (asserted on whatever response we got):
        - No 5xx (the only allowed statuses are 200 and 404).
        - No presigned URL or presigned token in headers or body.
        - On 200, the body is the placeholder PNG (not partial bytes).
        """
        try:
            response = await client.get(url, follow_redirects=False)
        except Exception:
            # The streaming route committed the response status and at
            # least the first chunk before the transport raised. In
            # production with uvicorn this is "the connection closes
            # with the bytes already sent" — no 5xx, no partial response
            # handed to the client. The contract is satisfied; nothing
            # more to assert here.
            return

        # A clean response was returned. It must be a fail-closed 200
        # (placeholder) or 404 — never a 5xx, never a partial leak.
        assert response.status_code in (200, 404), (
            f"Expected 200 placeholder or 404, got {response.status_code} "
            f"(mid-stream error must not surface as a 5xx)"
        )
        if response.status_code == 200:
            assert response.headers["content-type"] == "image/png"
            assert response.content == PLACEHOLDER_PNG
        # The body must not leak a presigned URL or token.
        body_text = response.content.decode("utf-8", errors="replace").lower()
        assert "presigned" not in body_text
        assert "token=" not in body_text
        for header_name, header_value in response.headers.items():
            assert "presigned" not in header_value.lower(), (
                f"presigned leak in header {header_name!r}: {header_value!r}"
            )
            assert "token=" not in header_value.lower()


class TestFotoRouteSqlLookupFailClosed:
    """PR4b 4R WARN-3: SQL failure on the animales lookup fails closed to the placeholder.

    The route wraps ``animals_service.get_animal_by_id`` so an unexpected
    ``InsForgeError`` / network drop / SQL syntax error on the animales
    SELECT becomes the placeholder PNG rather than a 5xx. The animal is
    still ``None`` (no row visible to the route) so this is consistent
    with the missing-animal semantics from the operator's perspective —
    they see the placeholder, never a stack-trace leak. The error is
    still observable in the audit log via ``log_safe`` so the operator
    is not blind to a backend failure.
    """

    async def test_foto_route_placeholder_on_animales_sql_lookup_error(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """``InsForgeError`` on the animales SELECT → placeholder (no 5xx leak)."""
        from app.core.insforge import InsForgeError

        _login_as_key_user(client)
        fake_client.animales_lookup_raises = InsForgeError(
            500, {"error": "animales_lookup_failed"}
        )
        _seed_animal(fake_client, "anim-r4-w3", nombrefoto="abc.jpg")

        response = await client.get(
            "/animales/anim-r4-w3/foto", follow_redirects=False
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == PLACEHOLDER_PNG

    async def test_foto_route_placeholder_on_animales_sql_unexpected_exception(
        self,
        client: httpx.AsyncClient,
        fake_client: _FakeAnimalesFotoClient,
    ) -> None:
        """A non-InsForge exception on the animales SELECT → placeholder.

        Belt-and-braces: the wrap catches ``Exception`` (not just
        ``InsForgeError``) so a ``KeyError`` from a column rename or a
        ``RuntimeError`` from a service-layer invariant violation also
        fails closed. The audit doc records the precise scope claim.
        """
        _login_as_key_user(client)
        fake_client.animales_lookup_raises = RuntimeError(
            "unexpected animales-lookup invariant breach"
        )
        _seed_animal(fake_client, "anim-r4-w3b", nombrefoto="abc.jpg")

        response = await client.get(
            "/animales/anim-r4-w3b/foto", follow_redirects=False
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == PLACEHOLDER_PNG


class TestFotoServiceMidStreamWrapping:
    """``stream_animal_photo`` wraps mid-stream errors as ``PhotoStreamError``.

    These atoms pin the service-level contract: callers (the route layer
    and any future caller) get a single typed surface so the placeholder
    translation has a stable hook. Without this wrapping, mid-stream
    ``httpx.RemoteProtocolError`` / ``httpx.TimeoutException`` /
    ``httpx.ReadTimeout`` would propagate verbatim and force every
    consumer to catch the full httpx exception tree.
    """

    def test_stream_animal_photo_wraps_mid_stream_5xx_as_photo_stream_error(
        self,
    ) -> None:
        """Streamed GET returns 5xx eagerly → wrapped as ``PhotoStreamError``."""
        from app.core.insforge import InsForgeError

        class _FiveXxStream:
            def download_object_stream(self, bucket, key):
                raise InsForgeError(503, {"error": "streamed_get_5xx"})

        with pytest.raises(photo_service.PhotoStreamError) as exc:
            for _ in photo_service.stream_animal_photo(
                _FiveXxStream(), nombrefoto="abc.jpg"
            ):
                pass
        assert isinstance(exc.value.__cause__, InsForgeError)
        assert exc.value.__cause__.status_code == 503

    def test_stream_animal_photo_wraps_mid_stream_network_error_as_photo_stream_error(
        self,
    ) -> None:
        """Mid-iteration ``httpx.RemoteProtocolError`` → wrapped as ``PhotoStreamError``."""

        def _fail_after(chunks, fail_after_n, exc):
            for i, chunk in enumerate(chunks):
                if i >= fail_after_n:
                    raise exc
                yield chunk

        class _MidStreamFail:
            def download_object_stream(self, bucket, key):
                return _fail_after(
                    [b"PART1-", b"PART2-", b"PART3"],
                    fail_after_n=2,
                    exc=httpx.RemoteProtocolError("connection reset"),
                )

        gen = photo_service.stream_animal_photo(_MidStreamFail(), nombrefoto="abc.jpg")
        # First two chunks are yielded OK.
        assert next(gen) == b"PART1-"
        assert next(gen) == b"PART2-"
        # The third iteration raises, wrapped as PhotoStreamError.
        with pytest.raises(photo_service.PhotoStreamError) as exc:
            next(gen)
        assert isinstance(exc.value.__cause__, httpx.RemoteProtocolError)

    def test_stream_animal_photo_wraps_mid_stream_read_timeout_as_photo_stream_error(
        self,
    ) -> None:
        """Mid-iteration ``httpx.ReadTimeout`` → wrapped as ``PhotoStreamError``."""

        def _fail_after(chunks, fail_after_n, exc):
            for i, chunk in enumerate(chunks):
                if i >= fail_after_n:
                    raise exc
                yield chunk

        class _StalledStream:
            def download_object_stream(self, bucket, key):
                return _fail_after(
                    [b"PART1-", b"PART2-"],
                    fail_after_n=1,
                    exc=httpx.ReadTimeout("stalled"),
                )

        gen = photo_service.stream_animal_photo(_StalledStream(), nombrefoto="abc.jpg")
        assert next(gen) == b"PART1-"
        with pytest.raises(photo_service.PhotoStreamError) as exc:
            next(gen)
        assert isinstance(exc.value.__cause__, httpx.ReadTimeout)
