# Propuesta: live-data-migration-sandbox

skill_resolution: paths-injected (sdd-propose, vba-access, access-vba-tdd, web-tdd-philosophy, cognitive-doc-design)

## Intención

Hacer operable el backend privado con datos reales (animales, personas, fotos) **mientras el desarrollo de APAP_WEB continúa**. Hoy las 8 tablas de dominio (`animales`, `voluntarios`, `entradas`, `acogidas`, `adopciones`, `actuacion_sanitaria`, `animal_current_state`, `animal_lifecycle_events`) están creadas en InsForge y vacías; los catálogos están poblados; el engine de apply (`migration/apply.py`), el reconciliador (`migration/reconcile.py`), el shadow state (`migration/shadow_state.py`), el lock (`migration/lock.py`) y los 5 mappings (`animal|voluntario|entrada|acogida|adopcion.yaml`) están completos e idempotentes. Lo que falta para "usable ya" son los tres puentes que la exploración deja como bloqueadores. Esta propuesta los cierra con un contrato de privacidad estricto (DNI/email/teléfono reales con acceso autenticado, sin raw PII en logs, sin bucket público), preserva la fidelidad al legacy `APAP_ACTUAL` como superset funcional (P1), y define el milestone de **bidireccionalidad completa** como **gate obligatorio** antes de reclamar fallback-readiness.

## Alcance

### Dentro (Milestone "Usable ya" → M0+M1+M2)

- **M0 — Runtime boundary verificado para lectura legacy**: implementación real, testable y operator-safe de `migration/dysflow_client.execute_legacy_sql`. Ver §"Runtime boundary verificado" abajo. NO se wirea Dysflow MCP desde Python.
- **M0 — Bootstrap completo**: ejecutar `ShadowStateRepository.ensure_table()` y `apply_sql_migrations()` contra InsForge; crear el bucket privado `apap-photos` vía MCP infrastructure.
- **M1 — Animales + entradas + voluntariado mínimos (datos reales, PII completa)**: `apply --table animal`, `entrada`, `voluntario` (incluye `DNI`/`Email`/`Tel1`/`Tel2`). Shadow state preserva DNI. Pre-flight con conteos y SHA-256 del legacy. Reconciliación post-apply con `animal_lifecycle_events`.
- **M1 — Fotos privadas**: SHA-256 + tamaño como `nombrefoto`, upload a bucket `apap-photos` (no público), display vía `/animales/{animal_id}/foto` autenticado (`animal_id` es `animales.id` UUID; NCHIP queda como natural key de lookup, no como identificador de ruta). Orfandad/deduplicación por SHA-256.
- **M1 — Navegación autenticada end-to-end**: `/animales`, `/voluntarios`, `/entradas` funcionando contra datos reales; sólo el contenido de aplicación público es `/login` (per AGENTS.md §18 + `PUBLIC_PATHS` verificado en `app/main.py:148`, que también incluye los endpoints de protocolo/operativos `/healthz`, `/auth/google`, `/auth/callback`, `/logout` — ninguno de ellos expone contenido de aplicación ni PII).
- **M1 — Audit + runbook**: `docs/audits/pii-live-migration-2026-Q3.md`, `docs/runbooks/migrate-live-data.md`.
- **M2 — Reverso `web→legacy` (gate de fallback-readiness)**: `apply_web_to_legacy` con reconciliación shadow + semantics; round-trip test para DNI/voluntario/animal; reconciliación de divergencias `needs_review` vía CLI. NO se reclama "fallback ready" sin M2 verde.

### Fuera (Non-goals)

- **NO** bucket público ni galería pública. Las fotos son privadas; cualquier ruta de display exige `require_authorized_user`.
- **NO** release/tag de producción. Migración a producción es decisión de usuario posterior; este change es sandbox/dev/staging.
- **NO** cambios al schema Access/.accdb ni destructive cleanup del filesystem legacy. El legacy es read-only para nosotros.
- **NO** wiring del MCP Dysflow como dependencia de runtime. Dysflow MCP es tooling del agente; no se invoca desde código de migración.
- **NO** `bulk_upsert` MCP para PII (evidencia explícita abajo).
- **NO** UI para resolver `needs_review` (heredado de `web-only-feature-preservation`).
- **NO** anonimización: el usuario explícitamente pidió PII real completa.

## Decisiones de producto (key)

| ID | Decisión | Justificación |
|---|---|---|
| **D-LIVE-01** | Runtime boundary verificado para legacy reads (ver § abajo) | La exploración sugirió wirear Dysflow MCP desde Python; eso es **incorrecto** (MCP = agent tooling, `writeExecutionPolicy: safe-by-default`, sin SLI). Proponemos boundary explícito. |
| **D-LIVE-02** | Bucket privado `apap-photos` (no público) | Privacy default-deny (§18 + §6); display exige auth. |
| **D-LIVE-03** | PII completa migrada (DNI, Email, Tel1, Tel2) con `log_safe` y `count+hash` en evidencia | Directiva explícita del usuario. `DNI` mantiene `web_only_strategy: preserve` y UNIQUE constraint actual; legacy sin DNI se acepta NULL. |
| **D-LIVE-04** | Bidireccionalidad por milestone: M1 = forward usable; M2 = reverse + round-trip = gate de fallback-readiness | AGENTS.md §18.1 exige sync bidireccional; el usuario acepta phased forward pero NO fallback claim sin M2. |
| **D-LIVE-05** | Chained PRs dentro de un change con `size:exception` aprobado por maintainer | Usuario aprobó `size:exception` para todos los PRs de APAP_WEB. |
| **D-LIVE-06** | Foto path: preflight Dysflow `get_capabilities` + `list_access_files` resuelve `URLDirectorioDocumentacion` y cuenta fotos vs. filas con `NombreFoto` no-NULL | Bound por evidencia; sin bloquear al usuario. |
| **D-LIVE-07** | Source snapshot identity: SHA-256 del .accdb + del directorio de fotos, persistido en `migration.lock_snapshot.json` por apply | Detección de drift entre runs; auditable. |
| **D-LIVE-08** | Collision policy: `DNI` UNIQUE — duplicados legacy → primer registro gana, resto a `needs_review` con `web_only_feature_shadow.review_reasons=["dni_collision"]` | Legacy NO enforce UNIQUE; la web sí. Política conservadora auditable. |

## Runtime boundary verificado para legacy reads (corrección a la exploración)

La exploración §3 sugirió *"Wire Dysflow MCP `query_execute` into `migration/dysflow_client.py`"*. **Esto es incorrecto** porque:

1. Dysflow MCP tiene `effectiveDryRunDefault: true` para 60 tools de write y `writeExecutionPolicy: "safe-by-default"` — está diseñado para uso del agente, no como API de runtime.
2. No hay SLO, rate limit, ni auth stable contract para invocarlo desde un proceso de migración largo.
3. Su ciclo de vida está atado a la sesión del agente.

**Boundary propuesto** (decisión técnica abierta al design):

| Opción | Testabilidad | Operator safety | Producción-ready | Notas |
|---|---|---|---|---|
| **A. `pyodbc` + Microsoft Access Driver (.accdb)** | ✅ tests con `FakeExecutor` via `set_legacy_query_executor()` | ✅ stdlib Windows + access driver estable | ✅ | Camino estándar en Windows; driver `Microsoft Access Database Engine` redistribuible |
| **B. Adapter de snapshot determinista (Access exporta a CSV/JSON al inicio)** | ✅ fixtures reproducibles | ✅ boundary testable, sin locks concurrentes | ✅ con runbook | Aísla del .accdb; necesita Access corriendo o export pre-hecho |
| **C. Subprocess a tool standalone (e.g., `mdb-export` o Access con VBA export)** | ✅ fixtures | ⚠️ dep externa | ⚠️ depende del tool | Más frágil; candidato a spike |
| **D. Invocar Dysflow MCP desde Python (sugerencia de la exploración)** | ❌ atado al ciclo del agente | ❌ `dryRun` por defecto | ❌ | **Rechazado por las razones arriba** |

**Recomendación provisional**: A (pyodbc) como primary, B como fallback documentado. **Decisión final reservada a design** con un spike explícito (TDD-loop §8.3) que compare tests + operator docs + tiempo de read para 5.000 filas. No se adivina.

El seam actual (`migration/legacy_reader.set_legacy_query_executor()` + `dysflow_client.execute_legacy_sql`) **se preserva**: cambia el cuerpo de la función, no su firma ni los tests.

## Capabilities (contract con sdd-spec)

### New Capabilities

- `live-migration-runtime-boundary`: contrato del executor legacy real (testabilidad, lock semantics, error semantics).
- `live-migration-private-photo-storage`: bucket privado, display autenticado, SHA-256 idempotencia, orphan/dup handling.
- `live-migration-pii-controls`: redacción `log_safe`, evidencia `count+hash`, colisión `needs_review`, source snapshot identity.
- `live-migration-bidirectional-completion`: reverse path `web→legacy`, round-trip test, CLI de reconciliación interactiva para divergencias.

### Modified Capabilities

- `migration-discovery-docs` (delta): añade `source-snapshot-identity` y `collision-policy` al discovery.
- `web-only-feature-preservation` (delta): reutiliza `post_apply_diff` para `direction="web-to-legacy"` con `preserve/derived/fixed` strategies.

## Approach

1. **M0**: Implementar `execute_legacy_sql` con la opción seleccionada (pyodbc como default provisional). Wiring de `check_msaccess_running()` en `apply_legacy_to_web` pre-flight. Crear bucket. Smoke test con `--check-only`.
2. **M1**: `apply_legacy_to_web` para `animal` + `entrada` + `voluntario`. Photo migration como pase secundario con SHA-256. Audit + runbook.
3. **M2**: `apply_web_to_legacy` simétrico; `post_apply_diff` bidireccional. Round-trip test (legacy→web→legacy preserva NCHIP, Voluntario, hash). Reconciliación interactiva.
4. **PR strategy**: chained PRs por milestone; cada uno ≤ 600 líneas (excepción aprobada por maintainer según `size:exception` global).

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `migration/dysflow_client.py` | Modified | `execute_legacy_sql` real (M0) |
| `migration/apply.py` | Modified | Wire `check_msaccess_running()` pre-flight; reverse direction (M2) |
| `migration/mappings/animal.yaml` | Modified | Storage mapping para fotos (`storage.bucket=apap-photos`, `storage.key=<sha256>.<ext>` propuesto por el cliente; el server puede renombrar y el `key` retornado es canónico — NCHIP es natural key de lookup, no del storage object) |
| `migration/mappings/voluntario.yaml` | Modified | Confirmar `DNI` UNIQUE handling + colisión policy |
| `app/core/insforge.py` | Modified | `upload_object()`, `download_object()`, `signed_get_url()` (privado) |
| `app/modules/animals/routes.py` | Modified | `GET /animales/{animal_id}/foto` autenticado (`animal_id` es `animales.id` UUID; NCHIP es natural key de lookup, no de ruta) |
| `app/core/middleware.py` | Unchanged | `PUBLIC_PATHS` vive en `app/main.py:148` (no en middleware); ningún cambio aquí. `PUBLIC_PATHS` actual = `{"/healthz", "/login", "/auth/google", "/auth/callback", "/logout"}` (5 entradas verificadas; sólo `/login` es contenido de aplicación público, los otros cuatro son endpoints de protocolo/operativos). |
| `docs/audits/pii-live-migration-2026-Q3.md` | New | Audit PII scope, methodology, findings, verdict |
| `docs/runbooks/migrate-live-data.md` | New | Runbook operador |
| `tests/migration/test_runtime_boundary.py` | New | Tests del executor + colisión + foto |
| `tests/migration/test_round_trip.py` | New | Test legacy→web→legacy para M2 |

## Milestones: "Usable ya" vs "Fallback ready"

| Estado | Significa | Gates |
|---|---|---|
| **Usable ya** (M0+M1 cerrados) | Forward import end-to-end con PII real; web app navega datos reales autenticado; fotos privadas con display autenticado; auditoría completa | counts legacy == counts web por tabla; SHA-256 reproduce determinístico; bucket privado; `log_safe` no emite PII raw; audit doc PASS |
| **Fallback ready** (M2 cerrado) | Lo anterior + reverse `web→legacy` + round-trip verde + reconciliación `needs_review` operativa | round-trip test verde; `apply_web_to_legacy --check-only` simétrico al forward; 1 ciclo real con operator assist |
| **Production-ready** (NO scope) | NO es objetivo. Requiere decisión de usuario + release/tag fuera de este change | out of scope |

## Riesgos

| Riesgo | Likelihood | Mitigación |
|---|---|---|
| Driver ODBC Access no instalado en operator box | Med | Runbook pre-flight (`pyodbc.drivers()` listing + install link) |
| `.accdb` lock contention (Access abierto) | Med | `check_msaccess_running()` ya existe; se wirea en M0 |
| Bucket mal configurado como público | Low | Test invariant: `get_bucket.isPublic == False` en pre-flight |
| DNI legacy colisión → UNIQUE violation | Med | Collision policy D-LIVE-08 + reconciliación interactiva |
| PII raw en logs | Med | Test invariant: `log_safe` con redaction list (12 campos) verificado por tests |
| Drift legacy↔web entre apply y reverse | Med | Source snapshot identity + round-trip test obligatorio |
| Reverse path incompleto al claim fallback-ready | High sin gate | **M2 gate**: sin round-trip verde NO se reclama fallback |
| Tamaño de PR excede budget aunque con `size:exception` | Med | Chained PRs por milestone; cada uno ≤ 600 líneas |

## Rollback Plan

| Capa | Rollback |
|---|---|
| **InsForge tablas de dominio** | `DELETE FROM animales WHERE nchip IN (legacy_ids)` — verificado antes en pre-flight; shadow rows quedan para auditoría |
| **`web_only_feature_shadow`** | Truncar (la tabla es staging del round-trip; no contiene PII fuera de las FK a web) |
| **Bucket `apap-photos`** | `delete-bucket` vía MCP; las `animales.nombrefoto` quedan con SHA-256 pero `404` en GET → display fallback a placeholder |
| **`migration.lock_snapshot.json`** | Borrar; el siguiente apply regenera |
| **Lock activo** | `rm migration.lock` si PID verificado muerto vía `psutil.pid_exists()` |
| **Source legacy** | **NO SE TOCA**. Rollback NO destruye `APAP_ACTUAL.accdb` ni `URLDirectorioDocumentacion` |
| **Volver a Access-only** | `APAP_MODE=legacy` arranca con backend Access; la web queda intacta pero no se sincroniza |

## Dependencies

- Microsoft Access Database Engine (ODBC driver) en operator box — runbook pre-flight
- `pyodbc` añadido a `[project.optional-dependencies.etl]` (preflight via context7)
- InsForge bucket creation via MCP (one-time infra)
- Sin nuevas dependencias en runtime web (la foto display usa HTTPX ya pinned)

## Success Criteria

- [ ] **M0**: `apap-migrate status --table animal` retorna counts reales; bucket existe y `isPublic=false`; `check_msaccess_running` integrado.
- [ ] **M1**: `apap-migrate apply --table animal --voluntario --entrada` con datos reales completa sin error; `log_safe` no emite PII raw (test invariant); `apap-migrate reconcile --check-only` retorna 0 `needs_review` post-apply (excepto colisiones declaradas).
- [ ] **M1**: `GET /animales/{animal_id}/foto` (UUID) autenticado retorna 200 con bytes correctos; sin auth retorna 302 a `/login`.
- [ ] **M1**: Audit `docs/audits/pii-live-migration-2026-Q3.md` con verdict PASS.
- [ ] **M1**: Runbook `docs/runbooks/migrate-live-data.md` ejecutable por operador no-desarrollador en < 30 min.
- [ ] **M2 (fallback gate)**: Round-trip test verde (legacy→web→legacy NCHIP+Voluntario+hash); `apply_web_to_legacy --check-only` simétrico.
- [ ] **Source snapshot identity**: cada apply persiste SHA-256 del `.accdb` + del dir de fotos en `migration.lock_snapshot.json`.
- [ ] **Privacy invariant**: tests verifican que `DNI`/`Email`/`Tel1`/`Tel2` nunca aparecen en `log_safe` payloads ni en `web_only_feature_shadow.preserved_value` sin máscara.
- [ ] **Authorization invariant**: tests verifican que `GET /animales/{animal_id}/foto` (UUID) y todas las rutas excepto las `PUBLIC_PATHS` de `app/main.py:148` (`/healthz`, `/login`, `/auth/google`, `/auth/callback`, `/logout`) rechazan sin sesión; sólo `/login` es contenido de aplicación público (los otros cuatro son endpoints de protocolo/operativos).
- [ ] **P1 fidelity**: cada capability legacy representable tiene trace chain (legacy capability → modelo web → test path).

## Out of scope (recordatorio)

NO public gallery · NO production release/tag · NO Access schema change · NO destructive source cleanup · NO bulk_upsert MCP for PII · NO Dysflow MCP as runtime dep · NO anonimización.