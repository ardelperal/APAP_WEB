# Design: live-data-migration-sandbox (accepted)

skill_resolution: paths-injected (sdd-design, web-tdd-philosophy, vba-access, access-vba-tdd)
change_key: live-data-migration-sandbox
status: accepted by orchestrator 2026-07-15; corrections A–K applied; PR1–PR4b implemented per tasks.md; PR5–PR7 remaining (PII controls + reconcile filter, reverse apply + round-trip, verify-fallback-ready gate).
supersedes: previous draft that hallucinated `DNI` as a legacy column and invented
`MigrationReport`/`ApplyResult` fields that don't exist.

## §0 — Milestones and gates

| Milestone | Gate | PR |
|---|---|---|
| **M0 — Runtime boundary** | `execute_legacy_sql(path, sql, offset, limit)` returns rows from real `.accdb`; no MCP import; `check_msaccess_running()` (no-arg) integrated pre-flight; bucket `apap-photos` exists `isPublic=false`; snapshot written AFTER lock, BEFORE first read | PR1 (pyodbc wiring), PR2 (ShadowStateRepository.ensure_table + bucket MCP create) |
| **M1 — Forward usable** | `apply --table animal/entrada/voluntario` completes with PII; `GET /animales/{animal_id}/foto` returns 200 with auth, 302 to `/login` without; audit doc `PASS`; `verify-fallback-ready` runs in CI but exits non-zero (`missing_real_cycle=true`) until M2 — `animal_id` is `animales.id` UUID (Correction L; NCHIP is natural key for lookup only, NOT the route identifier) | PR3 (apply + lock_snapshot + MSACCESS pre-flight + photo pass), PR4 (LocalBackendClient storage contract spike FIRST, then foto route + audit/runbook), PR5 (PII tests + reconcile CLI) |
| **M2 — Fallback-ready gate** | `apply_web_to_legacy` symmetric; round-trip test green; **`verify-fallback-ready` exits 0 as CI gate AND publication gate** | PR6 (`apply_web_to_legacy`), PR7 (round-trip + verify-fallback-ready wired into `.github/workflows/ci.yml`) |
| Production-ready | OUT OF SCOPE | — |

P1 fidelity to `APAP_ACTUAL/src/classes/TbFichaAnimal/Resumen.cls` is binding (per `docs/proceso.md`).

## §1 — Architecture decisions

| ID | Decision | Alternative rejected | Rationale (evidence) |
|---|---|---|---|
| D1 | Legacy executor = **`pyodbc>=5.3`** (Microsoft Access Driver, Windows) | Snapshot adapter (Linux/CI fallback); Dysflow MCP | PyPI release Oct 17 2025 confirms 5.3.0 current stable; wheels for Python 3.9–3.14 (`/mkleehammer/pyodbc`, MIT-0). MCP rejected per `dysflow.get_capabilities()`: `writeExecutionPolicy: safe-by-default`, `effectiveDryRunDefault: true`, agent lifecycle, no SLO |
| **D2 (Correction A)** | **`TbVoluntariosParaAutorrellenables` has NO `DNI` column.** DNI is **web-only shadow**, preserved across round-trip via existing `voluntario.yaml` (`legacy_column: null`, `web_only_strategy: preserve`). `migration/mappings/voluntario.yaml` is already correct; **no YAML edit needed.** | "DNI migrated from legacy" (previous design) | Dysflow `get_schema` for `TbVoluntariosParaAutorrellenables` returns ONLY: `Voluntario, Tel1, Tel2, Email` (all `type=10`, `size=255`). Zero DNI. |
| D3 | PII migrated: `Voluntario, Tel1, Tel2, Email` (all present in legacy). `DNI` web-only. | Include DNI in forward apply | D2 |
| D4 | DNI collision policy re-scoped: applies to **web-only preservation across round-trip** and **reverse-path**, NOT to forward (legacy has no DNI). | Forward collision policy as written | D2 |
| **D5 (Correction C)** | Storage API **candidate** surface per Context7 `/local_backend/local_backend` (1914 snippets) and `/websites/local_backend_dev`: bucket CRUD (`GET/POST/PUT/DELETE /api/storage/buckets[/bucketName]`); upload via `POST /api/storage/buckets/{bucket}/upload-strategy`; download via `GET /api/storage/downloadStrategy?path=...&expiresIn=...`; object list/delete via `/api/storage/buckets/{bucket}/objects[/key]`. **This is the documented surface, not the final deployed contract.** | Invent endpoints | Context7 docs are a starting point; the deployed instance's canonical path and required auth header are confirmed by the D16 live, read-only spike (Correction L) before PR4 implementation |
| D6 | Hash key = **client-derived `<sha256>.<ext>`** proposed via upload-strategy `filename`. Server may auto-rename on collision; returned `key` is canonical. `animales.nombrefoto` stores returned key. Re-hash is OPTIONAL operator command (`apap-migrate verify-storage --check-bytes`, NOT in CI). | Server-returned sha256 (does not exist in API response — server returns `key, size, mimeType, uploadedAt, url` only) | LocalBackend docs: upload response shape lacks sha256 |
| D7 | Authorization = **service-key only**; display route streams bytes via `StreamingResponse` from server-side fetch; never returns signed/LocalBackend URLs to clients | Public bucket | AGENTS.md §18 + privacy default-deny |
| **D8 (Correction J)** | Snapshot write ordering locked: pre-flight → `acquire_lock` → **write `migration.lock_snapshot.json`** → first `execute_legacy_sql`. SIGINT before snapshot: lock released, no snapshot. SIGINT after snapshot: snapshot persists (valid empty source per spec REQ-Snap-3), `partial_apply.json` written, lock released | Snapshot before lock | Spec says "BEFORE first read"; we pin exact order for deterministic SIGINT behavior |
| **D9 (Correction D)** | `check_msaccess_running()` keeps **no-arg signature** (existing at `migration/lock.py:441`); spec text corrected to match. Path-aware semantics NOT in this change (would require per-path FD inspection; not verifiable). | `check_msaccess_running(legacy_path)` | CodeGraph confirms existing signature is no-arg; spec misaligned |
| **D10 (Correction E)** | `PUBLIC_PATHS` lives at **`app/main.py:148`** (already correct). `_is_public_path` at `app/main.py:160`. `app/core/middleware.py` is **unchanged**. No code edit needed. | "Move to `app/core/middleware.py`" (previous design) | CodeGraph confirms location |
| **D11 (Correction B)** | ADD to existing `MigrationReport` (`migration/reporting.py:118`): `counts: dict[str, int]` (per-table `{count_legacy, count_web}`), `source_hashes: dict[str, str]` (per-table SHA-256), `collisions: dict[str, int]` (per-table counters, e.g. `{"dni_collisions": 0, "row_divergences": N}`). Add via `field(default_factory=dict)` so pre-existing reports stay valid. `ApplyResult` (`migration/apply.py:69`) KEEPS existing shape `{table_name, applied, skipped, errors}`; does NOT grow. | Pretend fields already exist | CodeGraph confirms neither type has these fields today |
| **D12 (Correction G)** | `verify-fallback-ready` is **HARD CI gate** (job in `.github/workflows/ci.yml` after pytest) AND **publication gate** (operator cannot claim M2 without exit 0). Receipt distinguishes **CI-runnable** (round-trip test, web-to-legacy check-only, audit verdict) vs **operator-attested** (real cycle recorded in `migration_report.json` + `migration_report_signature.json` with operator_id + sha256). | CLI convention only | Correction G |
| **D13 (E2E scope)** | Canonical browser E2E = **Playwright via repo tests** (`tests/e2e/test_animals_foto_auth.py`), **fixture-first, idempotent, three-path** (happy 200+bytes; sad 302 no-session; edge placeholder for sentinel). Each test creates bucket `apap-photos-test-<8hex>`, seeds synthetic 1×1 PNG, cleans up via fixture teardown. **NOT gated on real migrated data.** Playwright MCP is **diagnostic only** (operator sign-off), NOT in CI. | "Canonical browser E2E is diagnostic only" | User requires Playwright MCP access but canonical E2E must be repo/CI tests |
| **D14 (Correction I)** | Global `tests/migration/conftest.py` adds **autouse fixture `_reset_executor_seam`** that calls `set_legacy_query_executor(None)` AFTER every test. Belt-and-braces over per-file `try/finally`. | Per-file teardown only | Cross-test leakage prevention |
| **D15 (Correction K)** | `pyodbc>=5.3` pin in `[project.optional-dependencies.etl]` | Defer pin | Context7 + PyPI confirmed Oct 17 2025 release; wheels cover Python 3.11 floor |
| **D16 (Correction L)** | **PR4 storage contract spike FIRST.** Before implementing `LocalBackendClient.{ensure_bucket, get_bucket, upload_object, download_object_stream, delete_object}` and the `GET /animales/{animal_id}/foto` route, run a **live, read-only** probe against the deployed LocalBackend instance to confirm: (a) the canonical download-strategy path (e.g. `/api/storage/downloadStrategy` vs deployed alias), (b) the **required auth header** on the returned URL (e.g. `Authorization: Bearer <service_key>` vs alternative), (c) the error contract for 401 vs 404. Tests MUST **fail closed**: any 401 or 404 from the live probe marks PR4 red until the operator records the canonical response shape in a `STORAGE_CONTRACT.md` artifact under `docs/discovery/` and the tests assert against that shape. Bucket MUST stay `isPublic=false` regardless. | Assume Context7 docs as final deployed contract | Docs and deployed instance can drift (auth header variants, error semantics); spike prevents implementing against an assumed contract that the real instance rejects |
| **D17 (PR3 verification remediation, 2026-07-11)** | Source drift FAILS CLOSED. The apply pipeline aborts with `SourceDriftError` (CLI exit 6, reason `source_drift`) when the freshly-computed `accdb_sha256` / `photos_dir_sha256` disagree with the previous snapshot's fingerprints. No informational proceed; no auto-accept. A future PR may add `--accept-drift` for explicit acknowledgement. PR3 deliberately does NOT auto-resume a partial-apply state — the operator must review and remove `migration.partial_apply.json` (CLI exit 7, reason `partial_apply_interrupted`). Automatic resume is a follow-up task scheduled before the M2 fallback-ready gate. | "Show drift and proceed" / "automatic resume on partial evidence" | Per user directive 2026-07-11: PR3 verification remediation pins the fail-closed contract; the operator's documentation surface must reflect it. |
| **D18 (PR3 verification remediation, 2026-07-11)** | MSACCESS pre-flight is FAIL-CLOSED. `check_msaccess_running()` raises `MsAccessPreflightUnavailableError` when `psutil` is missing on the operator box OR when `psutil.process_iter` raises mid-iteration. The apply catches the exception, emits `log_safe("apply.preflight_unavailable", reason=<cat>)` (categorical — no PIDs, no error strings), and re-raises. The CLI converts to exit 5 with reason `msaccess_preflight_unavailable`. Dry-run (`--check-only`) bypasses the preflight entirely. `psutil` is a hard requirement on operator boxes. | "Soft-fail with warning" | Per user directive 2026-07-11: silent fail-open claimed "no MSACCESS live" while the check was unable to actually look — misleading. Fail-closed is the safe default; psutil is a documented operator prerequisite. |
| **D19 (PR3 verification remediation, 2026-07-11)** | Stale-lock recovery is **PID-dead only**. A lock is considered stale only when the lock file is parseable AND the owning PID is verifiably dead (per `migration/lock.py::_is_lock_stale`). A live PID always keeps the lock active, even past TTL — a live process may be stalled for legitimate reasons (long migration, operator breakpoint). When liveness cannot be verified (psutil missing, permission errors), `_is_process_alive` returns `True` (fail-safe: assume alive, refuse to overwrite). Lock files that are empty or corrupt are NEVER auto-recovered — a writer may be paused mid-write. The implementation in PR2 (post-PR-review fix) stays unchanged in PR3; this entry documents the contract. | "Force-overwrite after TTL expiry" | Per user directive 2026-07-11: the current safe behavior is already proven and PR3 does NOT change it. Implementation outside PR3 stays untouched; this entry documents the contract. |

## §2 — Module layout (changes only)

```
migration/
├── dysflow_client.py            # MOD: pyodbc implementation
├── apply.py                     # MOD: lock_snapshot AFTER lock; MSACCESS pre-flight; photo pass hooks
├── apply_reverse.py             # NEW (M2)
├── photo_migration.py           # NEW: SHA-256 client-derived; capture returned key (D5, D6)
├── lock_snapshot.py             # NEW (D8)
├── reporting.py                 # MOD: ADD counts/source_hashes/collisions to MigrationReport (D11)
├── cli.py                       # MOD: status --photos, verify-fallback-ready, --operator-attest
└── mappings/
    ├── animal.yaml              # MOD: storage.bucket=apap-photos, storage.key=<sha256>.<ext>
    └── voluntario.yaml          # UNCHANGED (DNI already correct; D2)

app/core/local_backend.py              # MOD: +ensure_bucket, +get_bucket, +upload_object, +download_object_stream, +delete_object (D5)
app/modules/animals/routes.py     # MOD: GET /animales/{animal_id}/foto (StreamingResponse; D7); animal_id is animales.id UUID
app/main.py                      # UNCHANGED (PUBLIC_PATHS already at L148; D10)
app/core/middleware.py            # UNCHANGED (D10)
app/core/logging.py              # MOD: REDACTED_FIELDS += dni, tel1, tel2 (12 → 15)
app/core/migration/              # unchanged
pyproject.toml                   # MOD: [etl] += pyodbc>=5.3 (D15)
.github/workflows/ci.yml         # MOD: add verify-fallback-ready job (D12)
docs/audits/pii-live-migration-2026-Q3.md   # NEW
docs/runbooks/migrate-live-data.md          # NEW
docs/discovery/migration-risks.md           # MOD: collision re-scoped; 3 PII columns, not 4
tests/migration/test_runtime_boundary.py    # NEW
tests/migration/test_photo_storage.py       # NEW (uses D5 mock shapes)
tests/migration/test_pii_redaction.py       # NEW (15 fields)
tests/migration/test_dni_collision.py       # NEW (web-only + reverse-path collisions; D4)
tests/migration/test_reverse_apply.py       # NEW (M2)
tests/migration/test_round_trip.py          # NEW (M2)
tests/migration/test_fallback_ready_gate.py # NEW (CI-runnable + operator-attested stub; D12)
tests/migration/conftest.py                 # MOD: _reset_executor_seam autouse fixture (D14)
tests/e2e/test_animals_foto_auth.py         # NEW (Playwright fixture-first three-path; D13)
tests/test_animals_foto_route.py            # NEW (M1)
```

## §3 — Storage API surface (Correction C + Correction L)

> **Status: CANDIDATE surface, NOT final contract.** The shapes below are documented in Context7 `/local_backend/local_backend` and `/websites/local_backend_dev`; the **deployed** LocalBackend instance's canonical path, auth header, and 401/404 error semantics are NOT yet pinned. PR4 begins with a **live, read-only contract spike** (D16) that records the actual deployed contract in `docs/discovery/storage-contract-2026-Q3.md` before any code in this section lands. Tests fail closed on 401/404 until that artifact exists and the tests assert against it.

```python
# app/core/local_backend.py — PR4 (after D16 spike)
# All endpoints below are CANDIDATES from Context7 docs. The spike pins the
# canonical path and auth header; if they differ, the docstring on each
# method updates before the implementation lands.

def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict:
    """CANDIDATE: POST /api/storage/buckets body={bucketName, isPublic}.
    Spike must confirm: bucket path, 409 semantics, idempotency on re-create."""

def get_bucket(self, bucket_name: str) -> dict:
    """CANDIDATE: GET /api/storage/buckets/{bucket_name}. Spike must confirm 404 shape."""

def upload_object(self, bucket: str, key: str, body: bytes, *,
                  content_type: str) -> dict:
    """CANDIDATE two-step upload:
      1. POST /api/storage/buckets/{bucket}/upload-strategy
         body={filename, contentType, size} -> {method, uploadUrl, fields,
         key, confirmRequired, confirmUrl, expiresAt}
      2. PUT (Local) or POST (S3 with fields) to uploadUrl with multipart
         file=body; if confirmRequired, POST to confirmUrl.
    Spike must confirm: filename field name, multipart shape, returned-key
    semantics (no sha256 in response per D6)."""

def download_object_stream(self, bucket: str, key: str) -> Iterator[bytes]:
    """CANDIDATE two-step download:
      1. GET /api/storage/downloadStrategy?path={key}&expiresIn=3600
         -> {method, url, expiresAt}
      2. GET url with the auth header confirmed by the D16 spike
         (Context7 suggests 'Authorization: Bearer service_key' but the
         deployed instance may differ); yield via httpx.Client.stream.
    Spike must confirm: canonical path, required auth header, 401 vs 404
    error shape; tests fail closed on either."""

def delete_object(self, bucket: str, key: str) -> None:
    """CANDIDATE: DELETE /api/storage/buckets/{bucket}/objects/{key}.
    Spike must confirm idempotency on 404."""
```

**Authorization**: service-key only. NEVER return LocalBackend URL to clients; route streams bytes via FastAPI `StreamingResponse`. Bucket MUST stay `isPublic=false` (D7).

**Object key**: client proposes `<sha256_hex>.<ext>`. Server may rename on collision; returned `key` is canonical truth. `animales.nombrefoto` stores returned key. `apap-migrate status --photos` enumerates bucket objects and joins to `nombrefoto`; `--cleanup-orphans` deletes orphans (idempotent). `apap-migrate verify-storage --check-bytes` (NOT in CI) downloads each object and re-hashes as operator spot-check.

**Size/MIME/ext**: 0 < size ≤ 10 MiB; allowlist `jpg, jpeg, png, webp, gif`; sentinel `__missing__` for missing/corrupt/unsupported.

## §4 — PII column mapping (Correction A — corrected evidence)

| Legacy column (Dysflow `TbVoluntariosParaAutorrellenables`) | Web column | web_only_strategy |
|---|---|---|
| `Voluntario` (text 255) | `voluntarios.voluntario` (key) | mapped 1:1 |
| `Tel1` (text 255) | `voluntarios.tel1` | mapped 1:1 |
| `Tel2` (text 255) | `voluntarios.tel2` | mapped 1:1 |
| `Email` (text 255) | `voluntarios.email` | mapped 1:1 |
| **NO `DNI` column in legacy** | `voluntarios.dni` | `preserve` (web-only shadow; round-trip) |

DNI in web is filled by manual web entry or future external flows; never by forward legacy migration. Reverse path (web→legacy) does NOT write DNI to legacy (no column). Round-trip preserves `web_only_feature_shadow.preserved_value` for any web-only DNI. `MigrationReport.collisions["dni_collisions"]` is typically 0 in M1 forward; counts only, no values.

## §5 — Verify-fallback-ready gate (Correction G)

```yaml
# .github/workflows/ci.yml (PR7)
verify_fallback_ready:
  needs: [test]
  runs-on: ubuntu-latest
  steps:
    - run: pip install -e '.[etl,dev]'
    - run: python -m migration verify-fallback-ready --ci-only
    # exit 1 fails the build
```

Receipt (printed + stored in `migration_report.json`):

```yaml
ci_runnable_conditions:
  test_round_trip: green
  web_to_legacy_check_only: green
  audit_verdict: PASS  # parses docs/audits/pii-live-migration-2026-Q3.md Verdict:
operator_attested_conditions:
  real_cycle_recorded: <bool>  # from migration_report_signature.json
exit_code: 0 iff ci_runnable all green AND operator_attested.real_cycle_recorded == true
```

`--ci-only` runs CI-runnable conditions only (exit 0 if all green, even without operator attestation). Full `verify-fallback-ready` (without flag) requires operator attestation; publication gate.

## §6 — Test architecture

| Layer | What | Where | Runner |
|---|---|---|---|
| Unit (atoms) | `_apply_one_row`, `_record_shadow_divergence`, `_compute_source_hash`, photo upload dedup, collision handler (web-only + reverse-path), `log_safe` redaction (15 fields), lock_snapshot read/write | `tests/migration/test_*.py`, `tests/test_animals_foto_route.py`, `tests/test_log_safe_redaction.py` | `pytest -W error::DeprecationWarning` |
| Integration | `apply_legacy_to_web` happy/sad/edge over `FakeLocalBackend` + injected executor; `apply_web_to_legacy` mirror | `tests/migration/test_apply.py`, `tests/migration/test_reverse_apply.py` | same |
| E2E (real apply) | `pyodbc` against real (test-only) `.accdb`; bucket via LocalBackend dev instance | `tests/migration/test_apply_e2e.py` (skipped without `APAP_E2E_BASE_URL`) | `pytest --etl-e2e` |
| **E2E (browser — Playwright)** | **Fixture-first, idempotent, three-path** (200+bytes happy / 302 sad / placeholder edge). Each test creates `apap-photos-test-<8hex>`, seeds synthetic 1×1 PNG, cleans up. **NOT gated on real migrated data.** | `tests/e2e/test_animals_foto_auth.py` | `playwright` (CI matrix) |
| Diagnostic (MCP only) | Operator's browser session sign-off via Playwright MCP. NOT in CI. NOT a test. | n/a | MCP session |
| Static boundary | grep `app/` + `migration/` for `mcp__dysflow`, `dysflow_query_execute`, `mcp_dispatch` → 0 matches | `tests/migration/test_runtime_boundary.py::test_no_mcp_runtime_dependency` | pytest |

### Fixture reset (Correction I)

```python
# tests/migration/conftest.py
@pytest.fixture(autouse=True)
def _reset_executor_seam() -> Iterator[None]:
    """Reset executor seam AFTER every test. Belt-and-braces over per-file try/finally."""
    yield
    from migration.legacy_reader import set_legacy_query_executor
    set_legacy_query_executor(None)
```

### Three-path matrix

| Slice | Happy | Sad | Edge |
|---|---|---|---|
| Runtime boundary | pyodbc returns rows | driver missing → `LegacyReaderError` exit 5 | empty source → applied=0 |
| Source snapshot | snapshot written after lock, before first read | mid-run SIGINT → snapshot + partial_apply.json | empty source → all-zeros hashes |
| Lock discipline | lock before read, release after | stale lock (dead PID) → overwrite | live lock → exit 6 |
| MSACCESS pre-flight | no MSACCESS | MSACCESS open → exit 5 + runbook URL | `--check-only` skips |
| Private bucket | `isPublic=false` | bucket missing → auto-create (MCP); public → exit 5 | recreated mid-run → re-check |
| Auth display | 200 + bytes (auth) | 302 `/login` (no session) | sentinel → placeholder |
| Photo upload dedup | 2 rows, same bytes → 1 object | corrupt bytes → sentinel | unsupported ext → sentinel |
| Orphan cleanup | 3 orphans → deleted | re-run → removed=0 | 0 orphans → no-op |
| DNI collision (D4) | first web-only DNI wins | 5 collisions → 5 shadow rows + 1 INSERT | NULL legacy → web NULL |
| log_safe redaction | 15 fields covered | 1 field missing → test fails | mixed-case key normalized |
| Round-trip | 100/100/100 counts, source_hash preserved | 5 manual edits → 5 reverse-UPDATEs + 0 needs_review | no edits → all no-op |

## §7 — Files affected (consolidated)

See §2 module layout table above. Key actions:

| File | Action | PR |
|---|---|---|
| `migration/dysflow_client.py` | MOD (NotImplementedError → pyodbc, pyodbc>=5.3) | PR1 |
| `migration/apply.py` | MOD (lock_snapshot AFTER lock; MSACCESS pre-flight; partial_apply.json) | PR3 |
| `migration/apply_reverse.py` | NEW | PR6 |
| `migration/photo_migration.py` | NEW (client-derived SHA-256; capture returned key) | PR4 |
| `migration/lock_snapshot.py` | NEW | PR3 |
| `migration/reporting.py` | MOD (ADD counts/source_hashes/collisions to MigrationReport) | PR3 |
| `migration/cli.py` | MOD (verify-fallback-ready --ci-only, --operator-attest) | PR2, PR4, PR6 |
| `migration/mappings/animal.yaml` | MOD (storage block) | PR4 |
| `migration/mappings/voluntario.yaml` | UNCHANGED (DNI already web-only) | — |
| `app/core/local_backend.py` | MOD (+5 methods per D5 candidate surface; **D16 spike must run FIRST**; tests fail closed on 401/404) | PR4 (after D16 spike) |
| `app/modules/animals/routes.py` | MOD (GET /animales/{animal_id}/foto via StreamingResponse; `animal_id` is `animales.id` UUID) | PR4 (after D16 spike) |
| `app/main.py` | UNCHANGED (PUBLIC_PATHS already here) | — |
| `app/core/middleware.py` | UNCHANGED | — |
| `app/core/logging.py` | MOD (REDACTED_FIELDS += dni, tel1, tel2) | PR4 |
| `pyproject.toml` | MOD ([etl] += pyodbc>=5.3) | PR1 |
| `.github/workflows/ci.yml` | MOD (verify-fallback-ready job; D12) | PR7 |
| `docs/audits/pii-live-migration-2026-Q3.md` | NEW | PR4 |
| `docs/runbooks/migrate-live-data.md` | NEW | PR4 |
| `docs/discovery/migration-risks.md` | MOD (collision re-scoped; 3 PII cols) | PR5 |
| `tests/migration/conftest.py` | MOD (_reset_executor_seam autouse fixture) | PR1 |
| `tests/migration/test_*.py` | NEW (runtime_boundary, photo_storage, pii_redaction, dni_collision, reverse_apply, round_trip, fallback_ready_gate) | PR1, PR4, PR6, PR7 |
| `tests/e2e/test_animals_foto_auth.py` | NEW (Playwright fixture-first three-path) | PR4 |
| `tests/test_animals_foto_route.py` | NEW | PR4 |

## §8 — Sequencing, risks, deployment

### Sequencing (chained ≤ 600L per `size:exception`)

PR1 (M0, ~450L) → PR2 (M0, ~300L) → PR3 (M1, ~500L) → PR4 (M1, ~600L) → PR5 (M1, ~250L) → PR6 (M2, ~550L) → PR7 (M2, ~400L).

### Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Operator box missing Access driver | Med | Runbook pre-flight (`pyodbc.drivers()`); pyodbc 5.3 wheels for 3.9–3.14 |
| LocalBackend bucket public misconfig | Low | Pre-flight invariant + test |
| Operator edits `migration.lock_snapshot.json` | Low | JSON parseable-only contract; runbook warns |
| pyodbc hangs on locked `.accdb` | Med | `check_msaccess_running()` no-arg pre-flight + `Connection.timeout=30` |
| LocalBackend storage API drift | Low | Test against `httpx.MockTransport` of all 5 method shapes |
| Server auto-renames SHA-256 key | Low | `status --photos` exposes orphans; `verify-storage --check-bytes` operator spot-check |
| `verify-fallback-ready` requires real cycle not CI-runnable | Med | CI runs CI-runnable subset (`--ci-only`); operator attestation is separate file |
| `size:exception` revoked mid-chain | Low | Per-PR diff budget re-check |

### Apply exit-code contract (PR3 verification remediation, 2026-07-11)

The CLI surfaces every typed exception from `apap-migrate apply` as a
single categorical line on stdout (or stderr for setup errors):

    apap-migrate apply: status=error reason=<categorical> exit=<N> runbook=<ref>

- `<categorical>` is one of the closed-vocabulary reasons below.
- `<N>` is the deterministic process exit code.
- `<ref>` is the stable constant ``MIGRATION_RUNBOOK_REF`` =
  ``docs/runbooks/live-migration-apply.md`` (the apply runbook file
  is scheduled for authoring in a follow-up PR; the path is the
  contract the CLI surfaces today).
- The line carries NO traceback, NO raw exception payload, NO PII
  column names (``DNI``, ``Email``, ``Tel1``, ``Tel2``), and NO
  filesystem paths. The operator reads the runbook for the verbose
  interpretation.

Closed vocabulary (every typed exception → one entry):

| Exception                              | Exit | reason                              |
|----------------------------------------|------|-------------------------------------|
| ``MsAccessPreflightUnavailableError``  | 5    | ``msaccess_preflight_unavailable``   |
| ``MsAccessRunningError``               | 5    | ``msaccess_running``                 |
| ``LegacyReaderError``                  | 5    | ``legacy_read_failed``               |
| ``BackendError`` (bootstrap path)     | 5    | ``infra_bootstrap_failed``          |
| ``SourceDriftError``                   | 6    | ``source_drift``                     |
| ``PartialApplyInterruptedError``       | 7    | ``partial_apply_interrupted``        |

``log_safe`` audit events emitted by the apply pipeline (operator
streams never see these):

- ``apply.preflight_unavailable`` with categorical ``reason`` —
  emitted by the apply layer when ``check_msaccess_running`` raises.
  No PIDs, no error strings, only the closed-vocabulary reason.
- ``sync.applied`` / ``sync.applied`` (NOOP_DIVERGENCE_RECORDED) —
  existing per-row audit events from PR3 work units 1–3.

Dry-run (``--check-only``) bypasses the preflight entirely (per design
§6 three-path matrix) and runs the read+count path without writing
the snapshot or acquiring the lock. ``SourceDriftError`` and
``PartialApplyInterruptedError`` are evaluated on dry-run too so
the operator gets the same categorical contract.

### Security + observability

- **Network**: CLI opens ONLY LocalBackend URL + reads `.accdb` from operator disk. No MCP calls.
- **Auth**: storage uses service key only; display uses `require_authorized_user`.
- **PII log**: 15-field closed redaction list; static boundary test forbids raw PII substrings in `MigrationReport.to_json()` output.
- **Bucket**: pre-flight rejects public; create-with-private is the only path.
- **Lock**: PID + TTL; stale recovery only on verified-dead PID.
- **Observability**: `MigrationReport.to_json()` includes counts/source_hashes/collisions; `migration_report.json` archived; `--check-only` exit 0 with reports (monitoreable).

### Deployment / rollback

- **Deploy**: `pip install '.[etl]'` on operator box; `apap-migrate init`; runbook-driven apply.
- **Rollback**: M0 `rm migration.lock_snapshot.json`. M1 apply mid-flight: `apap-migrate reconcile --interactive`. M1 bucket: `delete-bucket apap-photos` via MCP. M2: never claim fallback without `verify-fallback-ready` exit 0.

## §9 — Open questions

1. **Photo size limit (10 MiB)** — confirm with operator if any photo exceeds this. Runbook documents; sentinel + audit catches.
2. **Bucket region / CDN** — operator's instance default. Edge caching is a follow-up PR.
3. **Server-renamed key mapping** — current plan: store returned key in `nombrefoto`; if renamed, hash → returned-key in shadow. If the user prefers shadow for ALL keys, open a follow-up issue.

## §10 — Driver rationale (terse)

| Driver | Pro | Con | Decision |
|---|---|---|---|
| pyodbc 5.3+ | Windows standard; MS Access Driver redistribuible; wheels 3.9–3.14 | Windows-only; Linux requires unixODBC + mdbtools | PRIMARY |
| snapshot adapter | Reproducible; cross-platform | Stale if legacy changes between export and apply | FALLBACK (Linux/CI) |
| Dysflow MCP | On operator box | `safe-by-default`, `dryRun` default true; agent-lifecycle; no SLO | REJECTED |

## Evidence index

| Fact | Source |
|---|---|
| `TbVoluntariosParaAutorrellenables` columns: `Voluntario, Tel1, Tel2, Email` (NO DNI) | Dysflow `get_schema` |
| `MigrationReport` lacks `counts/source_hashes/collisions` | CodeGraph `migration/reporting.py:118` |
| `ApplyResult` shape `{table_name, applied, skipped, errors}` | CodeGraph `migration/apply.py:69` |
| `PUBLIC_PATHS` at `app/main.py:148` | CodeGraph `app/main.py` |
| `check_msaccess_running()` no-arg | CodeGraph `migration/lock.py:441` |
| `REDACTED_FIELDS` is 12 fields (no dni/tel1/tel2) | CodeGraph `app/core/logging.py:41` |
| `voluntario.yaml` already correct (DNI `legacy_column: null`) | Read `migration/mappings/voluntario.yaml` |
| LocalBackend storage endpoints | Context7 `/local_backend/local_backend` + `/websites/local_backend_dev` |
| pyodbc 5.3.0 current stable (Oct 17 2025) | Context7 `/mkleehammer/pyodbc` + PyPI |
