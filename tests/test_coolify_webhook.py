"""Tests for ``scripts/coolify_webhook.py``.

The Coolify manual github webhook endpoint
(``/webhooks/source/github/events/manual``) verifies the raw JSON body
against ``X-Hub-Signature-256`` using ``manual_webhook_secret_github``.
The deploy job in ``.github/workflows/ci.yml`` MUST POST a real push
payload signed with HMAC SHA-256 — an unsigned curl would be rejected
once the secret is configured, breaking every auto-deploy silently.

This module extracts the signing logic so it can be unit-tested. The
workflow shell still wraps a single ``python scripts/coolify_webhook.py``
call so the prod and test code paths are the same code.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from scripts.coolify_webhook import (
    build_push_payload,
    sign_and_post,
    sign_coolify_payload,
)

_SECRET = "test-secret-abc"


def test_sign_coolify_payload_matches_stdlib_hmac() -> None:
    """The HMAC matches what stdlib ``hmac.new(...).hexdigest()`` produces.

    Pins the wire format: lowercase hex, ``sha256=`` prefix. Any drift
    here would silently break every deploy (Coolify would 401 the
    payload and we would only see a rollback, never a clear error).
    """
    body = b'{"ref":"refs/heads/main","after":"deadbeef"}'
    expected_prefix = "sha256="
    expected_hex = hmac.new(
        _SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()

    sig = sign_coolify_payload(_SECRET, body)

    assert sig.startswith(expected_prefix)
    assert sig[len(expected_prefix):] == expected_hex
    # And the hex itself must be lowercase (GitHub's contract).
    assert sig == sig.lower()


def test_sign_coolify_payload_changes_with_body() -> None:
    """A different body MUST produce a different signature (no caching)."""
    sig_a = sign_coolify_payload(_SECRET, b"hello")
    sig_b = sign_coolify_payload(_SECRET, b"world")

    assert sig_a != sig_b


def test_sign_coolify_payload_changes_with_secret() -> None:
    """A different secret MUST produce a different signature."""
    sig_a = sign_coolify_payload("secret-a", b"same body")
    sig_b = sign_coolify_payload("secret-b", b"same body")

    assert sig_a != sig_b


def test_build_push_payload_includes_required_keys() -> None:
    """The payload MUST include the keys Coolify's manualWebhookApplications reads.

    Coolify v4's controller filters by ``branch`` (from ``ref``) and
    uses ``after`` (commit SHA) to record the deployment. A payload
    missing either key makes the controller fall through to
    "Nothing to do."
    """
    body = build_push_payload(
        ref="refs/heads/main",
        after="deadbeef",
        repo_full_name="ardelperal/APAP_WEB",
        commit_message="feat: ship",
    )

    parsed = json.loads(body)
    assert parsed["ref"] == "refs/heads/main"
    assert parsed["after"] == "deadbeef"
    assert parsed["repository"]["full_name"] == "ardelperal/APAP_WEB"
    # ``commits`` MUST be a non-empty list with at least one message.
    assert isinstance(parsed["commits"], list)
    assert len(parsed["commits"]) >= 1
    assert parsed["commits"][0]["message"] == "feat: ship"


def test_build_push_payload_is_compact_json_bytes() -> None:
    """The payload MUST be the exact bytes that get HMAC-signed.

    A signature computed over re-formatted JSON would not match
    Coolify's recomputation — compact separators (``",", ":"``) keep
    the payload byte-for-byte reproducible across Python versions
    and platforms.
    """
    body = build_push_payload(
        ref="refs/heads/main",
        after="deadbeef",
        repo_full_name="ardelperal/APAP_WEB",
        commit_message="feat: ship",
    )

    assert isinstance(body, bytes)
    # Round-trip: parsed JSON must equal what we wrote (round-trips
    # to the exact same bytes thanks to compact separators).
    assert json.dumps(
        json.loads(body), separators=(",", ":")
    ).encode("utf-8") == body
    # The inter-element separator (`, `) MUST NOT appear — that's the
    # proof compact separators are in effect. (We do not check ``: ``
    # because it can legitimately appear inside string values like
    # commit messages; compact JSON only elides whitespace between
    # structural tokens, not inside strings.)
    assert b", " not in body


def test_sign_and_post_sends_signed_payload() -> None:
    """``sign_and_post`` POSTs the body with HMAC and the GitHub headers.

    Pins the contract Coolify's controller checks: ``Content-Type``,
    ``X-GitHub-Event: push``, ``X-Hub-Signature-256: sha256=<hex>``,
    raw body bytes match what was signed.
    """
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, content=b'{"deployments":[{"message":"ok"}]}')

    transport = httpx.MockTransport(handler)
    status = sign_and_post(
        url="https://coolify.example.com/webhooks/source/github/events/manual",
        secret=_SECRET,
        body=b'{"hello":"world"}',
        transport=transport,
    )

    assert status == 200
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/webhooks/source/github/events/manual")
    # Raw body bytes are what was signed (no re-encoding).
    assert captured["body"] == b'{"hello":"world"}'
    # Headers Coolify checks.
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["headers"]["x-github-event"] == "push"
    # Signature is verifiable from the captured body + the test secret.
    expected = hmac.new(
        _SECRET.encode("utf-8"), captured["body"], hashlib.sha256
    ).hexdigest()
    assert captured["headers"]["x-hub-signature-256"] == f"sha256={expected}"


def test_sign_and_post_raises_on_http_error() -> None:
    """``sign_and_post`` MUST surface HTTP errors so the workflow fails loud.

    Without this, a Coolify outage would silently fail the deploy
    step (curl returns 0 on 4xx). With this, GitHub Actions shows
    ``Process completed with exit code 1`` and the deploy is
    visibly broken.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"upstream down")

    transport = httpx.MockTransport(handler)

    with pytest.raises(httpx.HTTPStatusError) as exc:
        sign_and_post(
            url="https://coolify.example.com/webhooks/source/github/events/manual",
            secret=_SECRET,
            body=b"{}",
            transport=transport,
        )

    assert exc.value.response.status_code == 503
