# Migration Risks

Business-relevant risks identified during discovery of the legacy Access/VBA system. These affect feature design, data integrity, or security in the future web application.

## Source snapshot identity

PR3 of `live-data-migration-sandbox` locks the source-identity contract for the forward applier so a re-apply detects drift between runs.

- **`migration.lock_snapshot.json`** is the durable record. Schema v1; written **AFTER the advisory lock is acquired, BEFORE the first `execute_legacy_sql` call** (per design §1 D8 / Correction J). SIGINT before the snapshot leaves no trace; SIGINT after writes the snapshot + `migration.partial_apply.json`.
- **Fingerprints**: SHA-256 hex of the `.accdb` bytes (`accdb_sha256`) and SHA-256 hex of the photos-directory manifest (`photos_dir_sha256` + `photos_file_count` + `photos_total_bytes`). Empty sources produce the SHA-256 of zero bytes (`EMPTY_SHA256`) deterministically so a fresh empty source matches a previous empty-source snapshot.
- **Drift detection**: on the next apply, `detect_drift` compares the prospective snapshot against the on-disk one. Drift aborts the apply (`SourceDriftError`, CLI exit 6, reason `source_drift`) — no informational proceed, no auto-accept. The previous snapshot is preserved on disk so the operator can diff manually.
- **Per-table hashes**: `MigrationReport.source_hashes` carries the per-table SHA-256 hex of the canonical JSON of the legacy batch (`{table_name: "<sha256 hex>"}`). Operator can review counts + hashes without opening the snapshot file.

The snapshot file is **NOT** a backup; it is a fingerprint. A re-apply does NOT mutate the legacy source. The apply path is single-threaded per `migration.lock` so concurrent runs do not race on the snapshot file.

## Collision policy (corrected)

The PR3 `MigrationReport` extended `MigrationReport.collisions` (`migration/reporting.py:167`) as `dict[str, dict[str, int]]` — per-table counters, **counts only, no values**. The operator-facing detail (which PKs collided) lives in `web_only_feature_shadow` and the `conflicts` list, NEVER inside the report (per spec REQ-PII-Audit invariant).

**PII columns in scope for collision policy** (verified via Dysflow `get_schema` on 2026-07-11):

| Column | Source (legacy) | Web column | web_only_strategy | Forward path | Collision surface |
|--------|------------------|------------|-------------------|--------------|-------------------|
| `email` | `TbVoluntariosParaAutorrellenables.Email` | `voluntarios.email` | mapped 1:1 | forward + reverse | forward only (legacy carries Email) |
| `tel1` | `TbVoluntariosParaAutorrellenables.Tel1` | `voluntarios.tel1` | mapped 1:1 | forward + reverse | forward only (legacy carries Tel1) |
| `tel2` | `TbVoluntariosParaAutorrellenables.Tel2` | `voluntarios.tel2` | mapped 1:1 | forward + reverse | forward only (legacy carries Tel2) |
| `dni`  | (NO legacy column — `TbVoluntariosParaAutorrellenables` returns exactly four columns: `Voluntario, Tel1, Tel2, Email`, all `type=10 text size=255`) | `voluntarios.dni` | `preserve` (web-only shadow; round-trip) | NEVER forward-migrated; preserved on web-side; reverse-path collision is recorded as `needs_review` | web-only manual INSERT (UNIQUE constraint on `voluntarios_dni_key`) + reverse-path (no legacy column to receive) |

**Why no `DNI` column in legacy.** `TbVoluntariosParaAutorrellenables` returns exactly four columns (`Voluntario, Tel1, Tel2, Email`). Any future claim that DNI exists in this legacy table MUST be re-verified via the same Dysflow `get_schema` tool — anecdotal evidence from old VB6 forms or operator memory is not a substitute. The current `migration/mappings/voluntario.yaml` already encodes this reality (`DNI` has `legacy_column: null`, `web_only_strategy: preserve`).

**Forward path produces zero DNI collisions** by construction: legacy rows carry no DNI column, so the forward applier never writes `voluntarios.dni`. Counters in `MigrationReport.collisions["voluntarios"]["preserve_advances"]` stay at 0 across the entire forward run (issue #217: the counter was renamed from `dni_collisions` to `preserve_advances` to reflect that it tracks preserve-column advances, not actual collisions).

**Collision scopes (PR5):**

1. **Web-only manual collisions** — an operator manually INSERTs two web `voluntarios` rows with the same DNI. The second INSERT fails on `voluntarios_dni_key`. The applier (or web UI) catches the rejection and routes the rejected row to `web_only_feature_shadow` with `reconciliation_status="needs_review"` and `review_reasons=["dni_collision"]`. The first INSERT wins; subsequent collisions do NOT overwrite.
2. **Reverse-path collisions** — the reverse applier (PR6) tries to push a web `DNI` back to legacy. Legacy has no column to receive it. The shadow table records the row with the same routing. The counter increments by 1 per collision.

In both scopes the first INSERT wins; subsequent collisions MUST NOT overwrite and MUST route to `web_only_feature_shadow`. Counts (never values) appear in `MigrationReport.collisions["voluntarios"]["preserve_advances"]` (issue #217: renamed from `dni_collisions` to accurately reflect that the counter tracks preserve-column advances, not actual collisions). The operator resolves via `apap-migrate reconcile --interactive` (option `a` keeps the web value, `b` accepts the derived value, `c` defers, `q` quits). The collision-routing helper lives at `migration/dni_collision.py::record_dni_collision` and is fully unit-tested (9 atoms in `tests/migration/test_dni_collision.py`); the helper persists `direction` verbatim on the shadow row as `origin_direction` (the column carries a closed three-value CHECK constraint: `legacy-to-web`, `web-to-legacy`, `web-only`). The **forward applier does NOT invoke** `record_dni_collision` because legacy `TbVoluntariosParaAutorrellenables` has no `DNI` column (Dysflow `get_schema` 2026-07-11). The DI seam `apply_legacy_to_web(dni_collision_counter=...)` is wired today so the PR6 reverse applier (`web_to_legacy`) can pass a `DniCollisionCounter()` and read its value at the end of the run to populate `MigrationReport.collisions[table_name]["preserve_advances"]`. The seam is exercised by `tests/migration/test_dni_collision.py::test_forward_legacy_produces_zero_dni_collisions` which passes a fresh counter through and asserts it stays at 0 (the contract: `apply_legacy_to_web` MUST NOT bump on forward apply).

The closed redaction list at `app/core/logging.py::REDACTED_FIELDS` (15 entries after PR4b: `email, session_token, jwt, oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization, cookie, referer, ip_address, x_forwarded_for, dni, tel1, tel2`) protects every `log_safe` payload — including the `sync.applied` per-row audit event and the `MigrationReport.to_json()` archive. The CLI reconcile listing masks `preserved_value` to `[REDACTED]` when the row's `web_column` is in the closed list. The audit verdict at `docs/audits/pii-live-migration-2026-Q3.md` is the M1 milestone gate.

## Data integrity risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| `Situacion` stored as mutable text | State can drift from actual records; manual overrides create inconsistencies | Compute state in web app from active records; never store as editable field |
| Chip change not atomic | Chip number updates may not cascade to all linked records/files | Implement chip-change saga: single transaction updates all references |
| No concurrency control | Two users editing the same record can overwrite each other | Add version numbers or ETags; reject stale writes |
| Duplicate health actions | Same action type + date can be recorded twice for an animal | Unique constraint on animal + action type + date |

## Security risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Hardcoded database password | Password embedded in VBA code; never expose in web app | Use environment variables and secret management |
| SQL concatenation in queries | Dynamic SQL built via string concatenation; injection risk | Parameterized queries and/or query builder; validate report SQL |
| Per-action passwords instead of RBAC | Button-level password checks, not role-based access | Design proper RBAC model with roles, permissions, and audit trail |

## Architecture risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| COM automation for documents | Word/Excel automation tied to Windows COM; not portable | Use cross-platform document generation library |
| Local filesystem for attachments | File paths point to local/network drives; not cloud-ready | Object storage (S3-compatible) with DB references |
| Pipe-delimited return format | Functions return `status|value|error` strings; fragile contract | REST APIs with proper HTTP status codes and JSON responses |
| Form-level business logic | Business rules embedded in form event handlers; not reusable | Extract into domain services; forms become thin UI layer |
| No API layer | All logic lives in Access forms/modules; no programmatic interface | Design REST/GraphQL API as the primary interface |

## Reporting risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dynamic SQL reports | Users can write arbitrary SQL; injection and performance risk | Validate report definitions; use views or curated query templates; sandbox execution |
| Quarterly report via form coordinates | Report layout mapped to form control positions; fragile | Structured report builder with data aggregation service |

## Data migration considerations

| Concern | Detail |
|---------|--------|
| Text-encoded states | Several fields encode state as text; need domain catalogs/enums before migration |
| File system references | Attachment/contract files stored on local paths; must migrate to object storage |
| Historical records | Legacy data must be preserved; plan for data migration scripts |
| Backward compatibility | Consider read-only legacy access during transition period |

### Data migration scope

| Table category | Tables | Migration priority | Notes |
|----------------|--------|-------------------|-------|
| Production data | `TbAnimales`, `TbEntradas`, `TbAdopcion`, `TbAcogidaAnimal`, `TbActuacionSanitaria` | High | Core business records; must migrate fully |
| Staging/auxiliary | `TbActuacionSanitariaAux`, `TbEntradasMultiplesAuxIniciales`, `TbAuxAnimales` | Low | Transient data; migrate structure only if needed |
| Audit/history | `TbContratosAnexos`, `TbDocumentosAnexos` | Medium | Legal documents; migrate with file storage migration |
| Catalog/reference | `TbOrigenEntrada`, `TbMotivosEntrada`, `TbTamaños`, `TbNombrePruebas`, `TbPruebasPeridicidad` | High | Domain catalogs; must migrate for validation rules |
| Configuration | `TbConfiguracionBackends`, form metadata | Low | Legacy config; not needed in web app |

### Backward compatibility plan

| Aspect | Approach |
|--------|----------|
| Duration | Read-only legacy access for 3–6 months post-migration (open question on exact duration) |
| Access mode | Legacy Access database opened as read-only; no writes permitted |
| Data sync | Nightly export of new records from legacy to web app during transition |
| Cutover | Full cutover when all users migrated and legacy data is frozen |
| Rollback | Legacy database remains available as fallback during transition |

### Post-migration validation

| Validation | Approach |
|------------|----------|
| Record count | Compare row counts per table between legacy and web app |
| State consistency | Verify computed `Situacion` matches legacy `Situacion` for all animals |
| Chip integrity | Verify all chip references are consistent across migrated records |
| Date range | Verify all dates fall within valid ranges |
| FK integrity | Verify all foreign key relationships resolve correctly |

## Not migration risks (legacy implementation details)

These are noted for completeness but are not business risks:

- `FormularioClave()` per-action password checks → replaced by RBAC
- `FormularioAbierto()` open-form checks → not relevant in web
- `AjustarTamaño Me` runtime resizing → responsive design handles this
- `ColocarTituloEnFiltro` list headers → standard table components
- `Dame()` / `DameID()` lookup helpers → standard API lookups
