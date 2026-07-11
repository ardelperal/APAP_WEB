# Hoja de Ruta Viva — APAP_WEB

> Documento vivo. Punto de entrada único para saber qué hay que construir, en qué orden, qué issues lo cubren y qué documentación ya existe. Si una pregunta se responde aquí, no hay que rebuscar.

**Última actualización:** 2026-07-11 (refresco: cierre PR1/M0 de `live-data-migration-sandbox` con PR #176 merge commit `0d2e72d` — Closes #175, runtime pyodbc boundary sin dependencia MCP y seam `set_legacy_query_executor` estable M0→M2; cierre PR2 de `live-data-migration-sandbox` con PR #180 commits `3bc53bc`+`91be88a` (merge `df483e3`) — Closes #179, `ShadowStateRepository` bootstrap + private `apap-photos` bucket con `isPublic=false` y runbook hardenizado (DROP TABLE/delete-bucket destructivos documentados; TRUNCATE no recomendado); cierre #141 `fecha_final` silent-data-loss con PR #151 commit `4d4b3cd`; cierre #142 P1 audit-log atomicity con PR #155 commit `3672d33` + PR #156 commit `27cab72` + cherry-pick `28d04e9`; cierre #143 P1 re-validación de `is_authorized`/`rol` per-request con PR #152 commit `6058a5a`; cierre #45 FOSTER-03 con commits `3e51829`+`5d77cdb`; cierre #47 ADOPT-01 con commits `62b9a46`+`4038a3a`; `main` queda sincronizado con GitHub Issues y CI verde)
**Mantenedor único:** aroman (autoaprueba issues y PRs)
**Rama objetivo actual:** **pre-MVP single-branch** — todo va a `main`, una sola rama al final del ciclo (ver §8 y `AGENTS.md` §15)
**Idioma de toda la documentación, issues y PRs:** castellano (España)

---

## 1. TL;DR

- **CI/CD foundation (Fase 0):** CI-01, CI-02, CD-01 y CD-02 están **todos en verde en `main`** desde el 2026-07-03. El deploy automático al push a `main` se ejecuta vía webhook firmado a Coolify (`COOLIFY_WEBHOOK_URL` + `COOLIFY_WEBHOOK_SECRET` configurados; verificado en CI run 28674612470). El primer deploy real sigue pendiente del DNS `apap.romancaba.com` (operación manual del mantenedor).
- **Infraestructura:** repositorio, Coolify y backend de InsForge ya aprovisionados. Runnable de la aplicación en producción pendiente solo del DNS.
- **Producto (Fases 1-7):** **Fase 1 ✅ mergeada en `main` (#17, commit `d0b1ed1`)**. **Fase 2 ✅ mergeada en `main` (#16, commit `1d22349`)**. **Fase 5a INTAKE cerrada**: INTAKE-01 ✅ (#87/#88/#89), INTAKE-02 ✅ (#40, commit `c7b69ec`), INTAKE-03 ✅ (#41, PR #136, commit `98e80c5`). **Fase 5b FOSTER**: FOSTER-01 ✅ (#43, commit `25e749e`) con entidad propia `casas_acogida` + `capacidad` (legacy `TbAcogidaCasas` 1:1 + 2 mejoras justificadas: `id` UUID y `capacidad INTEGER > 0`). FOSTER-02 ✅ (#44, commit `b7f197f`) con CRUD de estancias referenciando `casas_acogida` (FK estructurada vía `ALTER TABLE ADD COLUMN IF NOT EXISTS`) y `voluntarios` activos (active check per VOL-05); helpers públicos `compute_duracion` e `is_active`; `close_acogida` vs `delete_acogida` separados semánticamente (D-EST-04). FOSTER-03 ✅ (#45, commits `3e51829`+`5d77cdb`, 2026-07-04) con species gate hard + capacity advisory auditado (nuevo módulo `app/modules/foster/assignment.py` con `evaluate_assignment` y `record_override`; cierre de OD-3a y D-18); FOSTER-04 🔲 (#46) pendiente. ADOPT-01 ✅ (#47, commits `62b9a46`+`4038a3a`, 2026-07-04) con CRUD de adopciones referenciando `voluntarios` activos (FK estructurada per VOL-05) + `donativo_adopcion` numeric + `tipo_adopcion` regular/preadopcion/judicial; ADOPT-03 🔲 (#49). Fases 3-7 pendientes. El código de auth está listo; tabla `authorized_users` creada y seedeada (#25).
- **Issues UI/copy recientes (cerradas):** #124 logout → login, #125 OAuth callback loop, #126 UI sin copy interno + campos obligatorios Access, #127 home con tarjetas, #128 eliminar lenguaje interno, #131 labels castellanos. XSS allowlist detectado y fixado en `a528566`.
- **P1/P0 security follow-ups cerrados hoy (2026-07-05):** #141 `fix(acogidas) fecha_final` silent-data-loss (PR #151, commit `4d4b3cd`); #142 `feat(foster) override→estancia atomicity` (PR #155 commit `3672d33` + PR #156 commit `27cab72` + cherry-pick `28d04e9`); #143 `fix(auth) revocación inefectiva` con re-validación per-request vía caché TTL (`auth_cache_ttl_seconds` = 300s) + invalidación explícita al dar de baja (PR #152, commit `6058a5a`; audit en [`docs/audits/auth-revalidation-2026-Q3.md`](audits/auth-revalidation-2026-Q3.md) — **PASS**).
- **Documentación de discovery:** generada y consistente. Antes de tocar el legacy, leer `docs/discovery/` (ver §7). Decisiones de proyecto consolidadas en `docs/decisiones-proyecto.md` (nuevo, 2026-07-03).
- **Proceso operativo:** el playbook end-to-end por issue está en **`docs/proceso.md`** (creado 2026-07-03, PR #132 merge `5329ec5`). Es lectura obligatoria antes de tomar cualquier issue que vaya más allá de un doc trivial.

---

## 2. Estado actual (2026-06-19)

| Área | Estado | Detalle |
|---|---|---|
| Repositorio `ardelperal/APAP_WEB` | ✅ | Creado, `main` como rama por defecto |
| CI local (pytest + ruff + build) | ✅ | Phase 0 de `ci-cd-foundation` merged en `main` |
| GitHub Actions workflow | ✅ | `ci / lint`, `ci / test`, `ci / build` en PRs y push a `main`; `deploy` en push a `main` (skip en merge commits). Pre-MVP single-branch: ya no hay push a `staging` (§8). |
| Branch protection en la rama protegida activa | 🔲 | Documentado en `.github/branch-protection.md`; pendiente de activar en la UI de GitHub (tarea 1.5) |
| Proyecto Coolify + app `apap-web` | ✅ | Aprovisionado, apunta a `ardelperal/APAP_WEB:main`, fqdn `apap.romancaba.com` |
| DNS `apap.romancaba.com` | 🔲 | Pendiente de crear por el mantenedor antes del primer deploy real |
| Fix de dominio OAuth (redirect URI) | ✅ | Commit `3c32f3e` en main; `APAP_GOOGLE_REDIRECT_URI` corregido en Coolify; redeploy OK |
| CD-02 build y push del runnable a Coolify | ✅ | Mergeado en `main` como `dc98c1c` (PR #24) — Dockerfile corregido, build verificado |
| CD-01 webhook automático GitHub → Coolify en `push: main` | ✅ | Implementado y verificado (CI run 28674612470 el 2026-07-03). El job `deploy` ejecuta `scripts/coolify_webhook.py` con HMAC SHA-256 firmado contra `COOLIFY_WEBHOOK_URL` + `COOLIFY_WEBHOOK_SECRET`. Issue #1 cerrada. |
| Backend InsForge | ✅ | Verificado, MCP configurado; `APAP_INSFORGE_URL` apuntando a `c3uc9dk6.eu-central.insforge.app` |
| Tabla `authorized_users` en InsForge | ✅ | Creada y seedeada con `ardelperal@gmail.com` (developer) — issue #25; idempotente con `CREATE TABLE IF NOT EXISTS` |
| Esqueleto de la app FastAPI | ✅ | Mergeado en `main` como `d0b1ed1` (issue #17) |
| Login real con Google OAuth + allowlist | ✅ | Mergeado en `main` como `1d22349` (issue #16); tabla `authorized_users` creada y seedeada (#25). Pendiente solo el primer deploy real cuando el DNS esté resuelto. |
| Foundation UX/UI | 🔲 | Issue #6 abierto |
| Motor común de tareas | 🔲 | Issue #7 abierto |
| Hoja de ruta viva | ✅ | Esta issue #14 (mergeada en `69b509e`) |

---

## 3. Hoja de ruta por fases

> Leyenda: ✅ completado · 🟡 en curso · 🔲 pendiente · 🚫 bloqueado

### Fase 0 — Infraestructura y CI/CD

**Objetivo:** repositorio sano, CI verde, deploy automatizado a Coolify + InsForge.

| Slice | Estado | Issue | PR | SDD |
|---|---|---|---|---|
| CI-01 superficie de tests local | ✅ | — | merged | `ci-cd-foundation` Phase 0 |
| CI-02 workflow de GitHub Actions | ✅ | — | merged | `ci-cd-foundation` Phase 1 |
| CD-02 build y push del runnable a Coolify | ✅ | #1 | #24 (`dc98c1c`) | `ci-cd-foundation` Phase 2 |
| CD-01 webhook automático GitHub → Coolify en `push: main` | ✅ código en `225ef9c` + dry-run real verificado en CI run 28674612470 el 2026-07-03 (`COOLIFY_WEBHOOK_URL` + `COOLIFY_WEBHOOK_SECRET` configurados; skip en merge commits) | #1 | — | `ci-cd-foundation` Phase 2 |
| ~~CD-02 InsForge `insforge_create-deployment` step~~ | ~~🔲~~ N/A (2026-06-19) | #1 | — | — |
| Branch protection activado en la rama protegida activa (`staging` para trabajo normal; `main` si producción lo requiere) | 🔲 | — | — | `ci-cd-foundation` tarea 1.5 |
| Harness E2E (Playwright) | 🔲 | — | — | `E2E-01` (diferido a `staging`) |

**Pendiente del primer deploy real (no automatizable):**

- Crear el registro DNS A de `apap.romancaba.com` apuntando al servidor Coolify.
- Verificar que el redirect URI registrado en Google Cloud Console / InsForge shared OAuth es `https://apap.romancaba.com/auth/callback` (no `romancabanillas`).

**Documentación de referencia:**

- [`docs/development.md`](development.md) — flujo local del desarrollador
- [`docs/architecture-insforge-stack.md`](architecture-insforge-stack.md) — decisiones de stack
- [`docs/setup.md`](setup.md) — setup por desarrollador y credenciales InsForge
- [`openspec/changes/ci-cd-foundation/`](../../openspec/changes/ci-cd-foundation/) — propuesta, diseño, tareas, spec, apply-progress

### Fase 1 — Esqueleto de la aplicación web (#17)

**Objetivo:** `app/` mínimo con FastAPI + Jinja2 + Tailwind compilando, sin reglas de negocio todavía.

> ✅ **Cerrada**. Issue **#17** mergeada en `main` como `d0b1ed1`. Desbloquea Fase 2 (#16) y Fase 3.

**Decisiones pendientes:**

- Estructura exacta de `app/` (ver `docs/architecture-insforge-stack.md` § "Recommended project shape").
- Cómo se compila Tailwind v4 dentro del Dockerfile.
- Endpoint de health check (necesario para CD-02).
- Convenciones de `app/core/` (config, security, database) y de `app/modules/<dominio>/`.

### Fase 2 — Autenticación y autorización (#16)

**Objetivo:** login real con Google OAuth vía InsForge y allowlist de correos autorizados, con panel admin para el rol `developer`.

> ✅ **Cerrada**. Issue **#16** mergeada en `main` como `1d22349`. Login con Google OAuth (PKCE nativo contra InsForge), tabla `authorized_users` con seed bootstrap, middleware de allowlist, panel `/admin` para developers. Tabla real creada y seedeada (#25); deploy verificado (#1). Pendiente solo el primer deploy real cuando el DNS esté resuelto.

**Documentación de referencia:**

- [`docs/architecture-insforge-stack.md`](architecture-insforge-stack.md) § "Authentication and authorization"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § D-01, D-03, D-20, D-40

### Fase 3 — Modelo de dominio limpio (Animal + Volunteer + anexos)

**Objetivo:** tablas `animals`, `volunteers`, `authorized_users` y la tabla mínima de anexos. Sin UI de producto todavía.

> 🟡 En curso. `authorized_users` ✅ (issue #25). `animals`, `volunteers`, `volunteer_roles` ✅ (issue #26). Pendiente: `animal_event_log` (Fase 4 con CRUD) y `attachments` (Fase 7 con bucket de Storage). Bloquea Fases 4-7. Refresco 2026-07-03: paridad de campos de `animals` con el Access legacy cerrada en #129 (`cfba764`, PR #134).

**Documentación de referencia:**

- [`docs/architecture-insforge-stack.md`](architecture-insforge-stack.md) § "Data model policy"
- [`docs/discovery/data-model-notes.md`](discovery/data-model-notes.md)
- [`docs/discovery/data-model-completeness.md`](discovery/data-model-completeness.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § D-04 (paridad de campos), D-05 (fidelidad al legacy)

### Fase 4 — Entidad Animal (Feature 01)

**Objetivo:** CRUD de animales, búsqueda parametrizada, timeline de eventos y motor de estado derivado.

> Pendiente de crear issue. Depende de Fase 3.

**Documentación de referencia:**

- [`docs/discovery/feature-01-animal-lifecycle.md`](discovery/feature-01-animal-lifecycle.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Timeline del animal"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Ficha del animal: inspiración legacy"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Propuesta automática de transición"
- `docs/mockups/ficha-animal-timeline.html` — *(referencia rota: crear cuando arranque Fase 4)*

### Fase 5 — Voluntarios + Entradas + Acogidas + Adopciones (Feature 02)

**Objetivo:** flujos operativos centrales con asistentes por pasos y snapshots históricos de personas.

> 🟡 **En curso (Fase 5a INTAKE cerrada, Fase 5b FOSTER y Fase 5c ADOPT en curso)**: INTAKE-01 cerrado (schema + service + routes — #87, #88, #89, mergeadas 2026-06-28). INTAKE-02 cerrado (#40, commit `c7b69ec`, 2026-07-04) con staging + commit atómico. INTAKE-03 cerrado (#41, schema + service + routes + form, mergeada 2026-07-03 vía PR #136, commit `98e80c5`). INTAKE-04 (#42) quedó cubierto por CATALOG-01 (#65, PR #135). **FOSTER-01 cerrado** (#43, commit `25e749e`, 2026-07-04) con entidad propia `casas_acogida` + `capacidad` (legacy `TbAcogidaCasas` 1:1 + 2 mejoras justificadas: `id` UUID y `capacidad INTEGER > 0`). **FOSTER-02 cerrado** (#44, commit `b7f197f`, 2026-07-04) con CRUD de estancias de acogida que referencian `casas_acogida` (FK estructurada vía `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) y `voluntarios` activos (active check per VOL-05); helpers públicos `compute_duracion` (días entre fechas, `None` si abierta) e `is_active` (`activo AND fecha_final IS NULL`); separación semántica `close_acogida` (evento de ciclo de vida: `fecha_final = current_date`, `activo` se mantiene `true`) vs `delete_acogida` (soft-delete real: `activo = false`, `fecha_baja = now()`); 8 endpoints con CSRF + auth; tests TDD (38 service + 23 routes + 3 nuevos domain + 3 nuevos XSS). **FOSTER-03 cerrado** (#45, commits `3e51829`+`5d77cdb`, 2026-07-04) con species gate hard (cierre OD-3a) + capacity advisory auditado (cierre D-18); nuevo módulo `app/modules/foster/assignment.py` con `evaluate_assignment` (`AssignmentDecision` Literal admit/block/admit_with_warning) y `record_override` (audit log + `log_safe`); tabla propia `foster_capacity_overrides` (id, casa_acogida_id, animal_id, operador_user_id, motivo, created_at) vía `CREATE TABLE IF NOT EXISTS`; nuevo sub-router `/casas-acogida/{id}/asignar` y `/casas-acogida/{id}/overrides`; P0 species-gate bypass en `POST /acogidas` cerrado vía `_enforce_species_gate`; overrides restringidos a `developer` rol vía `require_developer_user`. FOSTER-04 (#46) sigue 🔲. **ADOPT-01 cerrado** (#47, commits `62b9a46`+`4038a3a`, 2026-07-04) con CRUD de adopciones referenciando `voluntarios` activos (FK estructurada per VOL-05); `donativo_adopcion` numeric (rechazo explícito de bool) + `tipo_adopcion` `regular`/`preadopcion`/`judicial` vía ALTER TABLE idempotente (D-EST-05); CTE atómico create/update (TOCTOU fix); `search_adopciones_by_adoptante` con ILIKE case-insensitive y `ESCAPE '\\'`; soft-delete atómico `UPDATE ... WHERE id = $1 AND activo = true RETURNING id` (D-ADOPT-03); 7 endpoints con CSRF + auth; tests TDD (29 service + 20 routes) más 16 tests de remediación post-review (CTE-shape, 403 reader→writer, FK disambiguation, wildcard escaping, 100-row cap). ADOPT-03 (#49) sigue 🔲.

**Documentación de referencia:**

- [`docs/discovery/feature-02-intake-foster-adoption.md`](discovery/feature-02-intake-foster-adoption.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § D-03 (dominio centrado en Animal), D-05 (fidelidad al legacy)
- [`docs/legacy-volunteer-roles.md`](legacy-volunteer-roles.md)
- [`docs/legacy-lifecycle-transition-rules.md`](legacy-lifecycle-transition-rules.md)

### Fase 6 — Salud, Terapias e Inventario de Material (Feature 03)

**Objetivo:** registro sanitario con periodicidad, terapias con recomendaciones, inventario de material con disponibilidad e historial de asignaciones.

> Pendiente de crear issues (uno por sub-flujo). Depende de Fases 3-4.

**Documentación de referencia:**

- [`docs/discovery/feature-03-health-care.md`](discovery/feature-03-health-care.md)
- [`docs/legacy-health-ui-workflow.md`](legacy-health-ui-workflow.md) — análisis detallado del workflow legacy de salud
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Pestaña Salud del animal"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Pestaña Terapias del animal"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Terapias: inventario de material y asignación"

### Fase 7 — Documentos, Contratos, Informes y Consultas (Feature 04)

**Objetivo:** anexos, motor de plantillas documentales, los 8 tipos de contrato, módulo de Consultas propio e informe trimestral.

> Pendiente de crear issues (uno por sub-flujo). Depende de Fases 3-6.

**Documentación de referencia:**

- [`docs/discovery/feature-04-documents-contracts-reports.md`](discovery/feature-04-documents-contracts-reports.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Motor de plantillas documentales"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Documentos generados como fuente de verdad"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Organización de documentos y anexos"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Flujo de contratos para firma y firmados"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Consultas como módulo de primer nivel"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Informe trimestral — alcance core"
- [`docs/legacy-signed-contract-flow.md`](legacy-signed-contract-flow.md)

### Fase transversal — Migración en vivo del legacy (backend privado con datos y fotos reales)

**Objetivo:** disponer de un backend privado (InsForge) poblado con los datos y las fotos reales del Access legacy, en una sola dirección controlada y verificable, antes de abrir Fases 4-7 a datos productivos. Precedencia operativa: PR3 → PR4a → PR4b → PR5 → PR6 → PR7 → E2E Playwright canónico CI → unidades de trabajo de operador (Phase 4 de `tasks.md`) solo con los gates de código en verde. La prioridad inmediata es un backend privado usable (datos y fotos reales del legacy), no un reemplazo del Access como fuente.

> 🟡 **En curso (PR1/M0 runtime boundary cerrado, PR2/M0 ShadowStateRepository + bucket privado cerrado; M1 + M2 pendientes).** PR1 (pyodbc executor sin dependencia MCP, seam `set_legacy_query_executor` estable M0→M2) mergeado como PR #176 / merge commit `0d2e72d` (Closes #175) el 2026-07-11. PR2 (`ShadowStateRepository.ensure_table()` + private `apap-photos` bucket con `isPublic=false` invariable fail-closed + runbook endurecido) mergeado como PR #180 / merge commit `df483e3` (Closes #179) el 2026-07-11. PR3 sigue siendo el siguiente paso para cerrar M1. **M1 pendiente**: PR3 (`lock_snapshot` + MSACCESS pre-flight + `MigrationReport.counts/source_hashes/collisions`), PR4a (storage contract spike en vivo contra InsForge — gate sin código de producto, fija el contrato canónico y los headers de auth), PR4b (storage implementation + ruta autenticada `GET /animales/{animal_id}/foto` + `REDACTED_FIELDS += {dni,tel1,tel2}` + audit PII + runbook `migrate-live-data`), PR5 (controles PII sobre logs + CLI reconcile `--filter-direction` + riesgos de migración). **M2 pendiente**: PR6 (`apply_reverse.py` simétrico + round-trip tests preservando `nchip`/`dni` + emisión `LIFECYCLE_REVERSED`), PR7 (gate `verify-fallback-ready` con `--ci-only` para CI + `--full` con atestación de operador). Tras PR7 verde, E2E canónico CI en `tests/e2e/test_animals_foto_auth.py` (3 paths: autenticado 200 / 302 a `/login` sin sesión / sentinel `__missing__`, con buckets `apap-photos-test-<8hex>` efímeros creados y borrados dentro de cada test).

**Invariantes no negociables (definidas por `proposal.md` y `tasks.md`):**

- **Privacidad de datos y fotos**: bucket `apap-photos` con `isPublic=false` (invariante PR2 + test `test_public_bucket_aborts` con exit 5). La ruta `GET /animales/{animal_id}/foto` requiere sesión válida (302 a `/login` si no autenticado), sirve bytes por `StreamingResponse` desde `download_object_stream` y nunca expone URL pública. PII ampliada en `REDACTED_FIELDS` (de 12 a 15 campos: `dni`, `tel1`, `tel2` añadidos en PR4b); invariante verificado en PR2 con `test_bucket_visibility_missing_or_null_fails_closed` (502 `bucket_visibility_unknown` ante `isPublic` ausente o null) y `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy` (no lock ni read en bootstrap failure). PR4b traerá la ruta autenticada y la ampliación de `REDACTED_FIELDS`.
- **M1 forward usable NO es fallback-ready**: tener M1 verde (animales, voluntarios, entradas y fotos migrados vía `apply_legacy_to_web`) NO equivale a poder volver atrás mientras el legacy siga siendo la fuente. **El round-trip M2 (PR6) y el gate `verify-fallback-ready` (PR7) son obligatorios** antes de cualquier decisión de retirar el Access legacy como fuente operativa.
- **TDD estricto, fixture-first, idempotente**: cada PR arranca con RED (tests antes de código) bajo `tests/migration/` y `tests/test_*.py`. PR1 fijó la pauta (14 átomos + seam `set_legacy_query_executor` + autouse fixture `_reset_legacy_executor` en `tests/migration/conftest.py`). E2E canónico CI vive en `tests/e2e/test_animals_foto_auth.py` (3 paths por test, buckets efímeros); Playwright MCP es diagnóstico de operador y NO corre en CI.
- **Ejecución con datos reales solo tras los gates de código**: las unidades de trabajo de operador listadas en `tasks.md` Phase 4 (`ensure-bucket --check-only`, `apply --check-only`, `apply`, `reconcile --check-only`, `status --photos`, `verify-fallback-ready --full`) se ejecutan exclusivamente después de que los gates de código (lint + test + build + `verify-fallback-ready --ci-only` en CI) estén verdes. Sin `verify-fallback-ready` verde y auditado, no se autoriza el cambio de modo.

**Documentación de referencia:**

- [`openspec/changes/live-data-migration-sandbox/proposal.md`](../openspec/changes/live-data-migration-sandbox/proposal.md) — D-LIVE-01 (runtime boundary verificado): riesgos, fuera-de-alcance y rollback por fase del cambio.
- [`openspec/changes/live-data-migration-sandbox/tasks.md`](../openspec/changes/live-data-migration-sandbox/tasks.md) — PR1-PR7 + Phase 4 (operador) + Phase 5 (E2E); forecast de revisión y chain strategy `auto-chain`. PR1 y PR2 cerrados.
- [`openspec/changes/live-data-migration-sandbox/specs/live-migration-runtime-boundary/spec.md`](../openspec/changes/live-data-migration-sandbox/specs/live-migration-runtime-boundary/spec.md) — capability ya entregada por el merge `0d2e72d` (PR1).
- [`openspec/changes/live-data-migration-sandbox/specs/live-migration-private-photo-storage/spec.md`](../openspec/changes/live-data-migration-sandbox/specs/live-migration-private-photo-storage/spec.md) — invariante de privacidad de fotos (PR2 cerrado: invariante de bucket privado verificado / pendiente PR4b para el storage media + ruta foto + REDACTED_FIELDS += dni/tel1/tel2).
- [`openspec/changes/live-data-migration-sandbox/specs/live-migration-bidirectional-completion/spec.md`](../openspec/changes/live-data-migration-sandbox/specs/live-migration-bidirectional-completion/spec.md) — capacidad de round-trip simétrico (pendiente PR6).
- [`docs/discovery/migration-risks.md`](discovery/migration-risks.md) — riesgos abiertos a actualizar en PR5.

### Fase transversal — Foundation UX/UI y Dashboard

**Objetivo:** design system reutilizable (cargando el skill `frontend-design`) y dashboard de pendientes con realtime.

| Slice | Estado | Issue |
|---|---|---|
| Foundation UX/UI | 🔲 | #6 |
| Dashboard inicial + bandeja de pendientes | 🔲 | pendiente (issue por crear) |
| Búsqueda global | 🔲 | pendiente (issue por crear) |

**Documentación de referencia:**

- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Dirección visual"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Relación con la UX legacy"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Dashboard de pendientes y navegación"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Búsqueda global"
- [`docs/design-tokens-apap-actual.md`](design-tokens-apap-actual.md) — tokens heredados del legacy como referencia
- [`docs/mockups/login-simple-insforge.html`](mockups/login-simple-insforge.html) — mockup login
- [`docs/mockups/login-dashboard.html`](mockups/login-dashboard.html) — mockup dashboard interno
- [`docs/mockups/ficha-animal-timeline.html`](mockups/ficha-animal-timeline.html) — mockup ficha animal
- [`docs/legacy-initial-dashboard.md`](legacy-initial-dashboard.md)

### Fase transversal — Motor de tareas

**Objetivo:** motor único para tareas manuales y tareas automáticas generadas desde eventos del legacy o del dominio.

| Slice | Estado | Issue |
|---|---|---|
| Motor común de tareas | 🔲 | #7 |

**Documentación de referencia:** (crear al arrancar la issue)

### Fase transversal — Traza canónica y panel de control

**Objetivo:** eventos estructurados correlacionados, panel de control para configuración funcional y diagnóstico.

| Slice | Estado | Issue |
|---|---|---|
| Traza canónica (eventos JSON correlacionados) | 🔲 | pendiente (issue por crear) |
| Panel de control / configuración | 🔲 | pendiente (issue por crear) |

**Documentación de referencia:**

- [`docs/canonical-logs.md`](canonical-logs.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Traza canónica del sistema"
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Panel de control / configuración"

### Fase transversal — Documentación unificada en castellano

**Objetivo:** alinear toda la documentación técnica con el idioma del proyecto.

> Decisión del 2026-06-17: toda la documentación, issues y PRs van en castellano. Los docs `docs/architecture-insforge-stack.md` y `docs/development.md` siguen en inglés y deben traducirse.

| Slice | Estado | Issue |
|---|---|---|
| Traducción al castellano de `docs/architecture-insforge-stack.md` | 🔲 | pendiente (issue por crear) |
| Traducción al castellano de `docs/development.md` | 🔲 | pendiente (issue por crear) |
| Revisión y traducción de los `docs/discovery/*.md` que aún estén en inglés | 🔲 | pendiente (issue por crear) |

**Documentación de referencia:**

- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) § "Idioma de documentación"
- [`docs/plan-completo.md`](plan-completo.md) Fase 0, fila "Traducir documentación al español" (en `untracked`, se commitea junto con esta issue o por separado)

---

## 4. Issues abiertos (refresco 2026-07-03)

> Lista representativa — auto-actualizable con `gh issue list --state open`. Muestra abierta, priorizada por recencia + relación con roadmap, no exhaustiva. **Las cerradas están listadas al final de esta sección.**

> **Cerradas hoy (2026-07-05) — 3 issues P1/P0:**
>
> - **#141** `fix(acogidas) fecha_final` — PR #151 ([commit `4d4b3cd`](https://github.com/ardelperal/APAP_WEB/pull/151))
> - **#142** `feat(foster) override→estancia atomicity` — PR #155 ([commit `3672d33`](https://github.com/ardelperal/APAP_WEB/pull/155)) + PR #156 ([commit `27cab72`](https://github.com/ardelperal/APAP_WEB/pull/156)) + cherry-pick `28d04e9`
> - **#143** `fix(auth) revocación inefectiva` — PR #152 ([commit `6058a5a`](https://github.com/ardelperal/APAP_WEB/pull/152)); audit en [`docs/audits/auth-revalidation-2026-Q3.md`](audits/auth-revalidation-2026-Q3.md) — **PASS**

| # | Título | Área | Estado |
|---|---|---|---|
| #6 | feat(ux): definir la base UX/UI de APAP | Transversal UX/UI | 🔲 |
| #7 | feat(tasks): definir motor común de tareas manuales y automáticas | Transversal tasks | 🔲 |
| #40 | INTAKE-02: API batch de entradas con commit transaccional | Fase 5a | ✅ (commit `c7b69ec`, 2026-07-04) |
| #41 | INTAKE-03: workflow de cesión por propietario con contrato separado | Fase 5a | ✅ (PR #136, commit `98e80c5`, 2026-07-03) |
| #43 | FOSTER-01: CRUD de casas de acogida con preferencia de especie y capacidad | Fase 5b | ✅ (commit `25e749e`, 2026-07-04) |
| #44 | FOSTER-02: CRUD de estancias de acogida con FK a voluntario | Fase 5b | ✅ (commit `b7f197f`, 2026-07-04) |
| #45 | FOSTER-03: gate de especie + advisory de capacidad con override auditado | Fase 5b | ✅ (commits `3e51829`+`5d77cdb`, 2026-07-04) |
| #46 | FOSTER-04: asignación de material a estancias de acogida | Fase 5b | 🔲 |
| #47 | ADOPT-01: CRUD de adopciones con FK a voluntario | Fase 5c | ✅ (commits `62b9a46`+`4038a3a`, 2026-07-04) |
| #48 | ~~ADOPT-02: expiración de pre-adopción tras ventana de 20 días~~ **CANCELADO** por provenancia inválida — cláusula de 20 días = foster (`Plantilla.cls` L381-391), no pre-adopción. Ref `correct-preadoption-legacy-provenance`. | — | ❌ |
| #49 | ADOPT-03: state machine de seguimiento de 4 estados | Fase 5c | 🔲 |
| #50 | HEALTH-01: CRUD de actuaciones sanitarias con validación de fechas (D-24) | Fase 6a | ✅ (commit `0589076`, 2026-07-04) |
| #51 | HEALTH-02: API batch de actuaciones con commit transaccional | Fase 6a | 🔲 |
| #52 | HEALTH-03: API de resumen de salud (última por tipo de prueba) | Fase 6a | 🔲 |
| #53 | HEALTH-04: CRUD de terapias y recomendaciones | Fase 6b | 🔲 |
| #54 | HEALTH-05: motor de periodicidad para tareas pendientes de salud | Fase 6b | 🔲 |
| #55 | HEALTH-06: migración de catálogo de pruebas y reglas de periodicidad | Fase 6b | 🔲 |
| #56 | DOC-01: generación de PDF de contratos desde plantillas | Fase 7b | 🔲 |
| #57 | DOC-02: upload de contrato firmado con registro | Fase 7b | 🔲 |
| #58 | DOC-03: anexos de archivo con linking polimórfico por entidad | Fase 7a | 🔲 |
| #59 | DOC-04: migración de archivos legacy a object storage | Fase 7a | 🔲 |
| #60 | REPORT-01: query builder parametrizado con plantillas curadas | Reportes | 🔲 |
| #61 | REPORT-02: ejecución server-side con export PDF/Excel | Reportes | 🔲 |
| #62 | REPORT-03: informe trimestral PDF con charts | Reportes | 🔲 |
| #63 | REPORT-04: sistema de notificación de pruebas pendientes | Reportes | 🔲 |
| #64 | REPORT-05: API de contadores de dashboard en tiempo real | Reportes + home | 🔲 |
| #66 | RBAC-01: modelo RBAC con matriz de permisos a nivel API | Auth | 🔲 |
| #69 | LIFECYCLE-SCHEMA-03: cache materializado `estado_actual_animal` | Fase 4 | 🔲 |

**Issues cerradas relevantes (refresco 2026-07-04, con commit/título):**

- #50 (`0589076`) — HEALTH-01: CRUD de `actuacion_sanitaria` con validación de fecha D-24 (regla formalizada en `docs/decisiones-proyecto.md` §3 D-24: ISO formato + no futura + no anterior a `animales.fecha_alta` con exención NULL legacy). Tabla nueva `actuacion_sanitaria` (11 columnas, FKs a `animales`/`voluntarios`/`catalogos_pruebas` per CATALOG-01) cableada en `ensure_domain_schema`. CTE atómico para validación FK + D-24 regla 3 con disambiguation específica ("fecha es anterior al alta del animal (YYYY-MM-DD)" vs "animal inactivo" vs "voluntario inactivo" vs "tipo de prueba inexistente"). 25 atoms service en `tests/test_sanidad.py` + 14 atoms routes en `tests/test_sanidad_routes.py` + 7 atoms schema en `tests/test_domain.py` + 40 atoms template coverage en `tests/test_xss_audit.py`.
- #44 (`b7f197f`) — FOSTER-02: estancias de acogida con FK a `casas_acogida` (FOSTER-01, FK estructurada vía `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) y a `voluntarios` activos (active check per VOL-05); helpers `compute_duracion` (días entre fechas) e `is_active` (`activo AND fecha_final IS NULL`); `close_acogida` (evento de ciclo de vida: `fecha_final = current_date`) separado de `delete_acogida` (soft-delete real: `activo = false`, `fecha_baja = now()`); 8 endpoints con CSRF + auth; 38 atoms service en `tests/test_acogidas.py` + 23 atoms routes en `tests/test_acogidas_routes.py` (8 parametrizados en auth guard + 15 individuales) + 3 nuevos tests en `tests/test_domain.py` pinneando la migración ALTER TABLE.
- #43 (`25e749e`) — FOSTER-01: casas de acogida con capacidad y preferencia de especie (legacy `TbAcogidaCasas` 1:1 + 2 mejoras justificadas: `id` UUID y `capacidad INTEGER > 0`); soft-delete atómico via `UPDATE ... WHERE id = $1 AND activo = true RETURNING id`. 30 atoms service en `tests/test_foster.py` + 21 atoms routes en `tests/test_foster_routes.py` (7 parametrizados en el auth guard + 14 individuales).
- #40 (`c7b69ec`) — INTAKE-02: entradas en lote con staging y commit atómico (Entradas Múltiples / legacy `TbEntradasMultiplesAuxIniciales`); CTE atómico `INSERT FROM staging + DELETE staging` en una sola sentencia PostgreSQL.
- #1 (`dc98c1c` PR #24 — CD-02 Dockerfile/build), `b929233` HMAC, `225ef9c` job `deploy`, `ca06a46` httpx, `b16a5dd`/`e32c573` extract/PG-deselect; deploy verificado en CI run 28674612470.
- #14 (`69b509e`) — hoja de ruta viva (este doc)
- #16 (`1d22349`) — Fase 2 auth
- #17 (`d0b1ed1`) — Fase 1 esqueleto
- #25 — `authorized_users` tabla
- #26 — `animals`/`volunteers`/`volunteer_roles` tablas
- #87/#88/#89 — INTAKE-01 schema+service+routes (Fase 5a básica)
- #119 (`28a0cb1`) — tighten `auth_dependencies.py` types
- #120 (`4bc0df1` PR #137) — refactor de `read_session_payload`: soporta lectura de cookies firmadas por nombre explícito y mantiene el comportamiento por defecto de `apap_session`.
- #129 (`cfba764` PR #134) — alinea campos obligatorios de ficha de animal con Access y discovery; TDD en `tests/test_animals.py`.
- #130 (`7d7a364` PR #133) — consolida `docs/decisiones-proyecto.md` y marca referencias rotas del roadmap con plan de remediación.
- #124 — logout → login
- #125 — OAuth callback loop
- #126 — UI sin copy interno + campos obligatorios Access
- #127 — home con tarjetas de pendientes
- #128 — eliminar lenguaje interno
- #131 — labels castellanos
- #42 (cubierta por `1103b2e` PR #135 / #65) — origenes y motivos de entrada migrados como parte de los 5 catálogos legacy.
- #65 (`1103b2e` PR #135) — CATALOG-01: 5 catálogos migrados desde Access legacy (7 origenes, 21 motivos, 13 pruebas, 12 periodicidad, 8 tipos de contrato) con seed idempotente via `ON CONFLICT DO NOTHING` y verificación P1 vía Dysflow MCP. Bidireccional sigue en Fase 7.
- #141 (`4d4b3cd` merge commit, PR #151) — fix P0 silent-data-loss en `acogidas.fecha_final`: `fecha_final` añadido a `_WRITE_COLUMNS` (12 columnas), introducido `_UPDATE_PATCH_ONLY_COLUMNS = frozenset({'fecha_final'})` y `_build_update_sql_and_params` para que el UPDATE escriba `fecha_final` solo cuando la clave está presente en `params` (soporta `None` para reapertura y valor explícito para edición). Module docstring aclara los 3 ejes independientes (`fecha_final` via form, `close_acogida`, `delete_acogida`). TDD: 5 atoms service + 2 atoms routes. code-review-expert APPROVED (0 P0/P1, 1 P2 follow-up). Rebase sobre el hotfix `_LINK_OVERRIDE_SQL` (`27cab72`) preserva el filtro de #142 follow-up.
- #142 (`3672d33` merge commit, PR #155 + `27cab72` PR #156 + cherry-pick `28d04e9`) — fix P1 audit-log atomicity: `foster_capacity_overrides` ahora tiene FK estructurada `estancia_id` (idempotente vía ALTER TABLE ADD COLUMN IF NOT EXISTS, orden preservado en `ensure_domain_schema`); `create_acogida` enhebra `override_id` (llevado vía redirect URL + hidden form field) y hace `UPDATE foster_capacity_overrides SET estancia_id` cuando el `INSERT` de la estancia tiene éxito. `log_safe('foster.override.unlinked')` warning cuando el link falla (no rompe el create). judgment-day CRITICAL §1.2 (`override_id` cross-casa/animal forgery) cerrado por PR #156 con filtro `_LINK_OVERRIDE_SQL` añadido en `casa_acogida_id` y `animal_id`. cherry-pick `28d04e9` restaura el filtro casa+animal en `_LINK_OVERRIDE_SQL` que la resolución del rebase #151/#157 había revertido accidentalmente. TDD: 7 atoms en `test_foster_assignment.py` + `test_acogidas.py` + `test_domain.py`. judgment-day APPROVED ambos jueces (0 blocker, 0 critical, 1 suggestion).
- #143 (`6058a5a` merge commit, PR #152) — fix P1 `is_authorized`/`rol` congelados en la cookie de sesión hasta 7 días; ahora re-validados por request contra `usuarios_autorizados` con caché TTL en proceso (`Settings.auth_cache_ttl_seconds` = 300s = 5 min). Caché se invalida explícitamente en `add_authorized_user` (alta/re-alta) y `deactivate_authorized_user` (baja) por `email` (tomado del `RETURNING`, sin query extra). Cookie firma identidad (email + user_id); DB es la fuente de verdad de autorización. `require_authorized_user` ahora depende de `client` (regla 1 cero-SQL en routes preservada vía service `auth.get_user_by_email`). El middleware `protect_user_facing_routes` sigue sin tocar DB (primera puerta barata, default-deny). Audit completo en [`docs/audits/auth-revalidation-2026-Q3.md`](audits/auth-revalidation-2026-Q3.md) — **PASS**. PR #152 es el closure trail (5 atoms de tests + comment fix en `app/main.py` + audit extendida con commits de implementación y verdict de review-lens); la implementación efectiva vive en `0ff01db`..`aea9e22` (TT-3.1..TT-3.3 + invalidación + redaction + docstring fix). judgment-day APPROVED ambos jueces (0 blocker, 0 critical, 1 suggestion). TDD: 10 atoms `tests/test_auth_cache.py` + 7 atoms `tests/test_auth_dependencies.py` + 3 atoms `tests/test_auth.py`.
- (Y el commit `a528566 test(xss-audit): allowlist index.html shortcut.href` que pilló la regla 15.1 antes del merge de hoy)

---

## 5. Issues pendientes de crear (por fase)

> Refresco 2026-07-03: las issues de INTAKE (Fase 5a) ya están abiertas como #87-#89 + #41/#42. Las de FOSTER, ADOPT, HEALTH, DOC, REPORT, RBAC, CATALOG también están abiertas (ver §4). Lo que queda **sin abrir** está aquí abajo.

| Fase / Área | Título tentativo | Depende de | Estado |
|---|---|---|---|
| Fase 4 | `feat(animals): CRUD + timeline + estado derivado` (issue track por abrir) | Fase 3 | 🔲 pendiente abrir issue raíz (los #50-#55/#69 cubren pedazos) |
| Transversal | `feat(dashboard): bandeja de pendientes + realtime` (issue track por abrir) | Fase 2 | 🔲 pendiente (los #64 cubren la API) |
| Transversal | `feat(search): búsqueda global` | Fases 3-4 | 🔲 pendiente |
| Transversal | `feat(canonical-logs): traza canónica del sistema` | Fase 1 | 🔲 pendiente (ref `docs/canonical-logs.md` no existe; el doc hay que crearlo cuando arranque la issue) |
| Transversal | `feat(admin-panel): panel de control / configuración` | Fases 1-2 | 🔲 pendiente |
| Docs | `docs(architecture): traducir architecture-insforge-stack.md al castellano` | — | 🔲 pendiente |
| Docs | `docs(development): traducir development.md al castellano` | — | 🔲 pendiente |
| Docs | `docs(discovery): revisar y traducir los discovery en inglés al castellano` | — | 🔲 pendiente |
| Docs | `docs(canonical-logs): crear el doc fundacional de traza canónica` | — | 🔲 bloqueado por la issue de arriba |
| Docs | `docs(decisiones-proyecto): crear el doc de decisiones de proyecto` | — | ✅ creado en este refresh (2026-07-03) |
| Docs | `docs(proceso): playbook operativo por issue` | — | ✅ creado en este refresh (PR #132 merge `5329ec5`) |
| Docs | `docs(plan-completo): crear el plan detallado de Fases 0-7` | — | 🔲 sigue como borrador en `untracked` (referencia rota histórica); evaluar si se crea o se elimina del roadmap |
| Docs | `docs(mockups): restaurar mockups HTML referenciados` (login, dashboard, ficha animal) | — | 🔲 los mockups se referencian pero nunca se llegaron a commitear; crear cuando se necesiten |
| Fase 6b | `feat(therapies): terapias y recomendaciones` | Fases 3-4 |
| Fase 6c | `feat(material): inventario de material y asignaciones` | Fases 3-4 |
| Fase 7a | `feat(attachments): anexos e historial documental` | Fases 3-6 |
| Fase 7b | `feat(templates): motor de plantillas y contratos` | Fases 3-6 |
| Fase 7c | `feat(consultas): módulo Consultas + informe trimestral` | Fases 3-6 |
| Transversal | `feat(dashboard): bandeja de pendientes + realtime` | Fase 2 |
| Transversal | `feat(search): búsqueda global` | Fases 3-4 |
| Transversal | `feat(canonical-logs): traza canónica del sistema` | Fase 1 |
| Transversal | `feat(admin-panel): panel de control / configuración` | Fases 1-2 |
| Docs | `docs(architecture): traducir architecture-insforge-stack.md al castellano` | — |
| Docs | `docs(development): traducir development.md al castellano` | — |
| Docs | `docs(discovery): revisar y traducir los discovery en inglés al castellano` | — |

---

## 6. Índice de documentación de referencia

### Producto y dominio

- [`docs/discovery/README.md`](discovery/README.md) — índice maestro del discovery
- [`docs/discovery/business-feature-map.md`](discovery/business-feature-map.md) — visión general y orden de generación
- [`docs/discovery/feature-01-animal-lifecycle.md`](discovery/feature-01-animal-lifecycle.md)
- [`docs/discovery/feature-02-intake-foster-adoption.md`](discovery/feature-02-intake-foster-adoption.md)
- [`docs/discovery/feature-03-health-care.md`](discovery/feature-03-health-care.md)
- [`docs/discovery/feature-04-documents-contracts-reports.md`](discovery/feature-04-documents-contracts-reports.md)
- [`docs/discovery/state-machines.md`](discovery/state-machines.md)
- [`docs/discovery/data-model-notes.md`](discovery/data-model-notes.md)
- [`docs/discovery/data-model-completeness.md`](discovery/data-model-completeness.md)
- [`docs/discovery/migration-risks.md`](discovery/migration-risks.md)
- [`docs/discovery/open-decisions.md`](discovery/open-decisions.md)
- [`docs/discovery/acceptance-checklist.md`](discovery/acceptance-checklist.md)
- [`docs/discovery/inventory-baseline.md`](discovery/inventory-baseline.md)
- [`docs/discovery/dysflow-notes.md`](discovery/dysflow-notes.md)
- [`docs/decisiones-proyecto.md`](decisiones-proyecto.md) — registro canónico de decisiones de producto (D-01–D-07), UX (D-10–D-12), arquitectura (D-20–D-21), proceso (D-30–D-38) y UAT (D-40–D-41). Creado 2026-07-03 con el refresh de #130.

### Arquitectura, plan y desarrollo

- [`docs/architecture-insforge-stack.md`](architecture-insforge-stack.md) — stack base y reglas InsForge/Coolify *(pendiente de traducir al castellano)*
- [`docs/plan-completo.md`](plan-completo.md) — *(referencia rota: no commiteado)* plan detallado de Fases 0-7. Estaba en `untracked` y nunca se llegó a commitear; ver §5 para el plan de creación.
- [`docs/development.md`](development.md) — flujo local de desarrollo *(pendiente de traducir al castellano)*
- [`docs/proceso.md`](proceso.md) — playbook operativo por issue: premisas (P1 fidelidad al legacy, P2 resolución de dudas, P3 docs reflejan código, P4 pre-MVP single-branch) + workflow completo (pre-flight → triaje → SDD/TDD → validación → merge → cierre con trazabilidad). **Leer al iniciar cualquier issue que vaya más allá de un doc trivial.**
- [`docs/setup.md`](setup.md) — setup por desarrollador y credenciales InsForge
- [`docs/audits/auth-revalidation-2026-Q3.md`](audits/auth-revalidation-2026-Q3.md) — auditoría de re-validación de `is_authorized`/`rol` por request (issue #143, **PASS** — autorización ahora revocable en ≤ `auth_cache_ttl_seconds` = 300s en lugar de hasta 7 días)

### UX y visual

- [`docs/design-tokens-apap-actual.md`](design-tokens-apap-actual.md) — tokens heredados del legacy como referencia
- [`docs/mockups/login-simple-insforge.html`](mockups/login-simple-insforge.html) — *(referencia rota: nunca commiteado)* mockup del login
- [`docs/mockups/login-dashboard.html`](mockups/login-dashboard.html) — *(referencia rota: nunca commiteado)* mockup del dashboard interno
- [`docs/mockups/ficha-animal-timeline.html`](mockups/ficha-animal-timeline.html) — *(referencia rota: nunca commiteado)* mockup de la ficha del animal
- [`docs/features-showcase.html`](features-showcase.html) — escaparate interactivo de features

> **Nota 2026-07-03:** los tres `mockups/*.html` se referencian históricamente pero nunca se llegaron a commitear. Estaban en el plan de #6 (UX/UI foundation) y en las features iniciales; ahora son bloqueados por #6 hasta que arranque esa issue.

### Legacy — análisis detallado (no clonar UX)

- [`docs/legacy-health-ui-workflow.md`](legacy-health-ui-workflow.md)
- [`docs/legacy-initial-dashboard.md`](legacy-initial-dashboard.md)
- [`docs/legacy-signed-contract-flow.md`](legacy-signed-contract-flow.md)
- [`docs/legacy-volunteer-roles.md`](legacy-volunteer-roles.md)
- [`docs/legacy-lifecycle-transition-rules.md`](legacy-lifecycle-transition-rules.md)

### Trazas y diagnóstico

- [`docs/canonical-logs.md`](canonical-logs.md) — *(referencia rota: nunca commiteado)* formato y contrato de la traza canónica. Crear cuando arranque la issue `feat(canonical-logs)`.

### SDD (OpenSpec)

- [`openspec/config.yaml`](../../openspec/config.yaml) — configuración del motor SDD
- [`openspec/changes/ci-cd-foundation/`](../../openspec/changes/ci-cd-foundation/) — change actual (CI/CD)
- [`openspec/specs/migration-discovery-docs/spec.md`](../../openspec/specs/migration-discovery-docs/spec.md) — spec archivado de la discovery

---

## 7. Cuándo ir al legacy directamente

**Reglas de uso de la documentación generada vs. el Access:**

1. **Si `docs/discovery/feature-XX-*.md` cubre la pregunta → leer el discovery primero.** Es la versión revisada y consolidada.
2. **Si el discovery no entra en detalle suficiente y existe un `docs/legacy-*.md` específico para el área → leer el legacy documentado.** Ejemplo: `docs/legacy-health-ui-workflow.md` para la pestaña Salud.
3. **Solo ir al Access directamente (vía Dysflow) si**:
   - La pregunta no está cubierta en discovery ni en legacy-*.
   - Hay que validar un dato concreto del schema o de los datos que no se puede inferir de la documentación.
   - Aparece un dato incoherente que requiere inspección de los formularios VBA (`Form_*`).
4. **Cualquier descubrimiento nuevo del Access debe documentarse** como `docs/legacy-<área>.md` antes de cerrar la tarea, no como nota efímera.

**Herramienta canónica para tocar el Access en este proyecto:** Dysflow MCP (`projectId: apap`). El skill `vba-access` es el único skill VBA permitido; los skills `access-vba-sync`, `access-query`, `access-form-creation` y `access-sandbox` están excluidos del workflow de APAP_WEB.

---

## 8. Convenciones del proyecto

| Tema | Convención |
|---|---|
| Idioma de issues y PRs | Castellano (España) |
| Idioma de artefactos técnicos (código, comentarios, docstrings) | Inglés por defecto; documentación de producto en castellano |
| Idioma de documentación | Castellano (España) para docs de producto, arquitectura y SDD |
| Mantenedor | aroman (autoaprueba issues y PRs) |
| Rama objetivo actual | **pre-MVP single-branch** — todo va a `main`, una sola rama al final del ciclo. `git config gentleai.stagingOnly` está **unset** para este repo (D-38, `AGENTS.md` §15). Reversión post-MVP: re-armar el flag, recrear `staging`, deferir al global `staging-acceptance-contract` con Virginia como validadora UAT. |
| Convención de commits | Conventional Commits |
| Tipo de PR label | exactamente uno de `type:bug` / `type:feature` / `type:docs` / `type:refactor` / `type:chore` / `type:breaking-change` |
| TDD | Estricto: tests antes de código (excepto docs y ops puros). Cada unidad de trabajo = 1 issue → tests rojo → implementación → verde → integración en `main` → cerrar issue con trazabilidad (SHA + test path) |
| Skill para frontend | `frontend-design` cargado en cualquier issue que toque UI/UX |
| Skill para workflow VBA/Access | Solo `dysflow` MCP, `vba-access` y `access-vba-tdd`; los demás skills de Access están excluidos (D-31) |
| Presupuesto de revisión | 400 líneas por PR; usar PRs encadenados cuando se supere |
| Cadena de PRs | `force-chained`; base normal `main` (pre-MVP); post-MVP vuelve a `staging` |
| Trazabilidad de SDD | Cada PR enlaza la issue (`Closes #N`) y referencia el change de OpenSpec cuando aplique |
| Fidelidad al legacy | D-05 (P1): superset funcional del Access; gap = `type:bug` con label `gap:legacy` |

---

## 9. Cómo mantener este documento

**Regla base:** este roadmap se mantiene actualizado como efecto directo de cualquier acción que afecte a su contenido. No es una tarea aparte, se hace en el mismo flujo. Las decisiones, la documentación, las issues y el roadmap viven sincronizados: si algo cambia, el roadmap cambia en esa misma sesión, sin esperar a que el usuario lo pida.

**Ritmo de trabajo actual:** abrir issue → escribir el test rojo (TDD estricto) → implementación mínima que lo pone en verde → integrar en `main` → cerrar issue con trazabilidad (SHA + test path). En pre-MVP no hay promoción separada; todo va directo a `main`. Post-MVP, la cadencia vuelve a ser staging → UAT con Virginia → main.

Acciones que obligan a actualizar el roadmap en la misma sesión:

- **Apertura de una issue**: añadir fila a §4 "Issues abiertos", retirar de §5 "Issues pendientes de crear" (si estaba), enlazar desde la fase correspondiente en §3 y abrir una PR de docs en el mismo flujo.
- **Cierre de una issue**: eliminar la fila de §4, reflejar el cambio en §2 "Estado actual" si toca algo visible allí y actualizar la fase correspondiente en §3.
- **Cambio de estado de una fase** (🔲 → 🟡 → ✅): actualizar §3 y la fecha de "Última actualización".
- **Nueva documentación**: añadir a §6 en el mismo PR.
- **Nueva decisión de arquitectura o proceso**: añadir a `docs/decisiones-proyecto.md`; el roadmap debe enlazarla, no duplicarla.
- **Cierre de una fase completa**: marcar ✅ la fila en §3, mantener el enlace al histórico (no borrar) y proponer la siguiente fase.
- **Obsolescencia detectada**: si el doc se desactualiza respecto a `main`, abrir `docs(roadmap): refrescar hoja de ruta` y ejecutar el refresco en la misma sesión.
- **Auditoría de enlaces de §6**: en cada refresh, verificar que cada `path/to/doc.md` referenciado existe realmente. Si no existe, marcar como **referencia rota** en la fila (§6 actual 2026-07-03) y/o crear el doc correspondiente en la misma PR. El checklist concreto se hace con:

  ```bash
  # Detecta referencias rotas en docs/roadmap.md
  grep -oE '\[.*\]\(([^)]+\.(md|html|yaml))' docs/roadmap.md \
    | sed -E 's/.*\(([^)]+)\)/\1/' \
    | sort -u \
    | while read p; do test -e "$p" || echo "ROTA: $p"; done
  ```

  Las referencias marcadas como **ROTA** en el refresh 2026-07-03 son: `docs/plan-completo.md`, `docs/canonical-logs.md`, `docs/mockups/login-simple-insforge.html`, `docs/mockups/login-dashboard.html`, `docs/mockups/ficha-animal-timeline.html`. Plan de remediación documentado en §5.