"""PR2 / M0 private bucket invariant tests.

No test in this file mutates a real InsForge backend. HTTP calls use
``httpx.MockTransport`` or in-memory fakes, and the CLI receives an
injected client.
"""

from __future__ import annotations

import io
import json
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient, InsForgeError
from migration import legacy_reader
from migration.apply import apply_legacy_to_web
from migration.cli import main
from tests.migration.conftest import FakeInsForge  # noqa: TID251

APAP_PHOTOS = "apap-photos"


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def test_private_bucket_invariant_existing_private_readback() -> None:
    """Existing private bucket is accepted without a create call."""
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        calls.append((request.method, request.url.path, body))
        assert request.headers.get("Authorization") == "Bearer ik_test"
        assert request.method == "GET"
        return _json_response(
            200,
            {"buckets": [{"bucketName": APAP_PHOTOS, "isPublic": False}]},
        )

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )
    try:
        bucket = client.ensure_bucket(APAP_PHOTOS, is_public=False)
    finally:
        client.close()

    assert bucket["bucketName"] == APAP_PHOTOS
    assert bucket["isPublic"] is False
    assert calls == [("GET", "/api/storage/buckets", {})]


def test_public_bucket_aborts_fail_closed() -> None:
    """A public ``apap-photos`` bucket is a hard privacy violation."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return _json_response(
            200,
            {"buckets": [{"bucketName": APAP_PHOTOS, "isPublic": True}]},
        )

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(InsForgeError) as excinfo:
            client.ensure_bucket(APAP_PHOTOS, is_public=False)
    finally:
        client.close()

    assert excinfo.value.status_code == 409
    assert excinfo.value.body["error"] == "bucket_public_violation"
    assert APAP_PHOTOS in excinfo.value.body["message"]


def test_missing_bucket_auto_create_is_private_and_idempotent() -> None:
    """Missing bucket is created private once, then replay is a no-op."""
    buckets: list[dict[str, Any]] = []
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        calls.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path == "/api/storage/buckets":
            return _json_response(200, {"buckets": list(buckets)})
        if request.method == "POST" and request.url.path == "/api/storage/buckets":
            assert body == {"bucketName": APAP_PHOTOS, "isPublic": False}
            buckets.append({"bucketName": APAP_PHOTOS, "isPublic": False})
            return _json_response(
                200,
                {"message": "Bucket created successfully", "bucket": APAP_PHOTOS},
            )
        return _json_response(500, {"error": "unexpected_call"})

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )
    try:
        first = client.ensure_bucket(APAP_PHOTOS, is_public=False)
        second = client.ensure_bucket(APAP_PHOTOS, is_public=False)
    finally:
        client.close()

    assert first == {"bucketName": APAP_PHOTOS, "isPublic": False}
    assert second == {"bucketName": APAP_PHOTOS, "isPublic": False}
    assert len(buckets) == 1
    assert [method for method, _, _ in calls].count("POST") == 1
    assert all(call[2].get("isPublic") is False for call in calls if call[0] == "POST")


def test_cli_ensure_bucket_check_only_confirms_existing_private_bucket() -> None:
    """Operator checkpoint can read back private state without writing."""

    class BucketFake(FakeInsForge):
        def get_bucket(self, bucket_name: str) -> dict[str, Any] | None:
            assert bucket_name == APAP_PHOTOS
            return {"bucketName": APAP_PHOTOS, "isPublic": False}

        def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, Any]:
            raise AssertionError("check-only must not create or mutate buckets")

    stream = io.StringIO()
    rc = main(
        ["ensure-bucket", APAP_PHOTOS, "--check-only"],
        web_client=BucketFake(),
        stream=stream,
    )

    assert rc == 0
    output = stream.getvalue()
    assert f"bucket={APAP_PHOTOS}" in output
    assert "isPublic=false" in output
    assert "status=exists" in output


def test_cli_ensure_bucket_missing_auto_create() -> None:
    """Mutation path creates a missing bucket private and reports it."""

    class BucketFake(FakeInsForge):
        def __init__(self) -> None:
            super().__init__()
            self.buckets: dict[str, dict[str, Any]] = {}
            self.create_calls = 0

        def get_bucket(self, bucket_name: str) -> dict[str, Any] | None:
            return self.buckets.get(bucket_name)

        def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, Any]:
            assert is_public is False
            self.create_calls += 1
            self.buckets.setdefault(
                bucket_name,
                {"bucketName": bucket_name, "isPublic": False},
            )
            return self.buckets[bucket_name]

    fake = BucketFake()
    stream = io.StringIO()

    rc = main(["ensure-bucket", APAP_PHOTOS], web_client=fake, stream=stream)

    assert rc == 0
    assert fake.create_calls == 1
    assert fake.buckets[APAP_PHOTOS]["isPublic"] is False
    assert "status=created" in stream.getvalue()


def test_cli_ensure_bucket_rejects_unsafe_bucket_name() -> None:
    """Unsafe bucket names fail before any HTTP call is attempted."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("unsafe bucket name must not reach the network")

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )
    stream = io.StringIO()
    try:
        rc = main(["ensure-bucket", "apap/photos"], web_client=client, stream=stream)
    finally:
        client.close()

    assert rc == 2
    assert "unsafe bucket name" in stream.getvalue()


def test_apply_ensures_private_bucket_before_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Apply pre-flight prepares storage infra before lock/read work."""
    events: list[str] = []

    class BucketFake(FakeInsForge):
        def __init__(self) -> None:
            super().__init__()
            self.bucket: dict[str, Any] | None = None

        def get_bucket(self, bucket_name: str) -> dict[str, Any] | None:
            events.append("get_bucket")
            return dict(self.bucket) if self.bucket is not None else None

        def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, Any]:
            events.append("ensure_bucket")
            assert bucket_name == APAP_PHOTOS
            assert is_public is False
            self.bucket = {"bucketName": bucket_name, "isPublic": False}
            return dict(self.bucket)

    def fake_acquire_lock(_path) -> None:
        events.append("lock")

    def fake_release_lock(_path) -> None:
        events.append("release")

    def fake_executor(_path: str, _sql: str, _offset: int, _limit: int) -> list[dict[str, Any]]:
        events.append("read")
        return []

    monkeypatch.setattr("migration.apply.acquire_lock", fake_acquire_lock)
    monkeypatch.setattr("migration.apply.release_lock", fake_release_lock)
    legacy_reader.set_legacy_query_executor(fake_executor)
    try:
        result = apply_legacy_to_web(
            BucketFake(),
            "animal",
            legacy_path="/dummy/legacy.accdb",
            lock_path=tmp_path / "migration.lock",
        )
    finally:
        legacy_reader.set_legacy_query_executor(None)

    assert result.applied == 0
    assert result.errors == []
    assert events.index("ensure_bucket") < events.index("lock") < events.index("read")
