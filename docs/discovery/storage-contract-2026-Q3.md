# Storage Contract Discovery — 2026 Q3

## Scope

PR4a empirically probes the deployed InsForge storage read contract needed by PR4b.
The spike is read-only by construction: it may call GET/HEAD only and refuses
POST, PUT, PATCH, and DELETE before any network transport receives a request.
It never creates buckets, uploads objects, deletes objects, logs service keys,
logs credentialed URLs, or captures object bytes.

## Methodology

- Bucket precondition (operator/MCP-attested): `apap-photos` exists, `isPublic=false`, object count `0`.
- Candidate endpoint probed: `/api/storage/downloadStrategy`.
- Candidate object path: `<redacted-path>`.
- Strategy request comparison: authenticated GET returned 404; unauthenticated GET returned 404.
- Returned URL HEAD comparison: not executed because the strategy response exposed no URL.
- Recorded evidence is a redacted shape: status codes, header names, body field
  types, endpoint path, auth-header behavior, and deterministic evidence hash.

## Evidence

```json
{
  "canonical_endpoint": "/api/storage/downloadStrategy",
  "decision_reason": "Storage probe received 404; endpoint or sentinel path is unproven.",
  "evidence_hash": "b363ee26beb599c73db053cf121e99425ca4c419a6f3c390b1c1c787f6391bea",
  "object_head": {
    "with_auth_status": null,
    "without_auth_status": null
  },
  "pr4b_gate": "BLOCKED",
  "probe": "download_strategy",
  "required_auth_header": "unknown",
  "returned_url": null,
  "schema": "apap.storage-contract-probe/v1",
  "status": "not_found",
  "storage_path": "<redacted-path>",
  "strategy_body_shape": "str",
  "strategy_headers": [
    "access-control-allow-credentials",
    "access-control-expose-headers",
    "connection",
    "content-length",
    "content-security-policy",
    "content-type",
    "date",
    "server",
    "vary",
    "x-content-type-options",
    "x-powered-by"
  ],
  "strategy_status_code": 404,
  "strategy_without_auth_status_code": 404
}
```

Evidence hash: `b363ee26beb599c73db053cf121e99425ca4c419a6f3c390b1c1c787f6391bea`

## Decision

- Verdict: BLOCKED
- PR4b gate: BLOCKED
- Pinned canonical endpoint: `unknown`
- Required auth header: `unknown`
- Decision reason: Storage probe received 404; endpoint or sentinel path is unproven.
