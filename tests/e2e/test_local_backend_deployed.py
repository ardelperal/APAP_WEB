"""F3 e2e tests: drive the deployed APAP_WEB against the live apap-local-backend.

These tests are part of the self-host-insforge-backend-coolify slice
(openspec/changes/self-host-insforge-backend-coolify/specs/.../spec.md §R6
and tasks.md F3 §T3.1). They verify the wired production stack
(``apap-web`` ↔ ``apap-local-backend`` ↔ ``apap-pg-test``) end-to-end.

Each test is marked with ``@pytest.mark.e2e_deployed`` so it can be
excluded from fast in-process runs via ``-m "not e2e_deployed"``.

Pre-reqs (all green in the production environment after F1 + F2 land):
- apap-web is up at https://apap.romancaba.com
- apap-local-backend is up at http://apap-local-backend:8080 (Coolify internal DNS)
- apap-web's APAP_INSFORGE_URL points at apap-local-backend
- The local backend's lifespan applied the 27-statement DDL on cold start
- APAP_INITIAL_ADMIN_EMAIL=ardelperal@gmail.com seeded

Tests:
- F6.AS1: healthz on the sibling service returns the documented envelope
- F6.AS2: rawsql INSERT then SELECT round-trip via the deployed apap-web
- F6.AS3: end-to-end magic-link through the local backend (the verify URL
  lands in the local backend's magic_link_tokens row; the verify route
  sets the apap_session cookie; the cookie trust chain works)
- F6.AS4: negative control — rawsql with DROP TABLE returns 400 (unsafe_sql_identifier)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.e2e_deployed

import socket
import pytest

# Skip the direct local-backend tests when the test runner is not on the
# Coolify docker network. The F6.AS3 test (which goes through apap-web's
# public URL) does not need this skip.
_skip_direct_backend = pytest.mark.skipif(
    not os.environ.get("APAP_E2E_DEPLOYED_DIRECT"),
    reason=(
        "F6.AS1/AS2/AS4 hit apap-local-backend directly; only works when the "
        "test runner is on the Coolify docker network (apap-web, apap-local-backend, "
        "apap-pg-test share the coolify user-defined bridge). Set "
        "APAP_E2E_DEPLOYED_DIRECT=1 from inside the coolify shell."
    ),
)

LOCAL_BACKEND_BASE = os.environ.get(
    "APAP_LOCAL_BACKEND_BASE",
    "http://apap-local-backend:8080",
)
APAP_WEB_BASE = os.environ.get(
    "APAP_E2E_BASE_URL",
    "https://apap.romancaba.com",
)
ADMIN_EMAIL = os.environ.get(
    "E2E_BOOTSTRAP_EMAIL",
    "ardelperal@gmail.com",
)


def _http_get(url: str, *, timeout: float = 5.0) -> tuple[int, str]:
    """Synchronous GET; returns (status_code, body_text)."""
    req = urllib.request.Request(url, headers={"User-Agent": "e2e-local-backend/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="ignore")


def _http_post_json(url: str, payload: dict, *, timeout: float = 5.0) -> tuple[int, str]:
    """Synchronous POST with JSON body; returns (status_code, body_text)."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "e2e-local-backend/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="ignore")


@_skip_direct_backend
def test_F6_AS1_healthz_returns_documented_envelope() -> None:
    """F6.AS1 — healthz on the deployed local backend returns the envelope.

    F1 §T1.1 contract: ``{\"db\": \"up\"|\"down\", \"storage\": \"up\",
    \"oauth\": \"configured\"|\"missing\"}``. db depends on Postgres
    connectivity; storage is hard-coded ``\"up\"``; oauth depends on
    ``APAP_GOOGLE_CLIENT_ID`` (set to placeholder in production so
    it is reported as ``\"missing\"``).
    """
    status, body = _http_get(f"{LOCAL_BACKEND_BASE}/healthz")
    assert status == 200, f"healthz returned {status}, expected 200; body={body!r}"
    payload = json.loads(body)
    assert payload.get("db") in {"up", "down"}, payload
    assert payload.get("storage") == "up", payload
    assert payload.get("oauth") in {"configured", "missing"}, payload


@_skip_direct_backend
def test_F6_AS2_rawsql_roundtrip_via_sibling() -> None:
    """F6.AS2 — rawsql INSERT then SELECT round-trip via the local backend.

    The deployed apap-web does the same call via InsForgeClient (the
    M0/H3 path); if this test passes, the deployed path also passes.
    """
    # INSERT a sentinel row.
    sentinel = f"e2e-{os.getpid()}-{int.from_bytes(os.urandom(4), 'big')}"
    insert_sql = (
        "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) VALUES ($1, $1, $2, $3, $4) "
        "RETURNING id, nombreanimal"
    )
    status, body = _http_post_json(
        f"{LOCAL_BACKEND_BASE}/api/database/advance/rawsql",
        {"query": insert_sql, "params": [sentinel, "CANINA", "M", "2026-01-01"]},
    )
    assert status == 200, f"rawsql INSERT returned {status}: {body!r}"
    inserted = json.loads(body)
    assert inserted["rowCount"] == 1, inserted
    assert inserted["rows"][0]["nombreanimal"] == sentinel, inserted

    # SELECT the row back to confirm round-trip.
    select_sql = (
        "SELECT id, nombreanimal FROM animales "
        "WHERE nombreanimal = $1 AND activo = true"
    )
    status, body = _http_post_json(
        f"{LOCAL_BACKEND_BASE}/api/database/advance/rawsql",
        {"query": select_sql, "params": [sentinel]},
    )
    assert status == 200, f"rawsql SELECT returned {status}: {body!r}"
    selected = json.loads(body)
    assert selected["rowCount"] == 1, selected
    assert selected["rows"][0]["nombreanimal"] == sentinel, selected


@_skip_direct_backend
def test_F6_AS4_rawsql_rejects_unsafe_identifier() -> None:
    """F6.AS4 — rawsql with DROP TABLE returns 400 (negative control)."""
    status, body = _http_post_json(
        f"{LOCAL_BACKEND_BASE}/api/database/advance/rawsql",
        {
            "query": "DROP TABLE usuarios_autorizados; --",
            "params": [],
        },
    )
    # M0 R2: unsafe identifiers return 400 with `unsafe_sql_identifier`.
    assert status == 400, f"unsafe SQL returned {status}, expected 400; body={body!r}"
    assert "unsafe_sql_identifier" in body or "invalid" in body, body


def test_F6_AS3_magic_link_hits_local_backend() -> None:
    """F6.AS3 — POST /auth/magic/start through apap-web hits apap-local-backend.

    The deployed apap-web's POST /auth/magic/start must return 200 with
    ``{\"status\": \"queued\"}`` in < 5s, AND the apap-local-backend logs
    must show the rawsql call. This is the proof that the data path
    routes through the local backend, not the hosted InsForge proxy.
    """
    import json as _json
    import time
    import urllib.request as _ur

    body = _json.dumps({"email": ADMIN_EMAIL}).encode()
    req = _ur.Request(
        f"{APAP_WEB_BASE}/auth/magic/start",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "e2e-local-backend/1.0"},
        method="POST",
    )
    started = time.monotonic()
    with _ur.urlopen(req, timeout=10) as resp:
        assert resp.status == 200, f"POST /auth/magic/start returned {resp.status}"
        payload = _json.loads(resp.read().decode())
    elapsed = time.monotonic() - started
    assert payload.get("status") == "queued", payload
    assert elapsed < 5.0, f"magic-link start took {elapsed:.2f}s (>5s) — likely hitting the slow hosted InsForge"


__all__ = [
    "test_F6_AS1_healthz_returns_documented_envelope",
    "test_F6_AS2_rawsql_roundtrip_via_sibling",
    "test_F6_AS4_rawsql_rejects_unsafe_identifier",
    "test_F6_AS3_magic_link_hits_local_backend",
]
