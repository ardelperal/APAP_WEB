"""Strict TDD tests for the PR4a InsForge storage contract spike.

The spike is intentionally read-only. These tests pin the operator-safe
contract before PR4b adds any media upload/download implementation.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from migration.storage_spike import (
    MUTATION_METHODS,
    MutationRefusedError,
    ReadOnlyProbeHttpClient,
    StorageProbeConfig,
    main,
    probe_download_strategy,
    write_discovery_document,
)

SAFE_SENTINEL_PATH = "apap-photos/0123456789abcdef.jpg"
SERVICE_KEY = "ik_live_secret_for_tests"
RETURNED_URL = "https://storage.example.local/private/sentinel.jpg?token=download-secret"


def _json_response(status_code: int, body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        headers={"Content-Type": "application/json", "X-Trace-Id": "trace-secret"},
    )


def _happy_transport(calls: list[tuple[str, str, str | None]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (
                request.method,
                request.url.path,
                request.headers.get("Authorization"),
            )
        )
        if request.method == "GET" and request.url.path == "/api/storage/downloadStrategy":
            assert request.url.params["path"] == SAFE_SENTINEL_PATH
            assert request.url.params["expiresIn"] == "3600"
            assert request.headers.get("Authorization") == f"Bearer {SERVICE_KEY}"
            return _json_response(
                200,
                {
                    "method": "GET",
                    "url": RETURNED_URL,
                    "expiresAt": "2026-07-12T00:00:00Z",
                },
            )
        if request.method == "HEAD" and request.url.path == "/private/sentinel.jpg":
            if request.headers.get("Authorization") == f"Bearer {SERVICE_KEY}":
                return httpx.Response(
                    200,
                    headers={
                        "Content-Type": "image/jpeg",
                        "Content-Length": "10",
                    },
                )
            return _json_response(401, {"error": "missing bearer"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def _config() -> StorageProbeConfig:
    return StorageProbeConfig(
        base_url="https://example.insforge.app",
        service_key=SERVICE_KEY,
        storage_path=SAFE_SENTINEL_PATH,
    )


def test_download_strategy_supported_shape_pins_endpoint_and_auth_header() -> None:
    """2xx strategy + authenticated HEAD proves the canonical read path."""
    calls: list[tuple[str, str, str | None]] = []

    result = probe_download_strategy(_config(), transport=_happy_transport(calls))

    evidence = result.to_machine_dict()
    assert evidence["status"] == "supported"
    assert evidence["pr4b_gate"] == "PASS"
    assert evidence["canonical_endpoint"] == "/api/storage/downloadStrategy"
    assert evidence["required_auth_header"] == "Authorization: Bearer <service_key>"
    assert evidence["strategy_status_code"] == 200
    assert evidence["returned_url"] == "<redacted-url>"
    assert evidence["strategy_body_shape"] == {
        "expiresAt": "str",
        "method": "str",
        "url": "url",
    }
    assert evidence["object_head"] == {
        "with_auth_status": 200,
        "without_auth_status": 401,
    }
    assert len(evidence["evidence_hash"]) == 64
    assert calls == [
        ("GET", "/api/storage/downloadStrategy", f"Bearer {SERVICE_KEY}"),
        ("HEAD", "/private/sentinel.jpg", None),
        ("HEAD", "/private/sentinel.jpg", f"Bearer {SERVICE_KEY}"),
    ]


def test_returned_url_authenticated_404_pins_endpoint_and_auth_header() -> None:
    """A protected returned-URL 404 still proves endpoint routing and auth."""
    calls: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("Authorization")))
        if request.method == "GET" and request.url.path == "/api/storage/downloadStrategy":
            return _json_response(
                200,
                {
                    "method": "GET",
                    "url": RETURNED_URL,
                    "expiresAt": "2026-07-12T00:00:00Z",
                },
            )
        if request.method == "HEAD" and request.url.path == "/private/sentinel.jpg":
            if request.headers.get("Authorization") == f"Bearer {SERVICE_KEY}":
                return httpx.Response(404)
            return _json_response(401, {"error": "missing bearer"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    result = probe_download_strategy(_config(), transport=httpx.MockTransport(handler))

    evidence = result.to_machine_dict()
    assert evidence["status"] == "object_not_found"
    assert evidence["pr4b_gate"] == "PASS"
    assert evidence["canonical_endpoint"] == "/api/storage/downloadStrategy"
    assert evidence["required_auth_header"] == "Authorization: Bearer <service_key>"
    assert evidence["object_head"] == {
        "with_auth_status": 404,
        "without_auth_status": 401,
    }
    assert calls == [
        ("GET", "/api/storage/downloadStrategy", f"Bearer {SERVICE_KEY}"),
        ("HEAD", "/private/sentinel.jpg", None),
        ("HEAD", "/private/sentinel.jpg", f"Bearer {SERVICE_KEY}"),
    ]


@pytest.mark.parametrize(
    ("status_code", "expected_status"),
    [(401, "auth_failed"), (403, "forbidden")],
)
def test_download_strategy_auth_failures_are_categorical_and_block_pr4b(
    status_code: int,
    expected_status: str,
) -> None:
    """401 and 403 are distinguishable, fail closed, and do not leak bodies."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return _json_response(status_code, {"message": "ik_live_secret_for_tests rejected"})

    result = probe_download_strategy(
        _config(),
        transport=httpx.MockTransport(handler),
    )

    evidence = result.to_machine_dict()
    assert evidence["status"] == expected_status
    assert evidence["pr4b_gate"] == "BLOCKED"
    assert evidence["strategy_status_code"] == status_code
    assert evidence["strategy_body_shape"] == {"message": "str"}
    assert "ik_live_secret_for_tests" not in json.dumps(evidence, sort_keys=True)
    assert calls == ["GET"]


def test_strategy_endpoint_authenticated_404_pins_endpoint_and_auth_header() -> None:
    """A protected strategy-level 404 proves endpoint routing and auth."""
    calls: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("Authorization")))
        assert request.method == "GET"
        assert request.url.path == "/api/storage/downloadStrategy"
        if request.headers.get("Authorization") == f"Bearer {SERVICE_KEY}":
            return _json_response(404, {"error": "object not found", "path": SAFE_SENTINEL_PATH})
        return _json_response(401, {"error": "missing bearer"})

    result = probe_download_strategy(_config(), transport=httpx.MockTransport(handler))

    evidence = result.to_machine_dict()
    assert evidence["status"] == "object_not_found"
    assert evidence["pr4b_gate"] == "PASS"
    assert evidence["canonical_endpoint"] == "/api/storage/downloadStrategy"
    assert evidence["required_auth_header"] == "Authorization: Bearer <service_key>"
    assert evidence["strategy_status_code"] == 404
    assert evidence["strategy_without_auth_status_code"] == 401
    assert evidence["object_head"] == {
        "with_auth_status": None,
        "without_auth_status": None,
    }
    assert SAFE_SENTINEL_PATH not in json.dumps(evidence, sort_keys=True)
    assert calls == [
        ("GET", "/api/storage/downloadStrategy", f"Bearer {SERVICE_KEY}"),
        ("GET", "/api/storage/downloadStrategy", None),
    ]


def test_cli_loads_credentials_from_settings_env_file_without_echoing_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator CLI uses the existing Settings/.env loader, not raw env only."""
    fake_secret = "ik_from_temp_env_file_should_not_echo"
    doc_path = tmp_path / "storage-contract-2026-Q3.md"
    (tmp_path / ".env").write_text(
        "APAP_INSFORGE_URL=https://example.insforge.app\n"
        f"APAP_INSFORGE_SERVICE_KEY={fake_secret}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APAP_INSFORGE_URL", raising=False)
    monkeypatch.delenv("APAP_INSFORGE_SERVICE_KEY", raising=False)

    from app.core.config import get_settings

    get_settings.cache_clear()
    calls: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("Authorization")))
        assert request.method == "GET"
        assert request.url.path == "/api/storage/downloadStrategy"
        if request.headers.get("Authorization") == f"Bearer {fake_secret}":
            return _json_response(404, {"error": "object not found", "path": SAFE_SENTINEL_PATH})
        return _json_response(401, {"error": "missing bearer"})

    try:
        stream = io.StringIO()
        rc = main(
            [
                "--probe",
                "download_strategy",
                "--path",
                SAFE_SENTINEL_PATH,
                "--output",
                str(doc_path),
            ],
            stream=stream,
            transport=httpx.MockTransport(handler),
        )
    finally:
        get_settings.cache_clear()

    output = stream.getvalue()
    text = doc_path.read_text(encoding="utf-8")
    payload = json.loads(output)
    assert rc == 0
    assert payload["status"] == "object_not_found"
    assert payload["pr4b_gate"] == "PASS"
    assert payload["required_auth_header"] == "Authorization: Bearer <service_key>"
    assert fake_secret not in output
    assert fake_secret not in text
    assert RETURNED_URL not in output
    assert RETURNED_URL not in text
    assert {method for method, _, _ in calls} == {"GET"}
    assert {method for method, _, _ in calls}.isdisjoint(MUTATION_METHODS)


def test_download_strategy_404_blocks_when_endpoint_or_sentinel_is_unproven() -> None:
    """404 is a pinned category so PR4b cannot start on an assumed path."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/storage/downloadStrategy"
        return _json_response(404, {"error": "not found", "path": SAFE_SENTINEL_PATH})

    result = probe_download_strategy(
        _config(),
        transport=httpx.MockTransport(handler),
    )

    evidence = result.to_machine_dict()
    assert evidence["status"] == "not_found"
    assert evidence["pr4b_gate"] == "BLOCKED"
    assert evidence["strategy_status_code"] == 404
    assert evidence["storage_path"] == "<redacted-path>"
    assert SAFE_SENTINEL_PATH not in json.dumps(evidence, sort_keys=True)


def test_mutation_methods_are_refused_before_network_and_405_is_categorized() -> None:
    """The spike never sends POST/PUT/PATCH/DELETE; server 405 is still reported."""
    mutation_calls: list[str] = []

    def mutation_handler(request: httpx.Request) -> httpx.Response:
        mutation_calls.append(request.method)
        return _json_response(500, {"error": "mutation reached server"})

    with ReadOnlyProbeHttpClient(
        base_url="https://example.insforge.app",
        service_key=SERVICE_KEY,
        transport=httpx.MockTransport(mutation_handler),
    ) as client:
        for method in MUTATION_METHODS:
            with pytest.raises(MutationRefusedError):
                client.request(method, "/api/storage/buckets/apap-photos/upload-strategy")

    assert mutation_calls == []

    def method_not_allowed_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return _json_response(405, {"error": "method not allowed"})

    result = probe_download_strategy(
        _config(),
        transport=httpx.MockTransport(method_not_allowed_handler),
    )

    assert result.to_machine_dict()["status"] == "method_not_allowed"
    assert result.to_machine_dict()["pr4b_gate"] == "BLOCKED"


def test_redacted_discovery_document_contains_no_secrets_or_raw_urls(
    tmp_path: Path,
) -> None:
    """The evidence doc is useful to PR4b without exposing keys or object URLs."""
    calls: list[tuple[str, str, str | None]] = []
    result = probe_download_strategy(_config(), transport=_happy_transport(calls))
    doc_path = tmp_path / "storage-contract-2026-Q3.md"

    write_discovery_document(result, doc_path)

    text = doc_path.read_text(encoding="utf-8")
    assert "# Storage Contract Discovery — 2026 Q3" in text
    assert "Verdict: PASS" in text
    assert "PR4b gate: PASS" in text
    assert "Canonical endpoint: `/api/storage/downloadStrategy`" in text
    assert "Authorization: Bearer <service_key>" in text
    assert result.evidence_hash in text
    assert SERVICE_KEY not in text
    assert "download-secret" not in text
    assert RETURNED_URL not in text
    assert SAFE_SENTINEL_PATH not in text


def test_evidence_hash_is_deterministic_and_repeated_probe_never_writes() -> None:
    """Re-running the probe only repeats safe reads and yields identical evidence."""
    calls: list[tuple[str, str, str | None]] = []

    first = probe_download_strategy(_config(), transport=_happy_transport(calls))
    second = probe_download_strategy(_config(), transport=_happy_transport(calls))

    assert first.evidence_hash == second.evidence_hash
    assert first.to_machine_dict() == second.to_machine_dict()
    assert {method for method, _, _ in calls} <= {"GET", "HEAD"}
    assert {method for method, _, _ in calls}.isdisjoint(MUTATION_METHODS)
    assert len(calls) == 6


def test_network_timeout_fails_closed_without_leaking_exception_url() -> None:
    """Network and timeout failures are categorical, blocked, and redacted."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException(
            "timed out while contacting https://example.insforge.app/secret?token=abc"
        )

    result = probe_download_strategy(
        _config(),
        transport=httpx.MockTransport(handler),
    )

    evidence = result.to_machine_dict()
    serialized = json.dumps(evidence, sort_keys=True)
    assert evidence["status"] == "timeout"
    assert evidence["pr4b_gate"] == "BLOCKED"
    assert "token=abc" not in serialized
    assert "secret" not in serialized
    assert "example.insforge.app" not in serialized


def test_cli_without_credentials_writes_blocked_document_without_network(
    tmp_path: Path,
) -> None:
    """Missing operator env blocks PR4b but remains mergeable and read-only."""
    doc_path = tmp_path / "storage-contract-2026-Q3.md"
    stream = io.StringIO()
    network_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        network_calls.append(request.method)
        return _json_response(500, {"error": "should not call network"})

    rc = main(
        [
            "--probe",
            "download_strategy",
            "--path",
            SAFE_SENTINEL_PATH,
            "--output",
            str(doc_path),
        ],
        env={},
        stream=stream,
        transport=httpx.MockTransport(handler),
    )

    payload = json.loads(stream.getvalue())
    text = doc_path.read_text(encoding="utf-8")
    assert rc == 3
    assert payload["status"] == "missing_credentials"
    assert payload["pr4b_gate"] == "BLOCKED"
    assert "Verdict: BLOCKED" in text
    assert "Live probe did not run: missing APAP_INSFORGE_URL/APAP_INSFORGE_SERVICE_KEY" in text
    assert network_calls == []
