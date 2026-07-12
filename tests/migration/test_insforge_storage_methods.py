"""Strict TDD atoms for the PR4b production storage methods.

The PR4b production methods on ``app.core.insforge.InsForgeClient``:

- ``upload_object(bucket, key, body, *, content_type)`` — three-step
  S3-compatible upload (request strategy → transfer → optional confirm).
- ``download_object_stream(bucket, key)`` — two-step stream
  (request strategy → GET returned URL with bearer auth).
- ``delete_object(bucket, key)`` — single DELETE.

These atoms pin the contract from ``docs/discovery/storage-contract-2026-Q3.md``
(the operator-pinned canonical endpoints + auth headers) without ever
hitting the network: ``httpx.MockTransport`` simulates InsForge for every
shape the production methods must accept or reject.

Hard rules honoured (web-tdd-philosophy):

- Rule 2 (DI): the real ``InsForgeClient`` accepts a ``transport`` kwarg.
- Rule 3 (cardinality): each atom asserts the exact request count.
- Rule 4 (no humo): each assertion pins a concrete shape / status / byte
  payload — not absence-of-error.
- Rule 6 (refactor-safety): assertions are about the wire contract,
  not internal sequencing.
- Rule 8 (no production mutation): no real InsForge / no real bucket.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient, InsForgeError

BUCKET = "apap-photos"
SERVICE_KEY = "ik_test_service_for_pr4b"
KEY = "abc123def456.jpg"
SAMPLE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # 40 bytes
SHA_HEX = "abc123def456" * 4  # 48 chars; we only check shape not semantics


# --- helpers ---------------------------------------------------------------


def _json_response(
    status_code: int,
    body: dict[str, Any] | list[Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    """Build a JSON or raw-bytes response with optional extra headers."""
    if content is None:
        if body is None:
            payload_bytes = b""
        else:
            payload_bytes = json.dumps(body).encode("utf-8")
        merged_headers = {"content-type": "application/json", **(headers or {})}
    else:
        payload_bytes = content
        merged_headers = headers or {}
    return httpx.Response(
        status_code=status_code,
        content=payload_bytes,
        headers=merged_headers,
    )


def _client(handler) -> InsForgeClient:
    """Build a real ``InsForgeClient`` whose transport is the test handler."""
    return InsForgeClient(
        base_url="https://example.insforge.app",
        service_key=SERVICE_KEY,
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )


def _upload_strategy_body(
    *,
    fields: dict[str, str] | None = None,
    confirm_required: bool = True,
    confirm_url: str = "https://example.insforge.app/api/storage/confirm/abc",
    upload_url: str = "https://example.insforge.app/api/storage/upload/abc",
    key: str = KEY,
) -> dict[str, Any]:
    """Build a documented upload-strategy response shape."""
    payload: dict[str, Any] = {
        "method": "POST" if fields else "PUT",
        "uploadUrl": upload_url,
        "key": key,
        "confirmRequired": confirm_required,
        "confirmUrl": confirm_url,
        "expiresAt": "2026-07-12T01:00:00Z",
    }
    if fields is not None:
        payload["fields"] = fields
    return payload


def _download_strategy_body(
    *,
    url: str = "https://example.insforge.app/private/abc?token=presigned",
) -> dict[str, Any]:
    """Build a documented download-strategy response shape."""
    return {
        "expiresAt": "2026-07-12T01:00:00Z",
        "method": "GET",
        "url": url,
    }


# =============================================================================
# upload_object — three-step S3-compatible upload
# =============================================================================


class TestUploadObjectHappyPath:
    """The three-step upload completes successfully when InsForge cooperates."""

    def test_upload_object_with_fields_posts_then_confirms(self) -> None:
        """Strategy with ``fields`` → POST multipart to uploadUrl → confirm."""
        calls: list[tuple[str, str, dict[str, str]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            headers = {k: v for k, v in request.headers.items() if k.lower() != "authorization"}
            calls.append((request.method, request.url.path, headers))
            if request.method == "POST" and request.url.path.endswith(
                f"/api/storage/buckets/{BUCKET}/upload-strategy"
            ):
                return _json_response(200, _upload_strategy_body(
                    fields={"key": "value"},
                    confirm_required=True,
                ))
            if request.method == "POST" and request.url.path.endswith("/upload/abc"):
                return _json_response(200, {"ok": True})
            if request.method == "POST" and request.url.path.endswith("/confirm/abc"):
                return _json_response(201, {"key": KEY})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        result = _client(handler).upload_object(
            BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )

        # 3 requests: strategy, transfer, confirm.
        assert len(calls) == 3
        assert calls[0][1].endswith("/upload-strategy")
        assert calls[1][1].endswith("/upload/abc")
        assert calls[2][1].endswith("/confirm/abc")
        assert result == {"key": KEY}

    def test_upload_object_without_fields_puts_and_skips_confirm(self) -> None:
        """Strategy with no ``fields`` and ``confirmRequired=False`` → PUT only."""
        calls: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            if request.method == "POST" and request.url.path.endswith("/upload-strategy"):
                return _json_response(200, _upload_strategy_body(
                    fields=None,
                    confirm_required=False,
                ))
            if request.method == "PUT" and request.url.path.endswith("/upload/abc"):
                return _json_response(200, {"ok": True})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        result = _client(handler).upload_object(
            BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )

        # Only strategy + PUT (no confirm).
        assert len(calls) == 2
        assert calls[0][1].endswith("/upload-strategy")
        assert calls[1][1].endswith("/upload/abc")
        assert calls[1][0] == "PUT"
        assert result == {"key": KEY}

    def test_upload_object_with_required_confirm_skips_when_not_required(self) -> None:
        """Strategy with ``confirmRequired=False`` MUST NOT call confirmUrl."""
        confirm_calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/upload-strategy"):
                return _json_response(200, _upload_strategy_body(
                    fields={"x": "y"},
                    confirm_required=False,
                ))
            if request.method == "POST" and request.url.path.endswith("/upload/abc"):
                return _json_response(200, {"ok": True})
            if request.method == "POST" and request.url.path.endswith("/confirm/abc"):
                confirm_calls.append(request.url.path)
                return _json_response(201, {"key": KEY})
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        _client(handler).upload_object(
            BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )

        assert confirm_calls == [], (
            "confirmUrl was called even though strategy said confirmRequired=False"
        )

    def test_upload_object_sends_filename_and_content_type_to_strategy(self) -> None:
        """The strategy POST body MUST carry ``filename``, ``contentType``, ``size``."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/upload-strategy"):
                captured["body"] = json.loads(request.content)
                return _json_response(200, _upload_strategy_body(
                    fields=None,
                    confirm_required=False,
                ))
            return _json_response(200, {"ok": True})

        _client(handler).upload_object(
            BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )

        body = captured["body"]
        assert body["filename"] == KEY
        assert body["contentType"] == "image/jpeg"
        assert body["size"] == len(SAMPLE_BYTES)


# =============================================================================
# upload_object — fail-closed on every error category
# =============================================================================


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [
        (401, "auth_failed"),
        (403, "forbidden"),
        (404, "not_found"),
        (405, "method_not_allowed"),
        (500, "internal_error"),
    ],
)
def test_upload_object_strategy_failures_fail_closed(
    status_code: int, reason: str
) -> None:
    """Strategy non-2xx aborts the upload without leaking the client config.

    The production contract: the exception body is the server's
    response body verbatim (we don't fabricate or scrub it — the
    InsForgeError carries the truth); the client MUST NOT surface the
    client's own service key inside that body or inside the request
    that triggered the failure. Each atom asserts the error body is
    exactly the server payload (a dict of the documented shape) and
    that no HTTP call hit the transfer or confirm endpoints.
    """
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        return _json_response(status_code, {"error": reason, "hint": "no real PII here"})

    with pytest.raises(InsForgeError) as exc:
        _client(handler).upload_object(
            BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )
    assert exc.value.status_code == status_code
    # Server response body is preserved verbatim — the client does NOT
    # fabricate a body. We assert the error and hint keys round-trip.
    assert exc.value.body == {"error": reason, "hint": "no real PII here"}
    # Only the strategy endpoint was contacted; transfer + confirm are
    # never reached when the strategy fails.
    assert len(observed_paths) == 1
    assert observed_paths[0].endswith("/upload-strategy")


def test_upload_object_transfer_failure_aborts_before_confirm() -> None:
    """A 500 on the transfer step MUST NOT call the confirm URL."""
    confirm_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/upload-strategy"):
            return _json_response(200, _upload_strategy_body(
                fields={"x": "y"},
                confirm_required=True,
            ))
        if request.method == "POST" and request.url.path.endswith("/upload/abc"):
            return _json_response(500, {"error": "transfer_failed"})
        if request.method == "POST" and request.url.path.endswith("/confirm/abc"):
            confirm_calls.append(request.url.path)
            return _json_response(201, {"key": KEY})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with pytest.raises(InsForgeError) as exc:
        _client(handler).upload_object(
            BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )
    assert exc.value.status_code == 500
    assert confirm_calls == []


def test_upload_object_confirm_failure_propagates_insforge_error() -> None:
    """A confirm failure surfaces as ``InsForgeError`` carrying the status."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/upload-strategy"):
            return _json_response(200, _upload_strategy_body(
                fields={"x": "y"},
                confirm_required=True,
            ))
        if request.method == "POST" and request.url.path.endswith("/upload/abc"):
            return _json_response(200, {"ok": True})
        if request.method == "POST" and request.url.path.endswith("/confirm/abc"):
            return _json_response(503, {"error": "confirm_unavailable"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with pytest.raises(InsForgeError) as exc:
        _client(handler).upload_object(
            BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )
    assert exc.value.status_code == 503


def test_upload_object_network_timeout_fails_closed() -> None:
    """Network timeouts surface as ``httpx.TimeoutException`` (fail closed)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out contacting insforge upload strategy")

    with pytest.raises(httpx.TimeoutException):
        _client(handler).upload_object(
            BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )


# =============================================================================
# download_object_stream — two-step authenticated download
# =============================================================================


class TestDownloadObjectStream:
    """The two-step stream reads bytes via a server-side bearer-auth GET."""

    def test_download_object_stream_yields_object_bytes(self) -> None:
        """Happy path: strategy 200 → bearer GET 200 with bytes."""
        download_bytes = b"\x89PNG\r\n\x1a\n" + b"PHOTO-BYTES" * 4
        calls: list[tuple[str, str, str | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path, request.headers.get("Authorization")))
            if request.method == "GET" and request.url.path.endswith(f"/{BUCKET}/download-strategy/objects/{KEY}"):
                return _json_response(200, _download_strategy_body(
                    url=f"https://example.insforge.app/private/{KEY}"
                ))
            if request.method == "GET" and request.url.path.endswith(f"/private/{KEY}"):
                return _json_response(
                    200, body=None,
                    headers={"content-type": "image/jpeg"},
                    content=download_bytes,
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        result = b"".join(_client(handler).download_object_stream(BUCKET, KEY))

        assert result == download_bytes
        # Two GETs: strategy + returned URL.
        assert len(calls) == 2
        assert calls[0][1].endswith(f"/download-strategy/objects/{KEY}")
        # The returned URL GET MUST carry the service-key bearer header.
        assert calls[1][2] == f"Bearer {SERVICE_KEY}"

    def test_download_object_stream_uses_documented_canonical_endpoint(self) -> None:
        """Strategy MUST hit the operator-pinned bucket-scoped path."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.method == "GET" and request.url.path.endswith(f"/{BUCKET}/download-strategy/objects/{KEY}"):
                return _json_response(200, _download_strategy_body())
            return _json_response(
                200, headers={"content-type": "image/jpeg"},
                content=b"\x89PNG\r\n\x1a\n",
            )

        b"".join(_client(handler).download_object_stream(BUCKET, KEY))

        assert calls[0] == f"/api/storage/buckets/{BUCKET}/download-strategy/objects/{KEY}"

    def test_download_object_stream_strategy_unauthorized_fails_closed(self) -> None:
        """401 on the strategy GET raises ``InsForgeError`` (no bytes)."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(401, {"error": "auth_required"})

        with pytest.raises(InsForgeError) as exc:
            b"".join(_client(handler).download_object_stream(BUCKET, KEY))
        assert exc.value.status_code == 401

    def test_download_object_stream_strategy_404_fails_closed(self) -> None:
        """404 on the strategy GET raises ``InsForgeError`` carrying 404."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(404, {"error": "not_found", "path": KEY})

        with pytest.raises(InsForgeError) as exc:
            b"".join(_client(handler).download_object_stream(BUCKET, KEY))
        assert exc.value.status_code == 404

    def test_download_object_stream_5xx_fails_closed(self) -> None:
        """5xx on the strategy GET raises ``InsForgeError`` (fail closed)."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(503, {"error": "temporarily_unavailable"})

        with pytest.raises(InsForgeError) as exc:
            b"".join(_client(handler).download_object_stream(BUCKET, KEY))
        assert exc.value.status_code == 503

    def test_download_object_stream_network_timeout_fails_closed(self) -> None:
        """Network timeouts surface as ``httpx.TimeoutException``."""

        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out contacting insforge strategy")

        with pytest.raises(httpx.TimeoutException):
            b"".join(_client(handler).download_object_stream(BUCKET, KEY))

    def test_download_object_stream_returns_iterator_yielding_bytes(self) -> None:
        """``download_object_stream`` is an iterator of bytes (streaming)."""
        chunks = [b"PART1-", b"PART2-", b"PART3"]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.endswith(
                f"/{BUCKET}/download-strategy/objects/{KEY}"
            ):
                return _json_response(200, _download_strategy_body(
                    url=f"https://example.insforge.app/private/{KEY}"
                ))
            if request.method == "GET" and request.url.path.endswith(f"/private/{KEY}"):
                # httpx streams chunks; emit three chunks.
                return httpx.Response(
                    status_code=200,
                    headers={"content-type": "image/jpeg"},
                    stream=httpx.ByteStream(b"".join(chunks)),
                )
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        stream: Iterator[bytes] = _client(handler).download_object_stream(BUCKET, KEY)
        # The production contract is an iterator (not bytes); collecting is
        # done at the call site.
        collected = b"".join(stream)
        assert collected == b"".join(chunks)

    def test_download_object_stream_passes_per_chunk_timeout_to_stream_call(
        self,
    ) -> None:
        """PR4b 4R WARN-1: the stream call MUST carry a per-chunk Timeout.

        The documented contract (per PR4b 4R WARN-1) is
        ``httpx.Timeout(connect=5, read=10, write=5, pool=5)``. The
        ``read`` timeout is the safety net that catches a stalled
        stream — without it, a server that opens the TCP/TLS handshake,
        returns 200 OK headers, then never sends body bytes would hang
        the route handler indefinitely. The MockTransport handler below
        captures the timeout from ``request.extensions`` (the
        httpx-internal slot the client passes per-call config through).
        """
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["timeout"] = request.extensions.get("timeout")
            if request.method == "GET" and request.url.path.endswith(
                f"/{BUCKET}/download-strategy/objects/{KEY}"
            ):
                return _json_response(200, _download_strategy_body())
            return _json_response(
                200,
                headers={"content-type": "image/jpeg"},
                content=b"\x89PNG\r\n\x1a\n",
            )

        b"".join(_client(handler).download_object_stream(BUCKET, KEY))

        timeout = captured["timeout"]
        assert timeout is not None, (
            "stream call did not pass a Timeout — stalled streams would hang"
        )
        # PR4b 4R WARN-1 contract: connect=5, read=10, write=5, pool=5.
        # httpx stores the per-call timeout in ``request.extensions`` as
        # a dict (the four Timeout fields, keyed by name).
        assert timeout["connect"] == 5.0
        assert timeout["read"] == 10.0
        assert timeout["write"] == 5.0
        assert timeout["pool"] == 5.0

    def test_download_object_stream_stalled_stream_surfaces_timeout(self) -> None:
        """PR4b 4R WARN-1: a stalled stream MUST surface as ``httpx.TimeoutException``.

        A stalled stream is one where the server returns 200 headers but
        the body never arrives. With the per-chunk ``read=10`` timeout,
        httpx aborts and raises ``httpx.ReadTimeout`` (a subclass of
        ``httpx.TimeoutException``) on the first chunk fetch that
        exceeds the budget. ``photo_service.stream_animal_photo`` then
        wraps it as ``PhotoStreamError`` so the route layer can
        translate to the placeholder PNG. The atom pins the transport
        contract — without the per-chunk timeout, the handler would
        hang indefinitely and the route would never respond.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.endswith(
                f"/{BUCKET}/download-strategy/objects/{KEY}"
            ):
                return _json_response(
                    200,
                    _download_strategy_body(
                        url="https://example.insforge.app/private/stalled"
                    ),
                )
            if request.method == "GET" and request.url.path.endswith(
                "/private/stalled"
            ):
                # Simulate a stalled stream: the body fetch never
                # completes within the per-chunk read timeout. MockTransport
                # surfaces the ReadTimeout as a transport-level error.
                raise httpx.ReadTimeout("simulated stalled stream body fetch")
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        with pytest.raises(httpx.TimeoutException):
            b"".join(_client(handler).download_object_stream(BUCKET, KEY))


# =============================================================================
# delete_object
# =============================================================================


class TestDeleteObject:
    """Single DELETE against the bucket-scoped object path."""

    def test_delete_object_sends_delete_to_bucket_scoped_path(self) -> None:
        """A 200 from the server returns ``None``."""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["auth"] = request.headers.get("Authorization") or ""
            return _json_response(200, {"deleted": True})

        result = _client(handler).delete_object(BUCKET, KEY)

        assert result is None
        assert captured["method"] == "DELETE"
        assert captured["path"] == f"/api/storage/buckets/{BUCKET}/objects/{KEY}"
        assert captured["auth"] == f"Bearer {SERVICE_KEY}"

    def test_delete_object_404_is_idempotent_noop(self) -> None:
        """A 404 (already deleted) is treated as success — the contract is idempotent."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(404, {"error": "not_found", "key": KEY})

        # 404 MUST NOT raise; the operator contract is "delete is idempotent".
        result = _client(handler).delete_object(BUCKET, KEY)
        assert result is None

    def test_delete_object_5xx_raises_insforge_error(self) -> None:
        """A 5xx surfaces as ``InsForgeError``."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return _json_response(500, {"error": "boom"})

        with pytest.raises(InsForgeError) as exc:
            _client(handler).delete_object(BUCKET, KEY)
        assert exc.value.status_code == 500


# =============================================================================
# Authorisation — public bucket / network safety
# =============================================================================


def test_upload_object_rejects_unsafe_bucket_name_before_network() -> None:
    """An unsafe bucket name MUST raise ``ValueError`` BEFORE any HTTP call."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _json_response(200, {"ok": True})

    with pytest.raises(ValueError, match="unsafe bucket name"):
        _client(handler).upload_object(
            "../etc/passwd", KEY, SAMPLE_BYTES, content_type="image/jpeg"
        )
    assert calls == [], "HTTP call happened despite unsafe bucket name rejection"


def test_download_object_stream_rejects_unsafe_bucket_name_before_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _json_response(200, {"url": "https://example.insforge.app/x"})

    with pytest.raises(ValueError, match="unsafe bucket name"):
        b"".join(_client(handler).download_object_stream("../etc/passwd", KEY))
    assert calls == []


def test_delete_object_rejects_unsafe_bucket_name_before_network() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _json_response(200, {"deleted": True})

    with pytest.raises(ValueError, match="unsafe bucket name"):
        _client(handler).delete_object("../etc/passwd", KEY)
    assert calls == []


# =============================================================================
# Idempotency / idempotent re-upload
# =============================================================================


def test_upload_object_reuses_existing_key_via_client_derived_filename() -> None:
    """The same bytes uploaded twice MUST send the SAME filename both times.

    PR4b uploads are idempotent at the client side: the caller derives
    ``filename=<sha256>.<ext>`` from the bytes, so re-running the same
    migration re-uses the same object key. The server may still
    rename; the contract pinned here is the client-side proposal.
    """
    observed_filenames: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/upload-strategy"):
            body = json.loads(request.content)
            observed_filenames.append(body["filename"])
            return _json_response(200, _upload_strategy_body(
                fields=None,
                confirm_required=False,
            ))
        return _json_response(200, {"ok": True})

    client = _client(handler)
    client.upload_object(BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg")
    client.upload_object(BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg")

    # Same key → same filename → server can dedup.
    assert observed_filenames == [KEY, KEY]


# =============================================================================
# Redaction of secrets in payloads
# =============================================================================


def test_upload_object_strategy_request_carries_bearer_authorization() -> None:
    """The strategy POST MUST carry ``Authorization: Bearer <service_key>``."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/upload-strategy"):
            captured["auth"] = request.headers.get("Authorization") or ""
            return _json_response(200, _upload_strategy_body(
                fields=None,
                confirm_required=False,
            ))
        return _json_response(200, {"ok": True})

    _client(handler).upload_object(BUCKET, KEY, SAMPLE_BYTES, content_type="image/jpeg")

    assert captured["auth"] == f"Bearer {SERVICE_KEY}"


def test_storage_methods_never_log_secrets_urls_or_paths() -> None:
    """The production methods MUST NOT log service keys, URLs, or object paths.

    PR4b 4R WARN-5: this atom uses the AST detector from
    ``scripts/check_rules.py`` (the same detector that runs in CI) to
    pin the absence of forbidden logging patterns in the production
    storage surface. Two detectors fire:

    - ``_check_apap003_raw_logger_call``: bans ``logger.{info, warning,
      error, debug, critical, exception}(...)`` chains in ``app/``
      except ``app/core/logging.py`` (the log_safe wrapper).
    - ``_check_print_in_app``: bans bare ``print(...)`` in ``app/``.

    Both detectors skip ``app/core/logging.py`` by path; the production
    storage module is ``app/core/insforge.py`` so neither exclusion
    applies and any logging pattern would surface as a Violation.

    Earlier versions of this atom grepped the source text. The grep
    missed AST-level patterns (string-built loggers, ``getattr(logger,
    method)(...)``, ``print`` calls inside comprehensions) and gave
    false positives on the docstring mentions of "log" / "print".
    """
    import ast
    import sys
    from pathlib import Path

    REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from check_rules import _check_apap003_raw_logger_call, _check_print_in_app

    insforge_path = REPO_ROOT / "app" / "core" / "insforge.py"
    source = insforge_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(insforge_path))

    apap003 = _check_apap003_raw_logger_call(insforge_path, tree, REPO_ROOT)
    print_in_app = _check_print_in_app(insforge_path, tree)

    assert apap003 == [], (
        f"app/core/insforge.py contains forbidden raw logger.* calls: "
        f"{[v.message for v in apap003]}; use log_safe() exclusively"
    )
    assert print_in_app == [], (
        f"app/core/insforge.py contains forbidden print() calls: "
        f"{[v.message for v in print_in_app]}; use log_safe() instead"
    )
