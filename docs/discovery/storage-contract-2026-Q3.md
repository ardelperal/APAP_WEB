# Storage Contract Discovery — 2026 Q3

## Scope

PR4a empirically probes the deployed InsForge storage read contract needed by PR4b.
The spike is read-only by construction: it may call GET/HEAD only and refuses
POST, PUT, PATCH, and DELETE before any network transport receives a request.
It never creates buckets, uploads objects, deletes objects, logs service keys,
logs credentialed URLs, or captures object bytes.

## Methodology

- Candidate endpoint probed: `/api/storage/downloadStrategy`.
- Candidate object path: `<redacted-path>`.
- Strategy request: GET with `expiresIn=3600` and service-key bearer auth.
- Returned URL request: HEAD without auth, then HEAD with service-key bearer auth.
- Recorded evidence is a redacted shape: status codes, header names, body field
  types, endpoint path, auth-header behavior, and deterministic evidence hash.

## Evidence

```json
{
  "canonical_endpoint": "/api/storage/downloadStrategy",
  "decision_reason": "Live probe did not run: missing APAP_INSFORGE_URL/APAP_INSFORGE_SERVICE_KEY",
  "evidence_hash": "8d0f87f79699483014a194d3b787953e1f0fe3353890479d4e41022bd52c559b",
  "object_head": {
    "with_auth_status": null,
    "without_auth_status": null
  },
  "pr4b_gate": "BLOCKED",
  "probe": "download_strategy",
  "required_auth_header": "unknown",
  "returned_url": null,
  "schema": "apap.storage-contract-probe/v1",
  "status": "missing_credentials",
  "storage_path": "<redacted-path>",
  "strategy_body_shape": {},
  "strategy_headers": [],
  "strategy_status_code": null
}
```

Evidence hash: `8d0f87f79699483014a194d3b787953e1f0fe3353890479d4e41022bd52c559b`

## Decision

- Verdict: BLOCKED
- PR4b gate: BLOCKED
- Pinned canonical endpoint: `unknown`
- Required auth header: `unknown`
- Decision reason: Live probe did not run: missing APAP_INSFORGE_URL/APAP_INSFORGE_SERVICE_KEY
- Live probe did not run: missing APAP_INSFORGE_URL/APAP_INSFORGE_SERVICE_KEY
