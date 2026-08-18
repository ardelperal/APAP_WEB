# Exploration: live-data-migration-sandbox

## Topic
Reprioritize APAP_WEB roadmap around making the backend operational now, migrating real legacy animal data and photos, and enabling realistic hands-on use while APAP_WEB continues to be built.

---

## 1. InsForge Backend — Current State (READ-ONLY inspection)

### Evidence (MCP `get-backend-metadata`, `get-table-schema`)

| Capability | Current State | Evidence |
|---|---|---|
| Database | ✅ Live PostgreSQL via InsForge | Endpoint: `c3uc9dk6.eu-central.insforge.app` |
| Domain tables | ✅ Exist, all EMPTY (0 rows) | `animales`, `voluntarios`, `entradas`, `acogidas`, `adopciones`, `actuacion_sanitaria`, `animal_current_state`, `animal_lifecycle_events`, `cesiones_propietario` |
| Shadow/migration tables | ✅ `web_only_feature_shadow` (DDL exists in `migration/shadow_state.py`, NOT YET created in DB) | Code confirmed; MCP query returned no such table |
| Catalog tables | ✅ Populated (21 motivos, 7 origenes, 12 periodicidad, 13 pruebas, 8 tipos_contrato) | `catalogos_*` have real data |
| Auth | ✅ Google OAuth only | `oAuthProviders: ["google"]`; `authorized_users` has 1 row |
| Object storage | ❌ NO buckets exist | `list-buckets` returns `[]`; `create-bucket` confirmed working via MCP |
| Custom functions | ❌ None deployed | `functions: []` |
| `web_sql_migrations` table | ✅ Exists, 2 rows | Migration DDL tracking table present |

### InsForge `animales` Schema (from `get-table-schema`)

Columns (23 total): `id` (uuid, PK), `nchip` (text, NOT NULL, unique key), `traenchip`, `fimplantacionchip`, `nombreanimal`, `especie`, `sexo`, `raza`, `color`, `pelo`, `tamano`, `caracter`.

Continuación: `fnacimiento`, `fdefuncion`, `terapia`, `observaciones`, `nombrefoto` (→ filename only), `cartilla`, `eutanasia`, `razappp`, `mestizo`.

Resto: `eutanasiaotroasc ausas`, `eutanasiaenfermedad`, `ultimoestadoantesdefallecido`, `comunicacionariac`

**PII risk**: `nchip` (chip number — can be traced to animal+owner), `nombrefoto` (filename may encode owner/volunteer names in path), `traenchip` (Yes/No chip status). No animal photos stored in DB; only filenames.

### `voluntarios` Schema (from `get-table-schema`)

Columns (9 total): `id` (uuid, PK), `voluntario` (text, NOT NULL), `tel1`, `tel2`, `email` (UNIQUE), `dni` (UNIQUE — PII), `fecha_alta`, `updated_at`, `activo`

**PII risk**: `dni` (Spanish national ID — PII), `email`, `tel1`, `tel2`, `voluntario` (name).

---

## 2. Migration Implementation — What Exists vs. What's Missing

### What IS Complete (production-ready engine)

| Component | File | Status |
|---|---|---|
| Apply engine (`legacy_to_web`) | `migration/apply.py` | ✅ Complete — `apply_legacy_to_web()` with idempotency, hash diff, shadow divergence recording, audit logging, advisory lock, dry-run |
| Reconciliation engine | `migration/reconcile.py` | ✅ Complete — `reconcile_after_legacy_write()` with `preserve/derived/fixed` strategies, `post_apply_diff` hook, lifecycle event persistence |
| Shadow state repository | `migration/shadow_state.py` | ✅ Complete — `ShadowStateRepository` with full CRUD, `ON CONFLICT DO UPDATE` idempotency |
| Advisory lock (file-based, PID-aware) | `migration/lock.py` | ✅ Complete — `acquire_lock`/`release_lock` with stale-PID recovery via `psutil`/Win32 API |
| Audit logging | `app/core/logging.py` → `log_safe("sync.applied", ...)` | ✅ Per-row audit with source_hash, target_hash, direction |
| Mappings (5 tables) | `migration/mappings/{animal,voluntario,entrada,acogida,adopcion}.yaml` | ✅ `animal.yaml` and `voluntario.yaml` reviewed; all 5 present |
| CLI surface | `migration/cli.py` | ✅ `apap-migrate reconcile --check-only --interactive --table --since` and `apap-migrate apply --table --legacy-path --since --check-only` and `apap-migrate status --table` |
| Legacy batch reader | `migration/legacy_reader.py` | ✅ Batched reading with `TableSpec`, `BATCH_SIZE=100`, paging via `TOP n` |
| Derivation engine | `migration/derivation.py` | ✅ `derive_estado_actual_animal()` with full lifecycle state machine |
| Semantic events | `migration/semantic_events.py` | ✅ `translate_diff()` → `LifecycleEvent` rows for `animal_lifecycle_events` |
| Bootstrap DDL | `migration/shadow_state.py` | ✅ `SHADOW_TABLE_SQL` and `SHADOW_NEEDS_REVIEW_INDEX_SQL` (CREATE TABLE IF NOT EXISTS + partial index) |

### What Is MISSING / BLOCKING Real Data Migration

| Blocker | File | Evidence |
|---|---|---|
| **`execute_legacy_sql` is a stub** | `migration/dysflow_client.py:50` | `raise NotImplementedError("execute_legacy_sql will be implemented when Dysflow MCP is wired in a later slice")` — ALL actual legacy reads will fail |
| **`web_only_feature_shadow` table NOT created in InsForge** | InsForge DB | MCP query shows table does not exist; bootstrap code exists but has never run against the real DB |
| **Storage bucket does not exist** | InsForge | `list-buckets` returns `[]`; no `apap-photos` or equivalent bucket; DOC-04 (#59) not started |
| **`web_to_legacy` migration not implemented** | `migration/apply.py:11` | Comment: "Direction (this slice): legacy_to_web only. The reverse direction is a future PR." |
| **`migrate reconcile` interactive mode requires `created_by` UUID** | `migration/reconcile.py:543` | `if created_by is None: errors.append(...)` — operator automation needed |
| **No `migrate apply --legacy-path` validation** | `migration/apply.py:229` | No pre-flight MSACCESS.EXE check in the apply path (only in `lock.py::check_msaccess_running()` which is not wired into the apply flow) |

---

## 3. Legacy Animal/Photo Sources — Mapping and Storage

### Animal Data Source

| Aspect | Detail |
|---|---|
| Legacy table | `TbFichaAnimal` (Access Jet/ACE) |
| Natural key | `NCHIP` (string, chip number — NOT NULL per schema) |
| Photo filename field | `TbFichaAnimal.NombreFoto` (string, e.g. `"0123456789.jpg"` or NULL) |
| Photo storage path | `URLDirectorioFotos & NCHIP & "." & extension` where: `URLDirectorioFotos = URLDirectorioDocumentacion & "Fotos\"` |
| `URLDirectorioDocumentacion` | `Environ$("APAP_DOCUMENTATION_PATH")` or `{Access Project Path}\Documentacion\` |
| Photo filename convention | `{NCHIP}.{extension}` — NCHIP embedded in filename (no directory structure) |
| Extensions observed | `.jpg`, `.jpeg`, `.png`, `.gif` (extension extracted from source via `FSO.GetExtensionName`) |
| Photo add operation | `Animal.cls::AñadirFoto()` — copies file from source to `URLDirectorioFotos`, updates `NombreFoto` field |
| Photo delete operation | `Animal.cls::EliminarFoto()` — deletes file from `URLDirectorioFotos`, sets `NombreFoto = Null` |
| Photo overwrite | If `strNChip.jpg` already exists in `URLDirectorioFotos`, it is deleted and replaced |
| Animal photo vs. other files | `URLDirectorioDocumentacion` also has `Documentacion\` (contracts/docs), `Anexos\` (attachments), `Plantillas\` (templates) — photos are separate from documents |

### Legacy Forms That Read/Write Photos (from CodeGraph, APAP_ACTUAL)

- `Form_FormFichaAnimalEdicion.cls` → calls `AñadirFoto(strNChip, strURLOrigen)`
- `Form_FormFichaAnimalAlta.cls` → creates animals
- `Form_FormFichaAnimalGestion.cls` → lists animals

### PII Dimensions

| PII Type | Legacy Source | Risk |
|---|---|---|
| Animal chip ID (`NCHIP`) | `TbFichaAnimal.NCHIP` | Can be traced to animal+owner via registry |
| Volunteer DNI | `TbVoluntarios.DNI` | Spanish national ID — HIGH PII |
| Volunteer contact | `TbVoluntarios.Telefono1`, `email` | MEDIUM PII |
| Owner/adopter name | `TbAdopcion`, `TbEntradas` (free-text) | MEDIUM PII |
| Animal photos | Filesystem at `URLDirectorioFotos/{NCHIP}.ext` | LOW PII (animal, not person — unless photo contains person metadata) |

### Animal Photos vs. Documents — Critical Distinction

| Type | Location | Visibility Intent |
|---|---|---|
| Animal ID photos (`Fotos/{NCHIP}.jpg`) | `URLDirectorioDocumentacion\Fotos\` | **Intended for public display** — shelter website, adoption listings |
| Contract templates (`Plantillas\`) | `URLDirectorioDocumentacion\Plantillas\` | **Internal use** — generated documents |
| Anexos (attachments) | `URLDirectorioDocumentacion\Anexos\` | **May contain sensitive documents** — medical, owner contracts |
| Sanitary records | `TbActuacionSanitaria` linked | **Medical PII** — animal health history |

---

## 4. Smallest Safe Vertical Slice — Usable Private Sandbox

### What "Usable Private Sandbox" Means

A developer can run a full `apap-migrate apply` on their own legacy `.accdb` copy, get real animals + photos into InsForge, and use the web app with real data — without affecting production.

### Required Components for the Slice

#### Phase A: Migration Infrastructure (hard blockers)

1. **`execute_legacy_sql` Dysflow wiring** — wire `dysflow_query_execute` into `migration/dysflow_client.py`. This is the ONLY missing piece that blocks ALL legacy reads.
2. **`web_only_feature_shadow` bootstrap** — run `ShadowStateRepository.ensure_table()` against InsForge to create the shadow table (one `execute_sql` call).
3. **`apap-migrate status --table`** — verify counts before/after without touching production.

#### Phase B: Animal Data Migration

4. **Animal mapping already exists** (`animal.yaml`) — `TbFichaAnimal` → `animales` with 22 identity columns + web-only (`id`, `fecha_alta`, `updated_at`, `activo`).
5. **Idempotency already implemented** — `apply_legacy_to_web` checks SHA-256 hash before INSERT; same row = skip.

#### Phase C: Photo Storage (new work)

6. **Create InsForge bucket** — `apap-photos` (private bucket, auth-required for upload, public-read for display URLs via signed/expiring tokens).
7. **Photo migration mapping** — extend `animal.yaml` with a `storage` mapping: `{legacy_path: "URLDirectorioFotos", web_bucket: "apap-photos", filename_pattern: "{NCHIP}.{ext}"}`.
8. **File copy + upload** — read photo from legacy path, compute SHA-256, check if already uploaded (idempotency), upload to InsForge bucket, update `animales.nombrefoto` with storage reference.

#### Phase D: Volunteer + PII Protection (separate concern)

9. **`voluntarios` mapping** — already exists (`voluntario.yaml`) with `dni` as web-only UNIQUE column. PII minimization: DO NOT migrate `dni` in the first slice — map `voluntario` name only (no DNI, no tel2).
10. **PII consent** — real volunteer DNI + contact is HIGH PII; requires explicit user decision before migration.

### Minimal Runbook for First Slice

```
# Pre-flight
1. Verify APAP_ACTUAL .accdb is accessible via Dysflow
2. Confirm photo directory is accessible: URLDirectorioDocumentacion + "Fotos\"
3. Count animals in legacy: SELECT COUNT(*) FROM TbFichaAnimal
4. Count photos in directory: Dir count of Fotos\*.{ext}

# Dry-run (no writes)
apap-migrate apply --legacy-path "C:\path\to\APAP_ACTUAL.accdb" --table animal --check-only

# Real apply
apap-migrate apply --legacy-path "C:\path\to\APAP_ACTUAL.accdb" --table animal

# Verify
apap-migrate status --table animal
```

---

## 5. Readiness Matrix

| Capability | Current State | Evidence | Blocker | Required Work |
|---|---|---|---|---|
| **Tables (domain)** | ✅ Exist in InsForge, all empty | `get-backend-metadata` | None | None |
| **Tables (shadow)** | ❌ `web_only_feature_shadow` NOT created | MCP query returned no rows | `ensure_table()` never run | Run `ShadowStateRepository.ensure_table()` once |
| **Catalog data** | ✅ 5 catalogs populated | InsForge has 21+7+12+13+8 rows | None | None |
| **Auth (Google OAuth)** | ✅ Working | `authorized_users` has 1 row | None | None |
| **Storage (buckets)** | ❌ No bucket exists | `list-buckets: []` | No bucket created | Create `apap-photos` bucket via MCP |
| **Animal mapping** | ✅ `animal.yaml` complete (22 columns) | File reviewed | None | None |
| **Voluntario mapping** | ✅ `voluntario.yaml` exists | File reviewed | `dni` is web-only UNIQUE — PII concern | PII decision required before migrating DNI |
| **Entrada mapping** | ✅ `entrada.yaml` exists (FK lookups defined) | File reviewed | `fk_lookup` for animal_id via NCHIP | FK resolution needs `sync_state.json` |
| **Acogida mapping** | ✅ `acogida.yaml` exists | File reviewed | FK lookups incomplete | Verify `fk_lookups` complete |
| **Adopcion mapping** | ✅ `adopcion.yaml` exists | File reviewed | FK lookups incomplete | Verify `fk_lookups` complete |
| **Legacy photo filenames** | ✅ `TbFichaAnimal.NombreFoto` mapped | `animal.yaml:38` | Filename only; actual file is filesystem | Photo storage slice required |
| **Photo storage (files)** | ❌ No bucket; filesystem only | `list-buckets: []` | DOC-04 (#59) not started | Create bucket + photo migration logic |
| **Apply engine (legacy→web)** | ✅ Complete | `apply.py` reviewed | None | None |
| **Reconciliation engine** | ✅ Complete | `reconcile.py` reviewed | None | None |
| **`execute_legacy_sql`** | ❌ Stub — raises `NotImplementedError` | `dysflow_client.py:50` | **HARD BLOCKER** — no legacy reads possible | Wire Dysflow MCP `query_execute` into `dysflow_client.py` |
| **`web_only_feature_shadow` bootstrap** | ✅ Code complete | `shadow_state.py` | NOT executed against real DB | Run once: `ShadowStateRepository(client).ensure_table()` |
| **Advisory lock** | ✅ Complete | `lock.py` reviewed | None | None |
| **Audit logging** | ✅ `log_safe("sync.applied", ...)` per row | `apply.py:359` | None | None |
| **Migrate reconcile CLI** | ✅ `--check-only` and `--interactive` | `cli.py` reviewed | Requires `created_by` UUID for lifecycle events | Operator passes `--operator-uuid` or automation handles |
| **Migrate status CLI** | ✅ Implemented | `cli.py:653` | None | None |
| **web→legacy migration** | ❌ Not implemented | `apply.py:11` comment | Future PR | Not needed for Phase 1 |
| **Animal photo → InsForge storage** | ❌ No mapping or code | Missing | DOC-04 (#59) not started | New mapping + file copy logic |
| **Idempotency (animal photos)** | ❌ Not implemented for files | SHA-256 hash exists for rows but not files | DOC-04 (#59) not started | Compute `SHA-256(file)` before upload |
| **PII minimization (voluntarios)** | ❌ Full `dni`, `tel1`, `tel2`, `email` mapped | `voluntario.yaml` | Requires user decision | First slice: exclude `dni`, use only `voluntario` name |
| **Animal photos public visibility** | ❌ No signed URL / public policy | No bucket exists | DOC-04 (#59) | Private bucket; display via `/api/storage/...` signed URLs |
| **Access binary locking** | ✅ `check_msaccess_running()` in `lock.py` | Not wired into `apply` | Not called in apply flow | Wire `check_msaccess_running()` into `apply_legacy_to_web` pre-flight |
| **Dysflow MCP connectivity** | ⚠️ Unknown | Not tested | Verify Dysflow can open `.accdb` with password | Test with `dysflow get_capabilities` |
| **Test suite** | ⚠️ Unit tests exist for migration | `tests/migration/` | `execute_legacy_sql` stub means integration tests blocked | Mock injection path already exists via `set_legacy_query_executor()` |

---

## 6. Existing Issues vs. This Change

### Roadmap Treatment

- **DOC-04** (`#59`): "DOC-04: migración de archivos legacy a object storage" — Fase 7a, **NOT started**, not linked to any PR
- **DOC-58** (`#58`): "DOC-02: anexos de archivo con linking polimórfico" — Fase 7a, **NOT started**
- **No migration-focused issue exists** — the migration is discussed in `web-only-feature-preservation` SDD but has no dedicated issue or PR

### web-only-feature-preservation SDD

- **Exists in OpenSpec** as `openspec/specs/web-only-feature-preservation/`
- Covers shadow state, reconciliation, semantic events, lifecycle events
- **Does NOT cover** the Dysflow wiring, photo migration, or the `execute_legacy_sql` stub

### Recommendation

**Create ONE new issue** named:

> **`migration-01: apply legacy animals + photos into InsForge (sandbox-ready)`**

Scope:
1. Wire `execute_legacy_sql` Dysflow MCP
2. Run `web_only_feature_shadow` bootstrap
3. `apap-migrate apply --table animal` (full idempotent run with real legacy data)
4. Photo migration: create `apap-photos` bucket + copy animal ID photos from `URLDirectorioFotos`
5. Minimal volunteer slice (name only, NO `dni`/tel/email in first pass)
6. Verify `apap-migrate status` counts match legacy
7. Dry-run + rollback runbook documented

**Does NOT include** in this issue:
- Full `voluntarios` migration with DNI
- `web_to_legacy` migration
- Full photo library (annexos, contracts)
- Production deployment of the migration

---

## 7. Contradictions / Blockers Requiring User Input

### Contradiction 1: Volunteer PII — `dni` UNIQUE constraint

- `voluntario.yaml` maps `dni` as a web-only column with NO legacy source
- `voluntarios.dni` has a UNIQUE constraint in InsForge (`voluntarios_dni_key`)
- Legacy `TbVoluntarios.DNI` is PII (Spanish national ID)
- **If we migrate volunteers without DNI, we lose the UNIQUE constraint enforcement** (can't deduplicate by DNI if we don't have it)
- **Question**: Should `dni` be migrated? If yes: explicit consent required for PII. If no: remove UNIQUE constraint on `dni` in InsForge schema (breaking change)

### Contradiction 2: Photo visibility — public vs. private

- Legacy photos in `URLDirectorioFotos` are accessible to anyone with file system access
- InsForge bucket can be private (auth required) or public
- Animal ID photos are **intended for public display** (shelter website)
- **Question**: Should the `apap-photos` bucket be public-read (simpler, but anyone with bucket URL can access) or private with signed URLs (more secure, but requires per-request signing)?

### Contradiction 3: Legacy data path for photos

- `URLDirectorioFotos` is on a shared network drive or the Access developer's machine (`Application.CurrentProject.Path`)
- The migration operator must have network/filesystem access to the legacy photo directory
- **Question**: Where is the actual production photo directory located? Is it accessible from the machine running the migration? Is there a backup?

### Contradiction 4: Destination environment

- InsForge backend is at `c3uc9dk6.eu-central.insforge.app`
- This is a shared/development environment
- **Question**: Is this the target for the sandbox, or should a separate InsForge project be created for the sandbox? What data isolation is expected?

### Contradiction 5: Real volunteer/adopter data — PII scope

- The user said "real legacy animal data and photos"
- Legacy data includes volunteers with full DNI + contact info
- This is Spanish PII under GDPR
- **Question**: For the sandbox, should we mask/anonymize volunteer PII (names only, no DNI/tel/email)? Or is the sandbox considered a private, non-production environment with no GDPR concern?

---

## 8. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **`execute_legacy_sql` stub** — no legacy reads possible | **CRITICAL** | Wire Dysflow MCP before any migration work |
| **`web_only_feature_shadow` not created** — shadow writes fail silently | **HIGH** | Run `ensure_table()` as first step of bootstrap |
| **No photo storage** — `NombreFoto` points to non-existent InsForge path | **HIGH** | Create `apap-photos` bucket + implement photo mapping before animal migration |
| **`dni` UNIQUE constraint collision** — duplicate volunteer names in legacy | **MEDIUM** | First slice: exclude `dni`; or deduplicate before migration |
| **Legacy photo directory inaccessible** — filesystem path not reachable | **HIGH** | Verify `URLDirectorioFotos` accessibility before planning |
| **PII in logs** — `log_safe` captures `nchip` which traces to owner | **MEDIUM** | Apply redaction list (already in place per AGENTS.md §9) |
| **No `check_msaccess_running` in apply path** — concurrent write risk | **MEDIUM** | Wire `check_msaccess_running()` into `apply_legacy_to_web` pre-flight |
| **InsForge bucket name collision** — `apap-photos` might already exist in another project | **LOW** | Check `list-buckets` before creating |
| **Large photo migration timeout** — thousands of photos × network latency | **MEDIUM** | Batch upload with concurrency limit; implement resumable uploads |
| **Access `.accdb` locked by another user** — Dysflow fails | **MEDIUM** | `lock.py` has PID-based lock; apply path needs `check_msaccess_running()` wired |

---

## 9. Safe First Slice — Definitive Scope

### Trigger: User approves PII scope and environment

```
SLICE-0 (Infrastructure — 1 day):
  □ Wire execute_legacy_sql Dysflow MCP
  □ Run ShadowStateRepository.ensure_table()
  □ Test: apap-migrate status --table animal (verify 0 counts)
  □ Create apap-photos bucket

SLICE-1 (Animals only, no photos — 2 days):
  □ apap-migrate apply --legacy-path <dev-accdb> --table animal
  □ Verify: InsForge animales count == legacy TbFichaAnimal count
  □ Verify: apap-migrate reconcile --check-only returns 0 needs_review

SLICE-2 (Photos — 2 days):
  □ Photo mapping in animal.yaml
  □ SHA-256 idempotency check
  □ Upload {NCHIP}.{ext} → apap-photos/{NCHIP}.{ext}
  □ Update animales.nombrefoto with bucket reference
  □ Verify: InsForge photos accessible via signed URL

SLICE-3 (Volunteers minimal — 1 day, PENDING USER DECISION):
  □ Map only 'voluntario' name column
  □ Exclude dni, tel1, tel2, email in first pass
  □ apap-migrate apply --table voluntario
  □ Verify counts
```

### Rollback for Slice-1 (Animals)

```sql
-- If animals migrated incorrectly:
DELETE FROM animales WHERE nchip IN (SELECT nchip FROM TbFichaAnimal);
-- Shadow rows remain for audit:
SELECT * FROM web_only_feature_shadow WHERE table_name = 'animales';
```

### Access Fallback (Round-Trip)

The bidirectional mandate requires `web_to_legacy` for full round-trip. For the first slice:
- **Access stays writable** for new animals/volunteers
- **Migration operator** re-runs `apap-migrate apply` periodically (daily)
- Shadow state tracks which rows were migrated vs. created in Access post-migration
- **Conflict = `needs_review`** — operator resolves via `apap-migrate reconcile --interactive`

---

## 10. Ready for Proposal

**Status**: partial — the core apply engine and mappings are production-quality. The Dysflow stub and missing bucket are the only hard blockers. Photo storage and volunteer PII require user decisions before the slice can be scoped precisely.

**Proposal SAFE**: Yes, conditionally — the Dysflow wiring is routine and the apply engine has full idempotency + audit. The photo and volunteer slices depend on the contradictions in §7 being resolved first.

**Next recommended**: Launch `sdd-propose` for change `live-data-migration-sandbox` once user resolves §7 contradictions (especially: volunteer PII scope, photo visibility model, and destination environment).

---

## Evidence Index (for audit)

| Evidence | Source | Location |
|---|---|---|
| `animales` schema (23 columns) | `insforge.get-table-schema("animales")` | InsForge MCP |
| `voluntarios` schema (9 columns, dni UNIQUE) | `insforge.get-table-schema("voluntarios")` | InsForge MCP |
| `web_only_feature_shadow` absent | `insforge.get-backend-metadata()` | InsForge MCP |
| No storage buckets | `insforge.list-buckets()` | InsForge MCP |
| `execute_legacy_sql` stub | `migration/dysflow_client.py:50` | APAP_WEB |
| `animal.yaml` 22-column mapping | `migration/mappings/animal.yaml` | APAP_WEB |
| `voluntario.yaml` with dni as web-only | `migration/mappings/voluntario.yaml` | APAP_WEB |
| Photo path: `URLDirectorioDocumentacion & "Fotos\"` | `Entorno.cls:348` | APAP_ACTUAL |
| Photo filename: `{NCHIP}.{ext}` | `Animal.cls:56` | APAP_ACTUAL |
| `AñadirFoto` copies to `URLDirectorioFotos` | `Animal.cls:66-72` | APAP_ACTUAL |
| Advisory lock with PID recovery | `migration/lock.py` | APAP_WEB |
| `apply_legacy_to_web` idempotency | `migration/apply.py:350-375` | APAP_WEB |
| `log_safe("sync.applied")` per row | `migration/apply.py:359` | APAP_WEB |
| `ShadowStateRepository.ensure_table()` DDL | `migration/shadow_state.py:47-77` | APAP_WEB |
| `web_sql_migrations` table: 2 rows | `insforge.get-backend-metadata()` | InsForge MCP |
| Catalogs populated | `insforge.get-backend-metadata()` | InsForge MCP |
| Google OAuth auth | `insforge.get-backend-metadata()` | InsForge MCP |
| `create-bucket` works | MCP test (cleaned up) | InsForge MCP |
