# PII Audit — Live Migration (2026 Q3, PR4b)

> **Verdict**: PASS
> **Scope**: M1 forward migration PII surface (legacy → web); authenticated
> photo display route; storage redaction invariants; `log_safe` redaction
> list. **Out of scope**: M2 reverse path (PR6/PR7), production release
> tags, public galleries, anonymization, encryption-at-rest beyond InsForge
> defaults.

## Scope

### PII columns in scope

| Column    | Source (legacy)               | Web column   | web_only_strategy | Forward path             |
|-----------|-------------------------------|--------------|-------------------|--------------------------|
| `email`   | `TbVoluntariosParaAutorrellenables.Email` | `voluntarios.email` | mapped 1:1        | forward + reverse        |
| `tel1`    | `TbVoluntariosParaAutorrellenables.Tel1`  | `voluntarios.tel1`  | mapped 1:1        | forward + reverse        |
| `tel2`    | `TbVoluntariosParaAutorrellenables.Tel2`  | `voluntarios.tel2`  | mapped 1:1        | forward + reverse        |
| `dni`     | (NO legacy column — verified via Dysflow `get_schema` on 2026-07-11) | `voluntarios.dni` | `preserve` (web-only shadow; round-trip) | NEVER forward-migrated; preserved on web-side; reverse-path collision is recorded as `needs_review` |

> **Why no `DNI` column in legacy.** `TbVoluntariosParaAutorrellenables`
> returns exactly four columns (`Voluntario, Tel1, Tel2, Email`, all
> `type=10 text size=255`). Any future claim that DNI exists in this
> legacy table MUST be re-verified via the same Dysflow `get_schema`
> tool. The `migration/mappings/voluntario.yaml` mapping already encodes
> this reality (`DNI` has `legacy_column: null`,
> `web_only_strategy: preserve`).

### Display routes in scope (PII can be reached via these)

| Route                                  | Auth required | Without session |
|----------------------------------------|---------------|-----------------|
| `GET /voluntarios`                     | yes           | 302 `/login`    |
| `GET /voluntarios/{id}`                | yes           | 302 `/login`    |
| `GET /animales`                        | yes           | 302 `/login`    |
| `GET /animales/{animal_id}` (UUID)     | yes           | 302 `/login`    |
| `GET /animales/{animal_id}/foto` (UUID)| yes           | 302 `/login`    |
| `GET /entradas`                        | yes           | 302 `/login`    |
| `GET /login`                           | no            | 200            |

`PUBLIC_PATHS` at `app/main.py:148` is the closed set of
intentionally-unauthenticated endpoints: `{/healthz, /login,
/auth/google, /auth/callback, /logout}` (5 entries). Only `/login`
exposes application content; the other four are protocol/operational
surfaces (liveness probe, OAuth flow start, OAuth callback, session
clear) that do not leak PII by design.

### Storage in scope

- `apap-photos` private bucket (`isPublic=false`); pre-flight invariant
  is `isPublic == False` and the apply aborts on `True` or absent.
- Object keys are client-derived as `<sha256>.<ext>` (SHA-256 of the
  bytes + detected extension). Server may rename on collision; the
  canonical key is the `key` field returned by the upload-strategy.
- `animales.nombrefoto` stores the **returned** key (not the legacy
  filename, not the proposed key if the server renamed).
- Sentinel `__missing__` is set when the source photo is missing,
  corrupt, or unsupported; the route serves a 1x1 PNG placeholder
  without any storage I/O.

### Redaction list (`app/core/logging.py::REDACTED_FIELDS`)

After PR4b the closed list has 15 entries: `email, session_token, jwt,
oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization,
cookie, referer, ip_address, x_forwarded_for, dni, tel1, tel2`.
Comparison is case-insensitive and treats `-` and `_` as equivalent.

## Methodology

Six invariants are pinned by automated atoms. Each atom is a fixture
that pre-loads the relevant fake, exercises the contract, and asserts
the post-state with a concrete value (not absence-of-error).

1. **Redaction list shape** — `tests/test_logging.py` +
   `tests/test_log_safe_redaction.py` (15 atoms after parametrization
   expansion). The list has exactly 15 entries; every new PII field
   (`dni`, `tel1`, `tel2`) is present; mixed-case variants
   (`DNI`, `Tel1`, `TEL2`) are redacted; descriptive names that merely
   CONTAIN a redacted substring (`dni_lookup_table`,
   `telefono_secundario`) pass through unchanged.
2. **Authorization invariant** —
   `tests/test_animals_foto_route.py::TestFotoRouteAuthorizationInvariant`
   pins that an anonymous request redirects to `/login` BEFORE
   any DB or storage call. No SQL queries, no storage calls.
3. **No-presigned-URL leak** —
   `tests/test_animals_foto_route.py::TestFotoRouteDoesNotLeakPresignedUrl`
   pins that no header or body of the response ever contains the
   storage URL or any presigned token, even when the storage
   surface raised with that URL in its error body.
4. **Fail-closed on every storage-stream error category** —
   `tests/migration/test_insforge_storage_methods.py` parameterises
   401, 403, 404, 405, 500 on the upload strategy; `download_object_stream`
   raises `InsForgeError` on 401/404/5xx and `httpx.TimeoutException` on
   network timeout. The route layer's
   `tests/test_animals_foto_route.py::TestFotoRouteMidStreamFailClosed`
   covers four placeholder emission paths: streamed-GET 5xx
   (`test_foto_route_placeholder_when_streamed_get_5xx_on_first_chunk`),
   mid-iteration network drop
   (`test_foto_route_placeholder_when_stream_mid_iteration_network_error`),
   streamed-GET succeeds for headers but fails on first-iteration
   (`test_foto_route_placeholder_when_stream_fails_on_first_iteration`),
   and per-chunk read timeout
   (`test_foto_route_placeholder_on_per_chunk_timeout`). The route
   consumes the storage generator eagerly so a mid-stream
   `PhotoStreamError` always becomes the placeholder PNG — never a 5xx.
   The service-level wrapping is pinned by
   `tests/test_animals_foto_route.py::TestFotoServiceMidStreamWrapping`.
   **PR4b 4R WARN-3:** unexpected exceptions on the animales SELECT
   (`animals_service.get_animal_by_id`) ALSO fail closed to the
   placeholder, for consistency with the storage-stream contract.
   `tests/test_animals_foto_route.py::TestFotoRouteSqlLookupFailClosed`
   pins both `InsForgeError` (transport-flavoured) and a non-InsForge
   `RuntimeError` (invariant-violation-flavoured). The error is
   recorded via `log_safe("animal_foto.sql_lookup_failed", reason=...)`
   so the operator still sees it in the audit stream. A genuinely
   missing animal (the service returns `None`) STILL surfaces as 404
   because the absence is a domain signal, not a transport failure.
5. **Idempotent upload** —
   `tests/migration/test_insforge_storage_methods.py::test_upload_object_reuses_existing_key_via_client_derived_filename`
   asserts the same bytes uploaded twice carry the same client-side
   filename so server-side dedup can fire.
6. **No raw `logger.*` / `print(...)` in `app/core/insforge.py`** —
   `tests/migration/test_insforge_storage_methods.py::test_storage_methods_never_log_secrets_urls_or_paths`
   uses the AST detector from `scripts/check_rules.py` (the same
   detector that runs in CI) to pin the absence of forbidden logging
   patterns in the production storage surface.

In addition, the operator runbook
`docs/runbooks/live-migration-apply.md` carries the canonical
operator workflow; `tests/test_runbook_links.py` pins that every
operator-facing runbook reference resolves to an authored file
with the AGENTS.md §13 headings (`## When to trigger`,
`## Pre-deploy checklist`, `## Deploy steps`, `## Verification`,
`## Rollback`).

## Findings

| Severity | Finding                                                                                  | Evidence                                                                                          | Status     |
|----------|-------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|------------|
| P0       | None — no critical findings.                                                              | n/a                                                                                               | n/a        |
| P1       | None — no high-severity findings.                                                          | n/a                                                                                               | n/a        |
| P2       | Sentinel placeholder is a static 1x1 transparent PNG; users see no "broken image" hint.   | `app/modules/animals/routes.py::_PLACEHOLDER_PHOTO_PNG`; `app/modules/animals/photo_service.py::SENTINEL_KEY`. UX improvement, not a security defect. | Acknowledged (out of PR4b scope) |
| P2       | `delete_object` 404 returns `None` (idempotent) — if the operator logs the return value they see no signal of "already absent". | `tests/migration/test_insforge_storage_methods.py::test_delete_object_404_is_idempotent_noop`. No PII or secret leakage; only operator UX. | Acknowledged (out of PR4b scope) |
| P3       | `content_type_for_key` falls back to `application/octet-stream` for unknown extensions; browsers will download instead of inline. | `app/modules/animals/photo_service.py::content_type_for_key`. Defensive default, no security impact. | Acknowledged |
| P3       | Audit doc rendered in castellano de España for project consistency; technical artifacts default to English. | `docs/audits/pii-live-migration-2026-Q3.md` (this file).                                           | By design  |

## Verdict

**PASS** — every PR4b PII control is pinned by an automated atom.
The M1 milestone gate accepts the PII contract on the basis of:

- The closed redaction list (15 entries) is verified end-to-end by
  parametrized atoms in `tests/test_log_safe_redaction.py` (13 atoms
  RED-first → GREEN with the implementation commit).
- The `GET /animales/{animal_id}/foto` route is verified by
  `tests/test_animals_foto_route.py` (9 atoms: auth redirect,
  happy streaming, sentinel placeholder, null placeholder, storage
  fail-closed, no-presigned-URL leak, isolated service, anonymous
  pre-storage invariant).
- The production storage methods on `InsForgeClient` are verified by
  `tests/migration/test_insforge_storage_methods.py` (28 atoms:
  happy/sad/edge for upload_object, download_object_stream,
  delete_object; fail-closed on 401/403/404/405/500/timeout/network;
  unsafe-bucket pre-network; idempotent re-upload; bearer auth on
  every strategy/transfer/download/confirm step).
- The migration operator path is documented in
  `docs/runbooks/live-migration-apply.md` with the AGENTS.md §13
  headings and the `MIGRATION_RUNBOOK_REF` constant surfaces this
  canonical path on every typed-exception line. The PR4b-specific
  photo display + storage sections extend that runbook on top of
  the existing apply / pre-flight / rollback / escalation sections.

### Acceptance evidence index

| Invariant                                       | Atom file                                           | Atoms |
|-------------------------------------------------|-----------------------------------------------------|-------|
| REDACTED_FIELDS has exactly 15 entries          | `tests/test_log_safe_redaction.py`                  | 1     |
| Each new PII field is in the closed list        | `tests/test_log_safe_redaction.py`                  | 3     |
| `log_safe` redacts each new field value         | `tests/test_log_safe_redaction.py`                  | 3     |
| Mixed-case variants are redacted                | `tests/test_log_safe_redaction.py`                  | 6     |
| PII never leaks via the formatted message       | `tests/test_log_safe_redaction.py`                  | 1     |
| Descriptive names pass through unchanged        | `tests/test_log_safe_redaction.py`                  | 1     |
| Storage methods happy/sad/edge                  | `tests/migration/test_insforge_storage_methods.py`  | 28    |
| Auth gate redirects anonymous to `/login`      | `tests/test_animals_foto_route.py`                  | 2     |
| Route streams bytes for real keys              | `tests/test_animals_foto_route.py`                  | 1     |
| Sentinel + null → placeholder, no I/O          | `tests/test_animals_foto_route.py`                  | 2     |
| Storage error → placeholder (fail-closed)      | `tests/test_animals_foto_route.py`                  | 1     |
| No presigned URL leak                          | `tests/test_animals_foto_route.py`                  | 1     |
| Service isolation (no photo/bucket SQL)         | `tests/test_animals_foto_route.py`                  | 1     |
| Runbook references resolve to authored files    | `tests/test_runbook_links.py`                       | 12    |

### Operator acknowledgement

The operator MUST review and accept this verdict as part of the M1
acceptance gate before claiming "Usable ya". The acceptance is
recorded in the migration report (`migration_report.json` +
`migration_report_signature.json`) per the apply runbook's
"Escalation" section.
