"""Coolify manual github webhook signing + POST helper.

Extracted from the inline ``.github/workflows/ci.yml`` heredoc so the
HMAC-SHA-256 computation, payload shape, and header contract are
unit-testable. The workflow now shells out to this module via
``python scripts/coolify_webhook.py`` so the prod and test paths are
the same code.

Contract (pinned by tests/test_coolify_webhook.py + spec at
openspec/changes/ci-cd-foundation/specs/ci-cd-pipeline/spec.md):

- Endpoint: ``POST /webhooks/source/github/events/manual``
- Body: minimal GitHub push payload with ``ref``, ``after``,
  ``repository.full_name``, and ``commits[].message``
- Headers: ``Content-Type: application/json``,
  ``X-GitHub-Event: push``, ``X-Hub-Signature-256: sha256=<hex>``
- Signature: HMAC SHA-256 over the exact raw JSON body bytes
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from typing import Any

import httpx


def sign_coolify_payload(secret: str, body: bytes) -> str:
    """Return the ``X-Hub-Signature-256`` header value for the given body.

    GitHub's wire format: lowercase hex digest, ``sha256=`` prefix.
    Coolify v4's ``manual`` endpoint recomputes this exact value
    server-side using ``manual_webhook_secret_github`` and rejects
    (with a 401 inside the controller) any mismatch.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_push_payload(
    *,
    ref: str,
    after: str,
    repo_full_name: str,
    commit_message: str,
) -> bytes:
    """Build the compact JSON body Coolify's ``manualWebhookApplications`` reads.

    The keys here are not decorative — Coolify v4's controller filters
    the candidate app list by ``branch`` (from ``ref``) and records
    the deployment under ``after`` (the commit SHA). A payload
    missing either key makes the controller fall through to
    "Nothing to do."

    ``commits`` MUST be a non-empty list with at least one ``message``
    entry — Coolify uses the latest commit message for the audit log
    line that appears on the deploy card.
    """
    payload: dict[str, Any] = {
        "ref": ref,
        "after": after,
        "repository": {"full_name": repo_full_name},
        "commits": [
            {
                "message": commit_message,
                "added": [],
                "removed": [],
                "modified": [],
            }
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def sign_and_post(
    *,
    url: str,
    secret: str,
    body: bytes,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> int:
    """POST the signed body to the Coolify webhook.

    Returns the HTTP status code on success. Raises ``httpx.HTTPStatusError``
    on any 4xx/5xx so the workflow step fails loud instead of silently
    rolling back at the healthcheck.

    The ``transport`` parameter is injected so unit tests can use
    ``httpx.MockTransport``; the real workflow lets httpx build a
    default transport from the env.
    """
    signature = sign_coolify_payload(secret, body)
    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": signature,
            },
        )
        response.raise_for_status()
        return response.status_code


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main() -> int:
    """CLI entry point: read env, build payload, sign and POST.

    Used by ``.github/workflows/ci.yml`` as a single Python call
    instead of an inline heredoc, so the deploy step is shorter and
    the signing code is unit-tested in tests/test_coolify_webhook.py.

    Required env:
        COOLIFY_WEBHOOK_URL    — the manual endpoint
        COOLIFY_WEBHOOK_SECRET  — the app's manual_webhook_secret_github
        GITHUB_REF              — e.g. ``refs/heads/main``
        GITHUB_SHA              — full commit SHA
        GITHUB_REPOSITORY       — ``owner/repo``
        COMMIT_MESSAGE          — message of the deploy commit
    """
    _pin_output_encoding()
    url = os.environ.get("COOLIFY_WEBHOOK_URL")
    secret = os.environ.get("COOLIFY_WEBHOOK_SECRET")
    if not url or not secret:
        print("::error::missing COOLIFY_WEBHOOK_URL or COOLIFY_WEBHOOK_SECRET", file=sys.stderr)
        return 1
    body = build_push_payload(
        ref=os.environ.get("GITHUB_REF", "refs/heads/main"),
        after=os.environ.get("GITHUB_SHA", "HEAD"),
        repo_full_name=os.environ.get("GITHUB_REPOSITORY", "ardelperal/APAP_WEB"),
        commit_message=os.environ.get("COMMIT_MESSAGE", "deploy"),
    )
    status = sign_and_post(url=url, secret=secret, body=body)
    print(f"::notice::Coolify webhook returned {status}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI exercised in CI
    raise SystemExit(main())
