# live-migration-private-photo-storage

## Purpose

Storage contract for animal photos migrated from `URLDirectorioDocumentacion` to the LocalBackend `apap-photos` bucket. Bucket MUST be private; display MUST require an authorized session; uploads MUST be SHA-256-keyed and idempotent; orphans and duplicates MUST be detectable and cleanable; missing/corrupt/unsupported photos MUST NOT abort migration.

## Requirements

### Requirement: Private Bucket Invariant

The `apap-photos` LocalBackend bucket MUST have `isPublic=False`. Pre-flight MUST verify and abort the apply with exit code 5 if the bucket is public or missing.

#### Scenario: Pre-flight rejects public bucket

- GIVEN a bucket `apap-photos` with `isPublic=True`
- WHEN `apap-migrate apply --table animal` runs
- THEN pre-flight aborts with `bucket_public_violation` and exit code 5
- AND the message instructs the operator to recreate the bucket private

#### Scenario: Pre-flight creates missing bucket

- GIVEN bucket `apap-photos` does not exist
- WHEN `apap-migrate apply --table animal` runs with infra permission
- THEN the bucket is created with `isPublic=False` via LocalBackend MCP
- AND the apply proceeds

### Requirement: Authenticated Display Only

`GET /animales/{animal_id}/foto` MUST require an authorized session. (`animal_id` is the `animales.id` UUID PK — NCHIP is a natural-key lookup column, NEVER a route identifier.) Without a session, the route MUST return HTTP 302 to `/login`. The route MUST NOT return a public URL or any signed URL accessible to anonymous callers. Bytes MUST be streamed from the LocalBackend object store using server-side credentials via the documented two-step download flow: `GET /api/storage/downloadStrategy?path=<key>&expiresIn=<seconds>` → server-side `GET` of the returned URL via `httpx.Client.stream` with the auth header confirmed by the PR4 live, read-only spike (see "Storage contract spike" requirement below).

> **Why UUID route (Correction for route identifier).** The route identifier is the **animal UUID** (`animales.id`, the primary key) via `/animales/{id}/foto`. The natural key `NCHIP` is a separate indexed column and can be used as a lookup but is NOT the route identifier. This avoids collisions when two animals share an `NCHIP` (data quality fix in flight per issue #148) and matches the existing web app convention of using `id` UUID in route paths. The previous design said "prefer existing UUID route unless a proven NCHIP route is required" — there is no proven NCHIP-route requirement; we use UUID.

#### Scenario: Anonymous request redirects to login

- GIVEN no session cookie
- WHEN `GET /animales/<uuid>/foto` is requested
- THEN response is 302 with `Location: /login`
- AND no `apap-photos` URL (signed or public) is leaked in headers or body

#### Scenario: Authorized request streams bytes

- GIVEN an authorized session and `animales.nombrefoto` = `<returned_key>`
- WHEN `GET /animales/<uuid>/foto` is requested
- THEN response is 200 with `Content-Type: image/<ext>` and the correct byte stream
- AND the stream bytes are streamed via FastAPI `StreamingResponse` (no full file in memory)
- AND the server-side fetch uses `httpx.Client.stream` over `GET /api/storage/downloadStrategy?path=<key>&expiresIn=3600`

### Requirement: SHA-256 Object Key + Deduplication (Client-Derived, Verified API)

Photo bytes MUST be uploaded with an object key proposed by the client as `<sha256>.<ext>` derived from SHA-256 of the bytes plus the detected extension. The LocalBackend upload-strategy endpoint MAY auto-rename on key collision; the canonical key is the `key` field returned by the server in the upload-strategy response. Duplicate content (same SHA-256 across rows) MUST NOT create duplicate objects; the existing object MUST be reused and both rows point to it.

> **Why client-derived, not server-returned sha256 (Correction C).** The verified LocalBackend upload-strategy response (per Context7 `/local_backend/local_backend` + `/websites/local_backend_dev`) is shaped `{method, uploadUrl, fields, key, confirmRequired, confirmUrl, expiresAt}`. The upload completion response is shaped `{key, size, mimeType, uploadedAt, url}`. **Neither response includes `sha256`.** Therefore the client MUST compute SHA-256 itself (which it does anyway to derive the proposed key) and treat the returned `key` as the canonical truth. Optional re-hash verification is provided by `apap-migrate verify-storage --check-bytes` (operator command, NOT in CI).

#### Scenario: Duplicate photo deduplicated

- GIVEN two `animales` rows with `NombreFoto` filenames that map to byte-identical photos
- WHEN the photo migration pass runs
- THEN exactly one bucket object is uploaded
- AND both `animales.nombrefoto` values are set to the same `<returned_key>` (server may rename from `<sha256>.<ext>` to a deduplicated name; the returned `key` is what we store)
- AND `apap-migrate status --photos` reports `unique_objects=N`, `row_references=2N`

#### Scenario: Object key is hash-derived and server-canonical

- GIVEN a photo file at `URLDirectorioDocumentacion/<x>.jpg` with bytes B
- WHEN the upload runs
- THEN the proposed key sent to `/api/storage/buckets/{bucket}/upload-strategy` is `<sha256(B)>.<ext>` where ext is detected from the bytes (jpeg/png/webp/gif)
- AND the `filename` field in the upload-strategy request body matches `<sha256(B)>.<ext>`
- AND `animales.nombrefoto` stores the **returned `key`** (not the legacy filename, not the proposed key if renamed)
- AND a hash → returned-key mapping is recorded in shadow IF the server renamed (no shadow row if not renamed)

#### Scenario: LocalBackend API contract matches spec

- GIVEN the `LocalBackendClient.upload_object` implementation
- WHEN a test mocks `POST /api/storage/buckets/apap-photos/upload-strategy`
- THEN the request body has `{filename, contentType, size}` and the response shape `{method, uploadUrl, fields, key, confirmRequired, confirmUrl, expiresAt}` is accepted
- AND step-2 PUT (Local) or POST (S3) hits the returned `uploadUrl` with `multipart/form-data` file field
- AND if `confirmRequired` is true, a POST to `confirmUrl` completes the upload

### Requirement: Orphan Detection and Cleanup

Photo objects in `apap-photos` without a corresponding `animales.nombrefoto` reference MUST be detectable. `apap-migrate status --photos` MUST report `orphan_count`. `--cleanup-orphans` MUST remove them idempotently.

#### Scenario: Orphan count reported

- GIVEN bucket has 100 objects and `animales.nombrefoto` references 97 of them
- WHEN `apap-migrate status --photos` runs
- THEN `orphan_count=3` is reported
- AND the 3 orphan keys are listed (no PII; keys are hashes)

#### Scenario: Cleanup is idempotent

- GIVEN 3 orphan objects
- WHEN `apap-migrate status --photos --cleanup-orphans` runs twice
- THEN the first run removes 3 objects
- AND the second run reports `removed=0`, `orphan_count=0`
- AND no `animales.nombrefoto` row is affected

### Requirement: Missing / Corrupt / Unsupported Photo Handling

If the photos directory is unreachable, the file is missing, bytes are corrupt, or the format is unsupported (e.g., `.tiff`, `.bmp`, `.heic` not in allowlist), the row MUST be marked with a sentinel `nombrefoto` value and the error logged. Migration MUST NOT abort.

| Case | Behavior |
|---|---|
| Directory unreachable | Set `nombrefoto=<sentinel>`, log `photo.dir_unreachable`, continue |
| File missing for `NombreFoto` row | Set `nombrefoto=<sentinel>`, log `photo.file_missing`, continue |
| Bytes corrupt (size 0 or unreadable) | Set `nombrefoto=<sentinel>`, log `photo.bytes_corrupt`, continue |
| Unsupported extension | Set `nombrefoto=<sentinel>`, log `photo.unsupported_ext`, continue |

#### Scenario: Missing photo does not abort

- GIVEN 500 rows with `NombreFoto`, 3 files missing
- WHEN the photo pass runs
- THEN 497 photos are uploaded; 3 rows have `nombrefoto=<sentinel>`
- AND `applied=497`, `errors=[]`, `warnings=["photo.file_missing x3"]` in `MigrationReport`
- AND exit code is 0

#### Scenario: Sentinel photo returns placeholder on GET

- GIVEN `animales.nombrefoto=<sentinel>`
- WHEN `GET /animales/<animal_id>/foto` is requested (authorized) (`animal_id` is `animales.id` UUID)
- THEN response is 200 with the placeholder bytes
- AND no LocalBackend call is made for a non-existent object

### Requirement: Idempotent Upload

Re-running the photo migration MUST NOT create duplicate uploads or duplicate `nombrefoto` values. SHA-256 match ⇒ skip.

#### Scenario: Second photo run is a no-op

- GIVEN a successful prior photo pass with 497 objects in bucket
- WHEN the photo pass runs again with no source changes
- THEN 0 uploads occur
- AND `apap-migrate status --photos` reports `unique_objects=497`, `orphans=0`

### Requirement: Cleanup on Rollback

If the migration is rolled back, the bucket MUST be deletable via MCP. After bucket deletion, `GET /animales/{animal_id}/foto` (UUID) MUST return placeholder bytes (not crash) because `nombrefoto` retains the hash but the object is gone.

#### Scenario: Bucket deletion falls back to placeholder

- GIVEN bucket `apap-photos` deleted via MCP
- WHEN `GET /animales/<animal_id>/foto` is requested (authorized)
- THEN response is 200 with placeholder bytes
- AND the route code catches the LocalBackend 404 and returns the placeholder

### Requirement: Storage Contract Spike Before Implementation (PR4 gate)

PR4 implementation of `LocalBackendClient.{ensure_bucket, get_bucket, upload_object, download_object_stream, delete_object}` and `GET /animales/{animal_id}/foto` MUST be preceded by a **live, read-only contract spike** against the deployed LocalBackend instance. The spike confirms:

1. The canonical download-strategy path (e.g. `/api/storage/downloadStrategy` vs a deployed alias).
2. The **required auth header** on the returned URL (Context7 docs suggest `Authorization: Bearer service_key`; the deployed instance MAY differ).
3. The error contract for 401 vs 404 (both must be distinguishable by the client).

The spike outcome is recorded in `docs/discovery/storage-contract-2026-Q3.md` and the unit/integration tests in `tests/migration/test_photo_storage.py` MUST assert against the recorded shape. **Tests MUST fail closed**: any 401 or 404 from the live probe marks PR4 red until the operator records the canonical response shape in `storage-contract-2026-Q3.md`. The bucket MUST stay `isPublic=false` regardless.

> **Why a spike instead of trusting docs.** Context7 `/local_backend/local_backend` and `/websites/local_backend_dev` document candidate endpoints and response shapes, but documentation can drift from the deployed instance. Implementing against an assumed contract (and only discovering the mismatch on first deploy) is a known silent-failure mode; the spike closes it before code lands.

#### Scenario: Spike pins canonical download-strategy path

- GIVEN the deployed LocalBackend instance is reachable with `APAP_LOCAL_BACKEND_URL` + `APAP_INSFORGE_SERVICE_KEY`
- WHEN an operator runs `python -m migration.storage_spike --probe download_strategy --path apap-photos/<sha256>.jpg` (a read-only command shipped with PR4's first commit, see `tests/migration/test_photo_storage.py::test_storage_spike_records_path`)
- THEN the spike records the actual returned `url` shape, status code, and response headers
- AND `docs/discovery/storage-contract-2026-Q3.md` is updated with the pinned canonical path + auth header

#### Scenario: Spike fails closed on 401/404

- GIVEN the spike returns 401 (auth header variant) or 404 (path alias)
- WHEN `pytest tests/migration/test_photo_storage.py` runs in CI
- THEN the test that asserts the canonical path/header shape FAILS
- AND PR4 is blocked until the operator records the real shape and updates the test

#### Scenario: Bucket stays private

- GIVEN any spike outcome (success, 401, or 404)
- WHEN `apap-migrate ensure-bucket apap-photos` runs
- THEN the bucket MUST be created or kept with `isPublic=false`
- AND the pre-flight invariant in the Private Bucket Invariant requirement above remains the contract (no relaxation based on the spike)

## Acceptance Evidence

- `tests/migration/test_photo_storage.py` covers private-bucket invariant, authenticated display (302 without session, 200 with), SHA-256 key derivation, dedup, orphans, cleanup idempotence, missing/corrupt/unsupported, and rollback fallback.
- `tests/test_animals_foto_route.py` covers the route layer (auth + streaming).
- Privacy invariant: NO unsigned/public URL is ever returned by the route.

## Out of Scope

- Public gallery or any unauthenticated photo route.
- Image transformation (resize/crop) at the route.
- OCR or content extraction from photos.
