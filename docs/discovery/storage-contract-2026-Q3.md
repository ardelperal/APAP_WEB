# Storage Contract Discovery — 2026 Q3

## Scope

PR4a records the deployed InsForge storage contract needed by PR4b.
Agent-side probe remains GET/HEAD-only and refuses POST, PUT, PATCH, and DELETE
before any network transport receives a request. Operator-supplied reversible
sentinel evidence is persisted only as redacted status/shape categories.
The artifact never records service keys, credentialed URLs, raw body values,
or object bytes.

## Methodology

- Candidate endpoint probed: `/api/storage/buckets/apap-photos/download-strategy/objects/{key}`.
- Candidate object path: `<redacted-path>`.
- Strategy verification: authenticated GET 200; unauthenticated GET 401.
- Returned presigned URL verification: HEAD 200 with and without bearer.
- Recorded evidence is a redacted shape: status codes, header names, body field
  types, endpoint path, auth-header behavior, and deterministic evidence hash.

## Evidence

```json
{
  "bucket": {
    "bucket_name": "apap-photos",
    "is_public": false
  },
  "canonical_endpoint": "/api/storage/buckets/apap-photos/download-strategy/objects/{key}",
  "cleanup": {
    "leftovers": false,
    "post_list_object_count": 0,
    "post_list_total": 0,
    "sentinel_delete_status_code": 200,
    "success": true
  },
  "decision_reason": "Reversible operator sentinel proved strategy auth, presigned download, three-step S3 upload confirmation, and cleanup.",
  "download_method": "presigned",
  "evidence_hash": "62f025e2df0d4fe92e61baa7cf001f34cb3eccdf525564d9ca13bc636bfdac07",
  "object_head": {
    "with_auth_status": 200,
    "without_auth_status": 200
  },
  "pr4b_gate": "PASS",
  "probe": "storage_contract_operator_sentinel",
  "required_auth_header": "Authorization: Bearer <service_key>",
  "returned_url": "<redacted-url>",
  "returned_url_auth": "self-authenticating",
  "returned_url_exposure": "server-stream-only",
  "schema": "apap.storage-contract-probe/v1",
  "status": "supported",
  "storage_path": "<redacted-path>",
  "strategy_body_shape": {
    "expiresAt": "str",
    "method": "str",
    "url": "url"
  },
  "strategy_headers": [],
  "strategy_status_code": 200,
  "strategy_without_auth_body_shape": {
    "error": "str",
    "message": "str",
    "nextActions": "list",
    "statusCode": "int"
  },
  "strategy_without_auth_status_code": 401,
  "upload_contract": {
    "confirm_required": true,
    "confirm_status_code": 201,
    "protocol": "s3-compatible",
    "steps": [
      "request_upload_strategy",
      "transfer_object",
      "confirm_upload"
    ],
    "strategy_fields_present": true,
    "transfer_method_rule": "POST when fields present; PUT when fields absent"
  }
}
```

Evidence hash: `62f025e2df0d4fe92e61baa7cf001f34cb3eccdf525564d9ca13bc636bfdac07`

## Decision

- Verdict: PASS
- PR4b gate: PASS
- Canonical endpoint: `/api/storage/buckets/apap-photos/download-strategy/objects/{key}`
- Required auth header: `Authorization: Bearer <service_key>`
- Decision reason: Reversible operator sentinel proved strategy auth, presigned download, three-step S3 upload confirmation, and cleanup.
- Operator-supplied reversible sentinel evidence: S3-compatible three-step upload; `confirmRequired=true`; confirm status 201; cleanup restored object_count=0 and total=0.
- Returned presigned URL: self-authenticating; `server-stream-only`; must not be exposed to browser/client.
