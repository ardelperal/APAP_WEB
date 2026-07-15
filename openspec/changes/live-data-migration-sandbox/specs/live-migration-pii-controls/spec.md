# live-migration-pii-controls

## Purpose

Privacy contract for migrating real PII (DNI, Email, Tel1, Tel2) from the legacy `.accdb` to the web. Defines PII column mapping, authorization on every PII-displaying route, `log_safe` redaction, count/hash evidence (no raw values), DNI UNIQUE collision handling, and the PII audit document. Compliant with AGENTS.md §18 (privacy default-deny) and §6 (security defaults deny).

## Requirements

### Requirement: Complete PII Column Mapping

The system MUST migrate `voluntarios.Email`, `voluntarios.Tel1`, `voluntarios.Tel2` from the legacy table `TbVoluntariosParaAutorrellenables` (verified by Dysflow `get_schema` on 2026-07-11 to have columns `Voluntario, Tel1, Tel2, Email` only — NO `DNI` column). `Email`/`Tel1`/`Tel2` MUST map from legacy when present and NULL when absent. `voluntarios.DNI` is a **WEB-ONLY** column with `web_only_strategy: preserve`; it has NO legacy source. `DNI` is populated by manual web entry or future external flows; forward legacy apply MUST leave `dni=NULL` for every row.

> **Why the schema claim is sourced, not assumed.** `TbVoluntariosParaAutorrellenables` was inspected via the live Dysflow MCP `get_schema` tool. The result returned exactly four columns (`Voluntario, Tel1, Tel2, Email`, all `type=10 text size=255`). Any future claim that DNI exists in this legacy table must re-verify via the same tool — anecdotal evidence from old VB6 forms or operator memory is not a substitute. The current `migration/mappings/voluntario.yaml` already encodes this reality (`DNI` has `legacy_column: null`, `web_only_strategy: preserve`).

#### Scenario: Legacy Email and phones migrate with NULL tolerance

- GIVEN a legacy row with `Email="a@b"`, `Tel1="600"`, `Tel2=NULL`
- WHEN the applier runs
- THEN web row has `email="a@b"`, `tel1="600"`, `tel2=NULL`
- AND `voluntarios.dni=NULL` (legacy has no DNI; web stays NULL until manually populated)

#### Scenario: All-NULL legacy row accepted

- GIVEN a legacy row with `Email=NULL`, `Tel1=NULL`, `Tel2=NULL`
- WHEN the applier runs
- THEN web row has `email=NULL`, `tel1=NULL`, `tel2=NULL`, `dni=NULL`
- AND no error is raised

#### Scenario: Web-only DNI survives round-trip

- GIVEN a web-only `voluntarios.DNI="12345678A"` set by manual web entry post-bootstrap
- WHEN the round-trip runs (legacy→web→legacy)
- THEN `web_only_feature_shadow.preserved_value` for `DNI` retains `"12345678A"`
- AND `last_legacy_snapshot_at` advances
- AND the legacy `.accdb` is NOT touched for DNI (no DNI column exists in legacy)

### Requirement: Authorization Required for All PII Routes

Every route that returns PII (`/voluntarios`, `/voluntarios/{id}`, `/animales/{animal_id}` (UUID) if displaying owner, etc.) MUST require `require_authorized_user`. Tests MUST verify that unauthenticated requests return 302 to `/login`.

| Route | Auth required | Without session |
|---|---|---|
| `GET /voluntarios` | yes | 302 `/login` |
| `GET /voluntarios/{id}` | yes | 302 `/login` |
| `GET /animales` | yes | 302 `/login` |
| `GET /animales/{animal_id}/foto` (UUID) | yes | 302 `/login` |
| `GET /entradas` | yes | 302 `/login` |
| `GET /login` | no | 200 |

#### Scenario: Unauthenticated volunteer list redirects

- GIVEN no session cookie
- WHEN `GET /voluntarios` is requested
- THEN response is 302 with `Location: /login`
- AND no volunteer data appears in the body

#### Scenario: PUBLIC_PATHS matches verified app behavior

- GIVEN `app/main.py:148` (the canonical home of `PUBLIC_PATHS`)
- WHEN a test inspects `PUBLIC_PATHS`
- THEN the set equals exactly `{"/healthz", "/login", "/auth/google", "/auth/callback", "/logout"}` — 5 entries, as verified by CodeGraph + Read of `app/main.py` on 2026-07-11
- AND no PII route (e.g. `/animales/{animal_id}/foto`, `/voluntarios`, `/entradas`) is in the public set
- AND only `/login` is a public UI / application-content path; the other four (`/healthz`, `/auth/google`, `/auth/callback`, `/logout`) are **protocol/operational endpoints** intentionally public because their behavior is anonymous by design (liveness probe, OAuth flow start, OAuth callback, session clear) and they do not leak PII

> **Why the canonical set is five paths, not just `{"/login", "/login/"}`.** The previous draft asserted `PUBLIC_PATHS` equals `{"/login", "/login/"}` "or whatever the canonical prefix is" — that is a FACTUAL ERROR. The verified `PUBLIC_PATHS` at `app/main.py:148` (CodeGraph + Read on 2026-07-11) contains exactly five paths. Removing `/healthz`, `/auth/google`, `/auth/callback`, or `/logout` would break the OAuth callback loop, Coolify's liveness probe, or logout semantics. The **product requirement is preserved**: only login UI/content is publicly browseable; the other four entries are protocol/operational surfaces, not application content. Any future change to `PUBLIC_PATHS` MUST update the test in `tests/test_public_paths.py` so the verified set stays in sync with the implementation, and the test MUST cover all five entries.

### Requirement: log_safe Redaction of PII Fields

`log_safe` payloads MUST NOT contain raw `dni`, `email`, `tel1`, `tel2`, or any of the 12 redaction list fields. The redaction list MUST cover all PII columns. The redaction test MUST assert that payloads post-`log_safe` contain masked values only (`***` or hash-prefix).

#### Scenario: sync.applied log has no raw DNI

- GIVEN a legacy row with `DNI="12345678A"`
- WHEN `apply_legacy_to_web` writes the row and calls `log_safe("sync.applied", ...)`
- THEN the captured log payload does NOT contain the substring `"12345678A"`
- AND it contains either no DNI field or a masked form

#### Scenario: web_only_feature_shadow.preserved_value is masked in logs

- GIVEN a shadow row with `preserved_value="12345678A"`
- WHEN any code logs the shadow row via `log_safe`
- THEN the captured payload does NOT contain the raw DNI
- AND it contains a hash prefix (first 8 chars of SHA-256) or `***`

#### Scenario: Redaction list covers all PII

- GIVEN `app/core/logging.py` redaction list
- WHEN a test iterates over all PII column names
- THEN each name is present in the redaction list
- AND a synthetic log payload containing each PII value emits a redacted payload

### Requirement: Count + Hash Evidence, Never Raw PII

All evidence (MigrationReport, audit doc, runbook, logs) MUST use counts (`count_legacy=N`, `count_web=N`) and SHA-256 hashes (`source_hash`, `target_hash`), NEVER raw PII values. This applies to console output, JSON reports, and CLI rendering.

> **Field scope (Correction B).** The `MigrationReport` type at `migration/reporting.py:118` currently has `direction`, `mode`, `dry_run`, `applied`, timestamps, `diffs`, `conflicts`, `backup_path`, `error`, `reconciliation_summary`. It does NOT yet have `counts`, `source_hashes`, or `collisions`. This change ADDs those three fields via `field(default_factory=dict)` so pre-existing reports stay valid. The full shape added is:
> - `counts: dict[str, dict[str, int]]` keyed by table name → `{"count_legacy": N, "count_web": N}`.
> - `source_hashes: dict[str, str]` keyed by table name → 64-hex SHA-256 of the legacy batch's canonical JSON (deterministic per spec REQ-Snap-1).
> - `collisions: dict[str, int]` keyed by collision counter name (e.g. `"dni_collisions"`, `"row_divergences"`) → integer count only.
>
> `ApplyResult` (at `migration/apply.py:69`) keeps its existing shape `{table_name, applied, skipped, errors}`; it does NOT grow. The per-table→per-run aggregate surfaces stay separate so the CLI can render one without the other.

#### Scenario: MigrationReport carries no raw PII

- GIVEN a successful apply with 523 volunteers (legacy Email/Tel1/Tel2 only)
- WHEN `MigrationReport.to_json()` runs
- THEN the JSON contains `counts.voluntarios={"count_legacy": 523, "count_web": 523}`
- AND `source_hashes.voluntarios=<sha256>` is present
- AND `collisions.dni_collisions=0` (legacy has no DNI; see Requirement above)
- AND no DNI/email/phone value appears anywhere in the JSON (verified by regex test in `tests/migration/test_pii_redaction.py`)

#### Scenario: CLI output has no raw PII

- GIVEN the same apply
- WHEN the CLI prints the summary
- THEN stdout contains only counts and hash prefixes (first 8 chars of SHA-256)
- AND no DNI/email/phone substring matches a fixture PII value

### Requirement: DNI Collision Policy (Web-Only and Reverse-Path Scope)

`voluntarios.dni` is UNIQUE in the web schema. **Forward legacy→web apply never produces a DNI collision** (legacy has no DNI column — see Requirement above). Collisions are possible in two scopes:

1. **Web-only manual collisions** — if an operator manually inserts multiple web `voluntarios` rows with the same `DNI` value, the second INSERT fails on the UNIQUE constraint; the applier (or web UI form) routes the rejected row to `web_only_feature_shadow` with `reconciliation_status="needs_review"` and `review_reasons=["dni_collision"]`.
2. **Reverse-path (web→legacy) collisions** — when the reverse applier tries to push a web `DNI` back to legacy, legacy has no column to receive it; the value stays in web's shadow with `review_reasons=["dni_collision"]` so the operator can resolve it.

In both scopes, the first INSERT wins; subsequent collisions MUST NOT overwrite and MUST route to `web_only_feature_shadow` with `reconciliation_status="needs_review"` and `review_reasons=["dni_collision"]`. The policy MUST be deterministic and auditable. Counts (never values) appear in `MigrationReport.collisions["dni_collisions"]`.

#### Scenario: First web-only DNI wins

- GIVEN web rows W1 and W2 with `DNI="12345678A"` (manually entered); web already has W1 from prior forward apply
- WHEN an INSERT for W2 is attempted
- THEN the INSERT fails on UNIQUE (`voluntarios_dni_key`)
- AND the applier routes W2 to a shadow row with `review_reasons=["dni_collision"]`, `reconciliation_status="needs_review"`
- AND `voluntarios.dni` still equals `"12345678A"` (not overwritten)

#### Scenario: Forward legacy→web produces zero DNI collisions

- GIVEN any number of legacy rows in `TbVoluntariosParaAutorrellenables` (none carry a DNI column)
- WHEN the forward applier runs
- THEN `MigrationReport.collisions["dni_collisions"]=0` (legacy has no DNI to collide on)
- AND every migrated web row has `dni=NULL`

#### Scenario: Reverse-path collision recorded

- GIVEN a web `DNI="12345678A"` and the reverse applier encounters it
- WHEN the reverse applier attempts to write `DNI` back to legacy
- THEN the legacy write for that column is skipped (legacy has no DNI column)
- AND a shadow row is recorded with `review_reasons=["dni_collision"]`, `reconciliation_status="needs_review"`
- AND `MigrationReport.collisions["dni_collisions"]` increments by 1

#### Scenario: Reviewer resolves via CLI

- GIVEN a `needs_review` row with `review_reasons=["dni_collision"]`
- WHEN the operator runs `apap-migrate reconcile --interactive`
- THEN the case appears in the list
- AND the operator can choose `keep web` (current web DNI), `accept derived` (update to legacy if possible), or `defer`
- AND the chosen option updates `reconciliation_status` and `reconciled_at`

### Requirement: PII Audit Document

`docs/audits/pii-live-migration-2026-Q3.md` MUST exist with sections: Scope (PII columns + display routes + storage), Methodology (redaction test, count/hash evidence test, authorization test, collision test), Findings (severity table), Verdict (PASS/FAIL with gate criteria). Verdict MUST be PASS for the M1 milestone gate.

#### Scenario: Audit doc enumerates all PII columns

- GIVEN the audit doc
- WHEN a test parses the Scope section
- THEN the column list contains exactly `{email, tel1, tel2}` (legacy-present) AND `dni` (web-only with explicit "no legacy source" annotation)
- AND each column maps to one or more display routes in the same section
- AND `dni` carries a note that it is web-only shadow, never migrated from legacy, and its UNIQUE constraint applies only to web-side and reverse-path collisions

#### Scenario: Audit verdict gates M1

- GIVEN the audit doc with Verdict `PASS`
- WHEN `apap-migrate status` runs as part of M1 acceptance
- THEN the gate check `audit_verdict == PASS` returns true
- AND M1 is NOT claimed green without PASS

## Acceptance Evidence

- `tests/migration/test_pii_redaction.py` covers log_safe redaction for all PII fields.
- `tests/test_public_paths.py` covers authorization on every PII route.
- `tests/migration/test_dni_collision.py` covers collision policy + reconciliation CLI for collisions.
- Audit doc `docs/audits/pii-live-migration-2026-Q3.md` with Verdict PASS is a precondition for M1 gate.

## Out of Scope

- Anonymization or hashing of PII in the database itself (the user explicitly requested real PII).
- Differential privacy or k-anonymity controls.
- PII encryption-at-rest beyond InsForge defaults.
- Consent management UI (out of this change).
