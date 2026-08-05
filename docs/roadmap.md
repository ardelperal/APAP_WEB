# Hoja de Ruta Viva — APAP_WEB

> Documento vivo. Punto de entrada único para saber qué hay que construir, en qué orden, qué issues lo cubren y qué documentación ya existe. Si una pregunta se responde aquí, no hay que rebuscar.

**Última actualización:** 2026-08-05 — refresco post-refactor hexagonal. **El GATE del SDD que anunciaban el header y §4 está RESUELTO y era falso desde el 2026-07-31**: `openspec/changes/legacy-discovery-interrogatorio` SÍ existe en disco y está trackeado en git (commit `12f6fb3`, «docs(sdd): consolidate legacy-discovery-interrogatorio — closes #343 Path A»), un día después del refresco anterior. Los 22 features con `status:approved` NO están bloqueados por eso. Novedad estructural de esta ventana: **la arquitectura pasó a hexagonal por vertical slices** — seis slices en `main` (#414 auth-users, #415 catalogos, #416 schema-bootstrap, #417 migration-web, #419 admin, #418 oauth), la regla de ubicación codificada en `AGENTS.md` §33 (PR #421) y el índice vivo en la épica #420. También: #422 cierra la mitad `migration/` del triaje S608 (#387), y 16 issues del backlog se adaptaron al contrato hexagonal para que su implementación futura no tenga ambigüedad. Ver §2.bis.
**Mantenedor único:** aroman (autoaprueba issues y PRs)
**Rama objetivo actual:** **pre-MVP single-branch** — todo va a `main`, una sola rama al final del ciclo (ver §8 y `AGENTS.md` §15)
**Idioma de toda la documentación, issues y PRs:** castellano (España)

---

## 1. TL;DR

- **CI/CD foundation (Fase 0):** CI-01, CI-02, CD-01 y CD-02 están **todos en verde en `main`** desde el 2026-07-03. El deploy automático al push a `main` se ejecuta vía webhook firmado a Coolify (`COOLIFY_WEBHOOK_URL` + `COOLIFY_WEBHOOK_SECRET` configurados; verificado en CI run 28674612470). El primer deploy real sigue pendiente del DNS `apap.romancaba.com` (operación manual del mantenedor).
- **Infraestructura:** repositorio, Coolify y backend de InsForge ya aprovisionados. Runnable de la aplicación en producción pendiente solo del DNS.
- **Producto (Fases 1-7):** **Fase 1 ✅ mergeada en `main` (#17, commit `d0b1ed1`)**. **Fase 2 ✅ mergeada en `main` (#16, commit `1d22349`)**. **Fase 5a INTAKE cerrada**: INTAKE-01 ✅ (#87/#88/#89), INTAKE-02 ✅ (#40, commit `c7b69ec`), INTAKE-03 ✅ (#41, PR #136, commit `98e80c5`). **Fase 5b FOSTER**: FOSTER-01 ✅ (#43, commit `25e749e`) con entidad propia `casas_acogida` + `capacidad` (legacy `TbAcogidaCasas` 1:1 + 2 mejoras justificadas: `id` UUID y `capacidad INTEGER > 0`). FOSTER-02 ✅ (#44, commit `b7f197f`) con CRUD de estancias referenciando `casas_acogida` (FK estructurada vía `ALTER TABLE ADD COLUMN IF NOT EXISTS`) y `voluntarios` activos (active check per VOL-05); helpers públicos `compute_duracion` e `is_active`; `close_acogida` vs `delete_acogida` separados semánticamente (D-EST-04). FOSTER-03 ✅ (#45, commits `3e51829`+`5d77cdb`, 2026-07-04) con species gate hard + capacity advisory auditado (nuevo módulo `app/modules/foster/assignment.py` con `evaluate_assignment` y `record_override`; cierre de OD-3a y D-18); FOSTER-04 ✅ (#46, cerrada 2026-07-05 vía PR #166 (PR A schema + service skeleton, merge `1660d9f`) + PR #170 (PR B catalog CRUD, merge `92b75aa`) + PR #171 (PR C junction routes + detail integration, merge `5017902`); runbook fix PR #172 (merge `57362e7`) tras el cierre) ADOPT-01 ✅ (#47, commits `62b9a46`+`4038a3a`, 2026-07-04) con CRUD de adopciones referenciando `voluntarios` activos (FK estructurada per VOL-05) + `donativo_adopcion` numeric + `tipo_adopcion` regular/preadopcion/judicial; ADOPT-03 🔲 (#49). Fases 3-7 pendientes. El código de auth está listo; tabla `authorized_users` creada y seedeada (#25).
- **Issues UI/copy recientes (cerradas):** #124 logout → login, #125 OAuth callback loop, #126 UI sin copy interno + campos obligatorios Access, #127 home con tarjetas, #128 eliminar lenguaje interno, #131 labels castellanos. XSS allowlist detectado y fixado en `a528566`.
- **P1/P0 security follow-ups cerrados hoy (2026-07-05):** #141 `fix(acogidas) fecha_final` silent-data-loss (PR #151, commit `4d4b3cd`); #142 `feat(foster) override→estancia atomicity` (PR #155 commit `3672d33` + PR #156 commit `27cab72` + cherry-pick `28d04e9`); #143 `fix(auth) revocación inefectiva` con re-validación per-request vía caché TTL (`auth_cache_ttl_seconds` = 300s) + invalidación explícita al dar de baja (PR #152, commit `6058a5a`; audit en [`docs/audits/auth-revalidation-2026-Q3.md`](audits/auth-revalidation-2026-Q3.md) — **PASS**).
- **Refactor de `app/main.py` cerrado hoy (2026-07-24):** #204 `refactor(app): extraer middleware de auth y registro de rutas de app/main.py` (PR #271, merge `2f93a95`): install_auth_middleware a `app/core/middleware.py` (197L) + register_routers a `app/routes_registry.py` (62L) + main.py 689→544 líneas (~21% reducción); audit PASS en [`docs/audits/issue-204-middleware-extraction-audit-2026-Q3.md`](audits/issue-204-middleware-extraction-audit-2026-Q3.md); `size:exception` pre-MVP autorizado; cobertura 89.18% (sobre floor 80%), `CRITICAL_HELPERS` 21/21 @100% PASS; CI run `29953269866` `conclusion=success` (lint + test + build); 4R review (`review-97d8a8b3ffb21f14`) con 6 follow-ups WARNING-tier documentados (ver §4 «Follow-ups from PR #271»).
- **Audit anti-pattern + hardening cerrado (2026-07-25 → 2026-07-27):** 22 cierres del catch-up batch derivado del audit full-codebase #294 (label `audit-2026-07-25`), distribuidos en cinco frentes. **Perímetro de seguridad:** #276 middleware de security headers (CSP/X-Frame-Options/HSTS/nosniff/Referrer-Policy) + #286 SlowAPI rate limit OAuth+write. **Ciclo de auth hardened:** #275 startup fail-fast de `APAP_SESSION_SECRET`, #277/#278 email normalization + dup-key stability, #279 last-developer lockout, #280 `invalidate_all()` preserva generaciones, #287 Redis seam removido. **Logging hygiene:** #283 envelope anidado de `_caller_fields` + #284 `JsonFormatter` allow-list estricto. **Operational gates:** #210 check-rules repo-root, #281 deploy step live, #282 Postgres para TOCTOU, #288 coverage por-capa, #290 Detector 13 query-builder, #291/#293 §32 anti-patterns codified (P1-P8), #292 pytester isolation, #289 domain.py split, #285 streaming+Etag+private cache para `animal_foto`. **Epic:** #294 cierra el audit y deja el checklist vivo en [`docs/audits/2026-07-25-audit-checklist.md`](audits/2026-07-25-audit-checklist.md). Más dos catch-ups de refresh anteriores: #216 rename `dysflow_client.py → legacy_access_client.py` (PR #297 `b87a0f9`, 2026-07-25) y #210 `fix(make) check-rules` (PR #270 `43f86c2`, 2026-07-22, que tampoco entró en el refresco 2026-07-22 del roadmap). Entries detalladas con PR + SHA + audit ref en §4.
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

## 2.bis Arquitectura: refactor hexagonal por vertical slices (2026-08-05)

> **Si vas a escribir código nuevo, esta sección manda sobre los ejemplos de §3 y §4.**
> Fuentes autoritativas: **`AGENTS.md` §33** (la regla, enforceable en review) y la
> **épica #420** (índice vivo de slices, orden de ejecución y definition of done).
> Este bloque es el resumen; si discrepan, gana `AGENTS.md`.

### Qué cambió

La arquitectura dejó de ser «FastAPI + service layer» y pasó a **hexagonal con vertical
slices**. El detonante: `app/core/*.py` importaba `InsForgeClient` directamente, así que
el backend no era sustituible y la lógica no era testeable sin transporte.

### Slices en `main`

| Slice | PR | Qué encapsula |
|---|---|---|
| auth-users | #414 | `usuarios_autorizados` — plantilla del patrón para el resto |
| catalogos | #415 | Tablas de catálogo (`list_periodicidad`, `list_tipos_contrato`, …) |
| schema-bootstrap | #416 | `ensure_domain_schema` + `run_idempotent_sql` |
| migration-web | #417 | Lado lectura de migración web (`WebReaderPort`) |
| admin | #419 | Rutas admin → casos de uso + `AdminTemplateAdapter` |
| auth-flow / oauth | #418 | Flujo OAuth completo (PKCE, sesión, 4 casos de uso) |

### Dónde va cada cosa (regla corta; la larga está en `AGENTS.md` §33.2)

- **`app/core/<capa>/<slice>/`** — transversal: lo consumen **2+ slices** *y* no tiene
  razón de negocio propia para cambiar. Las dos mitades son obligatorias.
- **`app/modules/<slice>/`** — capacidad de negocio; el slice entero en una carpeta:
  `domain/`, `ports/`, `application/` (un caso de uso por fichero),
  `adapters/insforge/` (con su `<slice>_insforge_queries.py`, regla §22),
  `di/`, y un `routes.py` fino.
- **Ante la duda, módulo.** Promover a `core` después es barato; sacarlo de `core` con
  cinco consumidores colgando, no.

Invariantes: `InsForgeClient`/`InsForgeError` solo bajo `adapters/` y `di/` (más
`app/main.py`, que construye el cliente); ningún `service.py` nuevo que ejecute SQL;
ningún criterio de aceptación que nombre al proveedor; un test de pin arquitectónico por
slice que falle si un import de transporte se cuela de capa.

**Deuda registrada:** `admin` está en `core` sin cumplir la regla (un solo consumidor).
Es una excepción deliberada documentada en `AGENTS.md` §33.5 y en #420 — **no sirve de
precedente** para meter la siguiente capacidad de negocio en `core`.

### Lo que falta

1. `auth-dependencies` — `app/core/auth_dependencies.py`, último seam de auth en core.
2. **Slices de módulo** — 22 ficheros en 11 módulos (`acogidas`, `adopciones`, `animals`,
   `cesiones`, `entradas`, `foster`, `materiales`, `salud`, `sanidad`, `tasks`,
   `voluntarios`). Independientes entre sí → PRs encadenables.
3. Cola de migración/infra — `migration/{apply,bootstrap,cli,cli_apply_reverse}.py`,
   `app/core/migration/sql_runner.py`, `app/core/tasks/scheduler.py`.

Medición de progreso (un solo comando):

```bash
git grep -n "^\s*from app.core.insforge import" -- 'app/**.py' 'migration/**.py' | wc -l
```

Legítimos son los `app/core/di/*_di.py` y `app/main.py`; el resto es backlog.

### Backlog ya alineado

16 issues anteriores al refactor se adaptaron el 2026-08-05 para que su implementación
futura no sea ambigua: #33, #54, #56–#64 llevan un bloque «Contrato de arquitectura»;
#341, #387, #390, #392 y #395 llevan nota de coordinación porque tocan ficheros que el
refactor reubica.

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

> 🟡 **En curso (Fase 5a INTAKE cerrada, Fase 5b FOSTER y Fase 5c ADOPT en curso)**: INTAKE-01 cerrado (schema + service + routes — #87, #88, #89, mergeadas 2026-06-28). INTAKE-02 cerrado (#40, commit `c7b69ec`, 2026-07-04) con staging + commit atómico. INTAKE-03 cerrado (#41, schema + service + routes + form, mergeada 2026-07-03 vía PR #136, commit `98e80c5`). INTAKE-04 (#42) quedó cubierto por CATALOG-01 (#65, PR #135). **FOSTER-01 cerrado** (#43, commit `25e749e`, 2026-07-04) con entidad propia `casas_acogida` + `capacidad` (legacy `TbAcogidaCasas` 1:1 + 2 mejoras justificadas: `id` UUID y `capacidad INTEGER > 0`). **FOSTER-02 cerrado** (#44, commit `b7f197f`, 2026-07-04) con CRUD de estancias de acogida que referencian `casas_acogida` (FK estructurada vía `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) y `voluntarios` activos (active check per VOL-05); helpers públicos `compute_duracion` (días entre fechas, `None` si abierta) e `is_active` (`activo AND fecha_final IS NULL`); separación semántica `close_acogida` (evento de ciclo de vida: `fecha_final = current_date`, `activo` se mantiene `true`) vs `delete_acogida` (soft-delete real: `activo = false`, `fecha_baja = now()`); 8 endpoints con CSRF + auth; tests TDD (38 service + 23 routes + 3 nuevos domain + 3 nuevos XSS). **FOSTER-03 cerrado** (#45, commits `3e51829`+`5d77cdb`, 2026-07-04) con species gate hard (cierre OD-3a) + capacity advisory auditado (cierre D-18); nuevo módulo `app/modules/foster/assignment.py` con `evaluate_assignment` (`AssignmentDecision` Literal admit/block/admit_with_warning) y `record_override` (audit log + `log_safe`); tabla propia `foster_capacity_overrides` (id, casa_acogida_id, animal_id, operador_user_id, motivo, created_at) vía `CREATE TABLE IF NOT EXISTS`; nuevo sub-router `/casas-acogida/{id}/asignar` y `/casas-acogida/{id}/overrides`; P0 species-gate bypass en `POST /acogidas` cerrado vía `_enforce_species_gate`; overrides restringidos a `developer` rol vía `require_developer_user`. FOSTER-04 ✅ (#46, cerrada 2026-07-05) — schema + service skeleton en PR #166 (`feat/material-schema-and-service`, merge `1660d9f`), catalog CRUD routes + templates en PR #170 (`feat/material-catalog-routes`, merge `92b75aa`), junction routes + per-estancia detail integration en PR #171 (`feat/material-junction-routes`, merge `5017902`); runbook cross-ref corregido en PR #172 (`fix/domain-runbook-ref-2026-07-05`). Slice completa: tabla `materiales` + junction `estancia_materiales` (legacy 1:1, id UUID + `capacidad INTEGER > 0` heredado de FOSTER-01), CRUD material, asignación por estancia, listado por estancia, RBAC writer/reader, CSRF en cada POST, XSS audit fixture extendido para los nuevos templates. **ADOPT-01 cerrado** (#47, commits `62b9a46`+`4038a3a`, 2026-07-04) con CRUD de adopciones referenciando `voluntarios` activos (FK estructurada per VOL-05); `donativo_adopcion` numeric (rechazo explícito de bool) + `tipo_adopcion` `regular`/`preadopcion`/`judicial` vía ALTER TABLE idempotente (D-EST-05); CTE atómico create/update (TOCTOU fix); `search_adopciones_by_adoptante` con ILIKE case-insensitive y `ESCAPE '\\'`; soft-delete atómico `UPDATE ... WHERE id = $1 AND activo = true RETURNING id` (D-ADOPT-03); 7 endpoints con CSRF + auth; tests TDD (29 service + 20 routes) más 16 tests de remediación post-review (CTE-shape, 403 reader→writer, FK disambiguation, wildcard escaping, 100-row cap). ADOPT-03 (#49) sigue 🔲.

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

**Objetivo:** disponer de un backend privado (InsForge) poblado con los datos y las fotos reales del Access legacy, en una sola dirección controlada y verificable, antes de abrir Fases 4-7 a datos productivos. Precedencia operativa: PR7 → E2E Playwright canónico CI → unidades de trabajo de operador (Phase 4 de `tasks.md`) solo con los gates de código en verde. PR5 está cerrado (2026-07-18, PR #196 / merge `024dc973`) y PR6 está cerrado (2026-07-18, PR #213 / merge `2782cb6`); el milestone M1 forward usable queda completo a nivel de código (animales, voluntarios, entradas y fotos migradas vía `apply_legacy_to_web`) y de controles PII/PR-A, y el round-trip M2 (PR6) ya prueba ida+y+vuelta con `apply_web_to_legacy` + 5 átomos de round-trip + reverse-path collision routing, pero **sigue sin ser fallback-ready** — el gate `verify-fallback-ready` (PR7) es el siguiente paso obligatorio antes de cualquier decisión de retirar el Access legacy como fuente operativa. La prioridad inmediata es un backend privado usable (datos y fotos reales del legacy), no un reemplazo del Access como fuente.

> 🟡 **En curso (PR1/M0 runtime boundary cerrado, PR2/M0 ShadowStateRepository + bucket privado cerrado, PR3/M1 core apply safety cerrado, PR4a/M1.storage-contract cerrado, PR4b/M1.storage-implementation cerrado, PR5/M1 PII controls + reconcile + discovery cerrado, PR6/M2 reverse-apply + round-trip cerrado; PR7/verify-fallback-ready es el siguiente paso).** PR4b, cerrado por issue #191 / PR #192 / merge `80020105c4b23f25311f405dd0427c0de308f8a1`, entrega `InsForgeClient.upload_object`/`download_object_stream`/`delete_object`, la ruta autenticada `GET /animales/{animal_id}/foto` y el seam tipado `PhotoStreamError`, con fail-closed ante fallos de storage iniciales, mid-stream y de lookup SQL. Mantiene `apap-photos` privado, nunca expone la URL presignada y amplía `REDACTED_FIELDS` de 12 a 15 con `dni`/`tel1`/`tel2`; la auditoría [`docs/audits/pii-live-migration-2026-Q3.md`](audits/pii-live-migration-2026-Q3.md) tiene veredicto **PASS**. La remediación 4R cerró en **PASS** con los commits `688653e`+`9821bd7`+`4717a4b`+`cde7c03`+`df28fc1`+`40b5285`+`1fc58f8`; CI run `29202180163` terminó `conclusion=success`. PR5 cerró 2026-07-18 por PR #196 / squash merge `024dc97307a745834f103be4ea27687c4381f93e` (10 commits de unidad de trabajo + dysflow-config delegate) los controles PII (10 átomos en `tests/migration/test_pii_redaction.py` + 9 átomos en `tests/migration/test_dni_collision.py` + 10 átomos en `tests/test_public_paths.py`), el flag CLI `--filter-direction {legacy-to-web, web-to-legacy, both}` con default `both` para compatibilidad PR4 callers, los helpers `_is_pii_web_column` + `_mask_pii_value` (closed-list vs `REDACTED_FIELDS`) + `_looks_like_pii(value)` (DNI/email/phone regex) para enmascarar `legacy_pk`/`web_pk`, y la actualización de `docs/discovery/migration-risks.md` con §"Source snapshot identity" + §"Collision policy (corrected)" (3 PII legacy-mapped + 1 web-only `voluntarios.dni` verificada vía Dysflow `get_schema`). PR6 cerró 2026-07-18 por PR #213 / merge `2782cb6e66a595de4dfbeff33d84e481f2522a3f` el path simétrico M2 (`migration/apply_reverse.py::apply_web_to_legacy` con sync-state snapshot transactional pre-apply + diff por tabla en memoria + per-row INSERT/UPDATE con `log_safe("sync.applied")` audit + emisión `LIFECYCLE_REVERSED` con `source_direction="web-to-legacy"` + reverse-path collision routing vía `record_dni_collision` + `preserve` columns bump `web_only_feature_shadow.last_legacy_snapshot_at` sin escribir `preserved_value`); 9 átomos en `tests/migration/test_reverse_apply.py` (incl. `test_apply_web_to_legacy_inserts` / `_updates` / `_dry_run_does_not_write` / `_dry_run_reports_zero` / `test_preserve_column_not_written_to_legacy` / `test_derived_column_no_rederive_on_reverse` / `test_lifecycle_reversed_event_emitted` / `test_sync_state_updated_transactionally` / `test_sync_state_rollback_on_legacy_write_failure`) + 5 átomos en `tests/migration/test_round_trip.py` (`test_round_trip_100_animals_preserves_nchip` / `_100_voluntarios_preserves_dni` / `_with_3_edits_applies_3_updates` / `_detects_unsynced_edits_as_needs_review` / `_counts_preserved`); lens-fix commits `52c328a` (F1 logger alias `logging_mod.log_safe` + F2 sync-state snapshot post-lock) + `e69aa2b` (F3–F8 review findings: per-row keyword-only signature, sync_state_path override, dry-run zero reporting, dry-run no-shadow-write, legacy_write executor DI seam, atomic lock-context rollback); module-size ratchet R1 (`migration/apply.py` -3L via revert direction kwarg plumbing) + R2 (`migration/cli.py` 1226→933 + nuevo `migration/cli_apply_reverse.py` 370L) + R3 (`migration/apply_reverse.py` 1165→86 shim + nuevo package `migration/reverse_apply/` con 7 sub-módulos: `__init__.py` 50L / `orchestrator.py` 306L / `per_row.py` 246L / `shadow.py` 132L / `lifecycle.py` 103L / `lock_context.py` 179L / `io_helpers.py` 96L / `types.py` 72L; total `BASELINE` `cli.py` mejora 1071→933 ratcheted shrink-only); audit [`docs/audits/pii-live-migration-2026-Q3.md`](audits/pii-live-migration-2026-Q3.md) sección "## PR6 Additions (2026-07-18, reverse apply + round-trip)" Verdict **PASS** (PII redaction discipline / authorization / 15-field list unchanged); runbook [`docs/runbooks/live-migration-apply.md`](runbooks/live-migration-apply.md) sección "Reverse direction (PR6 / M2)" con los 5 headings AGENTS §13; full migration suite 261 passed (preserved), full local gate 2413 passed + 2 skipped + 0 warnings; CI run `29661279842` `conclusion=success` (lint + test + build PASS, GitGuardian PASS; e2e/deploy SKIPPED — esperado pre-MVP); validation gate `gentle-ai review validate` invalidated, se cae a CI verde por directiva pre-MVP "no reviewers in pipeline"; rama `feat/live-migration-reverse-apply` borrada en local y en origin per AGENTS §15.2. PR4a (`migration/storage_spike.py` con `ReadOnlyProbeHttpClient` typed boundary `MutationRefusedError` antes de transport, `probe_download_strategy` con `httpx.MockTransport`, `build_pinned_operator_evidence_result()` con sha256 `62f025e2df0d4fe92e61baa7cf001f34cb3eccdf525564d9ca13bc636bfdac07`, `write_discovery_document()` renderea `docs/discovery/storage-contract-2026-Q3.md`; `tests/migration/test_photo_storage.py` 12 atoms + `tests/migration/test_storage_contract_evidence.py` 4 strict-TDD contract-pin atoms + `tests/test_repository_secrets_ignore.py` 8 atoms de W1 narrow `.gitignore`; root `.gitignore` narrow `/.env`, `/coverage.json`, `/coverage_full.json` con `.codegraph/` NO ignorado per AGENTS §14.4; `openspec/changes/live-data-migration-sandbox/tasks.md` PR4a `4.1/4.2/4.3/4.3a/4.3b` marcados completos) mergeado como PR #188 / merge commit `24ff0325` (Closes #187) el 2026-07-12. CI run `29197668830` en `824c036` `conclusion=success`; native 4R PASS (0 BLOCKER / 0 CRITICAL / 0 WARNING / 1 INFO B4 — credential echo hardening en CLI, mitigado por `test_cli_loads_credentials_from_settings_loader_without_echoing_secrets`); single CI-routed correction transaction `824c036` (swap `git status --ignored` → `_check_ignored` en los 2 atoms de working-tree-state, bounded test-only). El operator-supplied reversible sentinel cleanup mantuvo el bucket privado `apap-photos` con `object_count=0/total=0` (sentinel `__missing__` creado y borrado dentro del ciclo); **no se subieron fotos reales en el spike** (PR4a es un gate de código contra el contrato pinned, no una carga de datos). PR3 (`migration.lock_snapshot.atomic_write` + drift + `partial_apply` + `migration.apply.core` reorder per D8 + `migration.lock.check_msaccess_running` fail-closed + `migration.reporting.counts/source_hashes/collisions` backward-compat + `migration.cli` exit-code contract 5/6/7 + `docs/runbooks/live-migration-apply.md`) mergeado como PR #184 / merge commit `a5e5ee8` (Closes #183) el 2026-07-12. PR1 (pyodbc executor sin dependencia MCP, seam `set_legacy_query_executor` estable M0→M2) mergeado como PR #176 / merge commit `0d2e72d` (Closes #175) el 2026-07-11. PR2 (`ShadowStateRepository.ensure_table()` + private `apap-photos` bucket con `isPublic=false` invariable fail-closed + runbook endurecido) mergeado como PR #180 / merge commit `df483e3` (Closes #179) el 2026-07-11. **M1 pendiente**: follow-up de media forward (`migration/photo_migration.py` + bloque storage de `migration/mappings/animal.yaml`). **M2 pendiente**: PR7 (gate `verify-fallback-ready` con `--ci-only` para CI + `--full` con atestación de operador). Tras PR7 verde, E2E canónico CI en `tests/e2e/test_animals_foto_auth.py` (3 paths: autenticado 200 / 302 a `/login` sin sesión / sentinel `__missing__`, con buckets `apap-photos-test-<8hex>` efímeros creados y borrados dentro de cada test).

**Invariantes no negociables (definidas por `proposal.md` y `tasks.md`):**

- **Privacidad de datos y fotos**: bucket `apap-photos` con `isPublic=false` (invariante PR2 + test `test_public_bucket_aborts` con exit 5). PR4b cerró M1.storage-implementation en issue #191 / PR #192 / merge `8002010`: la ruta `GET /animales/{animal_id}/foto` exige sesión válida (302 a `/login` si no autenticado), consume el stream antes de construir la respuesta para convertir fallos iniciales, mid-stream y de lookup SQL en el PNG placeholder, y nunca expone la URL presignada. `REDACTED_FIELDS` pasó de 12 a 15 (`dni`, `tel1`, `tel2`) y la auditoría de PII quedó en **PASS**; los commits de remediación 4R `688653e`+`9821bd7`+`4717a4b`+`cde7c03`+`df28fc1`+`40b5285`+`1fc58f8` cerraron el review en **PASS**, y el drift guard contra PR4a (evidence hash `62f025e2df0d4fe92e61baa7cf001f34cb3eccdf525564d9ca13bc636bfdac07` consumido sin cambios) sigue anclando el contrato `apap-photos` en `docs/discovery/storage-contract-2026-Q3.md`. Invariante verificado en PR2 con `test_bucket_visibility_missing_or_null_fails_closed` (502 `bucket_visibility_unknown` ante `isPublic` ausente o null) y `test_apply_bootstrap_failure_does_not_acquire_lock_or_read_legacy` (no lock ni read en bootstrap failure). PR3 trae el MSACCESS pre-flight fail-closed (`test_preflight_failure_does_not_acquire_lock_or_read_legacy` + `test_apply_fails_closed_when_process_iteration_errors` + `MsAccessPreflightUnavailableError` con `reason=msaccess_preflight_unavailable` → exit 5).
- **M1 forward usable NO es fallback-ready**: tener M1 verde (animales, voluntarios, entradas y fotos migrados vía `apply_legacy_to_web`) NO equivale a poder volver atrás mientras el legacy siga siendo la fuente. **El gate `verify-fallback-ready` (PR7) sigue siendo obligatorio** antes de cualquier decisión de retirar el Access legacy como fuente operativa; el round-trip M2 (PR6) ya prueba ida-y-vuelta como capacidad pero no certifica la decisión de retirar el legacy — esa certificación la cierra PR7.
- **TDD estricto, fixture-first, idempotente**: cada PR arranca con RED (tests antes de código) bajo `tests/migration/` y `tests/test_*.py`. PR1 fijó la pauta (14 átomos + seam `set_legacy_query_executor` + autouse fixture `_reset_legacy_executor` en `tests/migration/conftest.py`). E2E canónico CI vive en `tests/e2e/conftest.py` + `tests/e2e/test_landing.py` + `tests/e2e/test_nav_layout.py`. Cobertura efectiva: rutas públicas sin sesión (`/healthz` liveness JSON, redirect auth-guard `/` → `/login`, `/animales` sin sesión → `/login`, `/unauthorized` → `/login`), regresión visual del login (APAP primary blue `#0A91EB`, gradient `#076FB8`, label «Entrar con Gmail», footer `#076FB8`), y sentinels de layout responsivo a 375 / 768 / 1280 px (overflow nav + scroll horizontal). **No existe E2E autenticado en CI todavía** — `tests/e2e/test_animals_foto_auth.py` referenciado en versiones anteriores de este doc no está en el árbol actual; el job `e2e` de `ci.yml` queda skip cuando `APAP_OAUTH_CLIENT_ID` no está configurado (pre-MVP sin secretos OAuth en CI), y el job `test` excluye `tests/e2e/` con `--ignore=tests/e2e` para evitar colisión playwright↔pytest-asyncio. La ampliación de cobertura E2E real está trackeada en #206 (bloqueada por secretos OAuth en CI) y #223 (runner autoalojado dedicado).
- **Ejecución con datos reales solo tras los gates de código**: las unidades de trabajo de operador listadas en `tasks.md` Phase 4 (`ensure-bucket --check-only`, `apply --check-only`, `apply`, `reconcile --check-only`, `status --photos`, `verify-fallback-ready --full`) se ejecutan exclusivamente después de que los gates de código (lint + test + build + `verify-fallback-ready --ci-only` en CI) estén verdes. Sin `verify-fallback-ready` verde y auditado, no se autoriza el cambio de modo.

**Documentación de referencia:**

- [`openspec/changes/live-data-migration-sandbox/proposal.md`](../openspec/changes/live-data-migration-sandbox/proposal.md) — D-LIVE-01 (runtime boundary verificado): riesgos, fuera-de-alcance y rollback por fase del cambio.
- [`openspec/changes/live-data-migration-sandbox/tasks.md`](../openspec/changes/live-data-migration-sandbox/tasks.md) — PR1-PR7 + Phase 4 (operador) + Phase 5 (E2E); forecast de revisión y chain strategy `auto-chain`. PR1, PR2, PR3, PR4a, PR4b, PR5 y PR6 cerrados.
- [`openspec/changes/live-data-migration-sandbox/specs/live-migration-runtime-boundary/spec.md`](../openspec/changes/live-data-migration-sandbox/specs/live-migration-runtime-boundary/spec.md) — capability ya entregada por el merge `0d2e72d` (PR1).
- [`openspec/changes/live-data-migration-sandbox/specs/live-migration-private-photo-storage/spec.md`](../openspec/changes/live-data-migration-sandbox/specs/live-migration-private-photo-storage/spec.md) — invariante de privacidad de fotos (PR2 + PR3 + PR4a + PR4b cerrados: invariante de bucket privado verificado / M1 core apply safety verificado / storage contract pinned via spike operator-supplied reversible sentinel con sha256 `62f025e2df0d4fe92e61baa7cf001f34cb3eccdf525564d9ca13bc636bfdac07` y sentinel cleanup manteniendo bucket privado `object_count=0/total=0` / storage media + ruta foto fail-closed + `REDACTED_FIELDS += dni/tel1/tel2` + auditoría PII `PASS`).
- [`openspec/changes/live-data-migration-sandbox/specs/live-migration-pii-controls/spec.md`](../openspec/changes/live-data-migration-sandbox/specs/live-migration-pii-controls/spec.md) — invariante de controles PII (PR5 cerrado PR #196 / merge `024dc973`): 5 átomos `sync.applied` parametrizados sobre `REDACTED_FIELDS`, `shadow.preserved_value` masking, `MigrationReport.to_json()` no-PII regex, CLI stdout no-PII (incluido `derived_value` masking), redaction-list-covers-all-PII invariant; forward legacy→web produce 0 DNI collisions + first-web-DNI-wins + reverse-path collision recorded; PUBLIC_PATHS 5-entry shape pinned (`/healthz`, `/login`, `/auth/google`, `/auth/callback`, `/logout`) con 302-to-`/login` parametrizado sobre las 5 rutas PII-displaying.
- [`openspec/changes/live-data-migration-sandbox/specs/live-migration-bidirectional-completion/spec.md`](../openspec/changes/live-data-migration-sandbox/specs/live-migration-bidirectional-completion/spec.md) — capacidad de round-trip simétrico entregada por PR6 (`apply_web_to_legacy` + 5 átomos de round-trip en `tests/migration/test_round_trip.py` + per-strategy-table honoured symmetrically on reverse: `preserve` avanza `last_legacy_snapshot_at` sin escribir `preserved_value`, `derived` no re-deriva, `fixed` nunca escrito).
- [`docs/runbooks/live-migration-apply.md`](runbooks/live-migration-apply.md) — runbook canónico de apply cierra PR3 con exits 5/6/7 + psutil prerequisite + check-only + private infra + snapshot/partial files + no-auto-resume + no-destructive-removal + rollback + escalation, ampliado en PR6 con la sección "Reverse direction (PR6 / M2)" cubriendo los 5 headings AGENTS §13 (when-to-trigger / pre-deploy checklist / deploy steps / verification / rollback) para el flujo simétrico `apply_web_to_legacy`; los `MigrationReport` counts/source_hashes/collisions quedan consumidos por el reverse applier para la decisión PR7.
- [`docs/discovery/migration-risks.md`](discovery/migration-risks.md) — riesgos abiertos ampliados con §"Source snapshot identity" (PR3 lock-snapshot contract re-referenciado) + §"Collision policy (corrected)" (3 columnas PII legacy-mapped + 1 web-only `voluntarios.dni`) en PR5 y reverse-path collision semantics en PR6 (web-to-legacy `record_dni_collision` con `origin_direction="web-to-legacy"` stamp + `DniCollisionCounter` per-run mutable + reconcile CLI `--filter-direction` ya consumiendo el stamp).

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

## 4. Issues abiertos (refresco 2026-07-30)

> **✅ GATE RESUELTO (2026-08-05) — el bloqueo que anunciaba esta sección era falso.**
> El change `openspec/changes/legacy-discovery-interrogatorio` **SÍ existe en disco** y
> está trackeado en git: `proposal.md`, `tasks.md` y `specs/` entraron el **2026-07-31**
> con el commit `12f6fb3` («docs(sdd): consolidate legacy-discovery-interrogatorio —
> closes #343 Path A»), un día después del refresco 2026-07-30 que redactó este aviso.
> Los 22 features con `status:approved` **no están bloqueados** por esta causa.
>
> Lección de proceso: este documento se declara «punto de entrada único», así que un
> aviso obsoleto aquí no es ruido — detiene trabajo real. §9 obliga a refrescarlo en la
> misma sesión en que algo cambia; ese refresco no ocurrió entre el 2026-07-31 y el
> 2026-08-05, y el resultado fueron cinco días anunciando un bloqueo inexistente.
> Verificar un GATE antes de propagarlo es parte del refresco, no un extra.

> Lista representativa — auto-actualizable con `gh issue list --state open`. Muestra abierta, priorizada por recencia + relación con roadmap, no exhaustiva. **Las cerradas están listadas al final de esta sección.**

> **Estado de PRs abiertos al 2026-08-05** (tras la limpieza que dejó el remoto en `main` + 3 ramas):
>
> - **#406** `chore/issue-392-deadcode` — CI en rojo. Borrado de 5 símbolos muertos (#392).
> - **#408** `fix/issue-387-s608-sql-v2` — CI en rojo y **~97 commits por detrás de `main`**.
>   Cubre la mitad `app/modules/` del triaje S608. **No mergear tal cual:** su triaje se midió
>   cuando había 57 sitios; hoy hay 54 (tras #422) y su rama no lo sabe. El harness de #387
>   obliga a re-medir y comentar cuando el número difiere, no a ajustar el objetivo. Los
>   conflictos con `main` que aparentan reescrituras de fichero completo son artefacto de
>   finales de línea: con `--ignore-all-space` el cambio real son ~16 líneas.
> - Dos ramas remotas corresponden a PRs **cerrados sin mergear** (#362, #413) y se mantienen
>   a propósito; #413 fue el intento por capas que sustituyeron los slices verticales.
>
> **Rama local sin PR:** `rescue/329-mvp-ready-gate` conserva dos commits recuperados que
> añadían un gate `APAP_MVP_READY` al job `e2e`. **No aplicar:** su propósito era apagar e2e
> en pre-MVP, pero hoy e2e corre y pasa en `main`, así que aplicarlo restaría señal. Se
> conserva solo como registro.

> **Cerradas hoy (2026-07-05) — 3 issues P1/P0:**
>
> - **#141** `fix(acogidas) fecha_final` — PR #151 ([commit `4d4b3cd`](https://github.com/ardelperal/APAP_WEB/pull/151))
> - **#142** `feat(foster) override→estancia atomicity` — PR #155 ([commit `3672d33`](https://github.com/ardelperal/APAP_WEB/pull/155)) + PR #156 ([commit `27cab72`](https://github.com/ardelperal/APAP_WEB/pull/156)) + cherry-pick `28d04e9`
> - **#143** `fix(auth) revocación inefectiva` — PR #152 ([commit `6058a5a`](https://github.com/ardelperal/APAP_WEB/pull/152)); audit en [`docs/audits/auth-revalidation-2026-Q3.md`](audits/auth-revalidation-2026-Q3.md) — **PASS**
>
> **Cerradas hoy (2026-07-12) — PR4b/M1.storage-implementation:**
>
> - **#191** `feat(migration) PR4b` storage-implementation + foto route + PII audit + runbook extensions — PR #192 ([commits `e7f5857`+`b021e12`+`b74a135`+`f977c9e`+`688653e`+`9821bd7`+`4717a4b`+`cde7c03`+`df28fc1`+`40b5285`+`1fc58f8`](https://github.com/ardelperal/APAP_WEB/pull/192), merge `8002010`); audit [`docs/audits/pii-live-migration-2026-Q3.md`](audits/pii-live-migration-2026-Q3.md) **PASS**; 4R remediation **PASS** (CRIT-1 + WARN-1/3/4/5/2 + verify headline, 7 commits bounded); CI run `29202180163` `conclusion=success` (lint + test + build)
>
> **Cerradas hoy (2026-07-18) — PR5/M1 PII controls + reconcile + discovery:**
>
> - **PR #196** `feat(migration): PR5 PII controls + reconcile --filter-direction + discovery doc` — sin issue de seguimiento abierta (secuencia PR1→#175 / PR2→#179 / PR3→#183 / PR4a→#187 / PR4b→#191 se rompió en PR5 por scope discipline); ([commits squash `b463d5e`+`c278468`+`1cdd043`+`f02b82c`+`8fe6104`+`607191c`+`a72f491`+`af214c6`+`810afc3`+`357579c`](https://github.com/ardelperal/APAP_WEB/pull/196), merge `024dc97307a745834f103be4ea27687c4381f93e`, +2691/-384 sobre 16 archivos, `size:exception` pre-MVP autorizado por mantenedor "no reviewers in pipeline"); audit [`docs/audits/pii-live-migration-2026-Q3.md`](audits/pii-live-migration-2026-Q3.md) **PASS** ampliada con sección "## PR5 Additions (2026-07-15)"; discovery [`docs/discovery/migration-risks.md`](discovery/migration-risks.md) extendido (+37 líneas: source-snapshot-identity + collision-policy); nuevos átomos `tests/migration/test_pii_redaction.py` (10) + `tests/migration/test_dni_collision.py` (9) + `tests/test_public_paths.py` (10) = 29 átomos M1 adicionales sobre los 70 de PR4b; CI run `29634884361` `conclusion=success` (lint + test + build PASS, GitGuardian PASS; e2e/deploy SKIPPED — esperado pre-MVP); validation gate `gentle-ai review validate` invalidated (legacy v1 receipts missing + compact v2 en `reviewing`), se cae a CI verde por directiva pre-MVP "no reviewers in pipeline"; rama `feat/migration-pr5-pii-controls` borrada en local y en origin per AGENTS §15.2
>
> **Cerradas hoy (2026-07-18) — PR6/M2 reverse-apply + round-trip:**
>
> - **PR #213** `feat(migration): PR6 reverse apply + round-trip tests (M2)` — sin issue de seguimiento abierta (secuencia de issues PR1→#175 / PR2→#179 / PR3→#183 / PR4a→#187 / PR4b→#191 / PR5-sin-issue / PR6-sin-issue rota por scope discipline); ([commits squash `5255f67`+`74f5f64`+`52c328a`+`e69aa2b`+`ef09dd3`+`6c91fbd`+`d8e8ff6`+`e04e600`+`5de296c`](https://github.com/ardelperal/APAP_WEB/pull/213), merge `2782cb6e66a595de4dfbeff33d84e481f2522a3f`, +6391/-2533 sobre 26 archivos, `size:exception` pre-MVP autorizado por mantenedor "no reviewers in pipeline"); entrega M2 simétrico (`migration/apply_reverse.py::apply_web_to_legacy` con sync-state snapshot transactional pre-apply + diff por tabla en memoria + per-row INSERT/UPDATE con `log_safe("sync.applied")` audit + emisión `LIFECYCLE_REVERSED` con `source_direction="web-to-legacy"` + reverse-path collision routing vía `record_dni_collision` + `preserve` columns bump `web_only_feature_shadow.last_legacy_snapshot_at` sin escribir `preserved_value` + derivation engine NEVER invoked on reverse); 14 átomos nuevos sobre los 99 de PR5: 9 en `tests/migration/test_reverse_apply.py` (inserts/updates/dry-run/dry-run-zero/preserve-not-written/derived-no-rederive/lifecycle-emitted/sync-state-updated/sync-state-rollback-on-write-failure) + 5 en `tests/migration/test_round_trip.py` (100 animals preserve nchip / 100 voluntarios preserve dni / 3 edits apply 3 updates / detects unsynced edits as needs_review / counts preserved); lens-fix `52c328a` (F1 logger alias `logging_mod.log_safe` + F2 sync-state snapshot post-lock) + `e69aa2b` (F3–F8 review findings: per-row keyword-only signature, sync_state_path override, dry-run zero reporting, dry-run no-shadow-write, legacy_write executor DI seam, atomic lock-context rollback); module-size ratchet R1 (`migration/apply.py` -3L revert direction kwarg plumbing) + R2 (`migration/cli.py` 1226→933 + nuevo `migration/cli_apply_reverse.py` 370L) + R3 (`migration/apply_reverse.py` 1165→86 shim + nuevo package `migration/reverse_apply/` con 7 sub-módulos `__init__`/orchestrator/per_row/shadow/lifecycle/lock_context/io_helpers/types; `BASELINE` `cli.py` mejora 1071→933 ratcheted shrink-only) + `5de296c` (MSACCESS psutil autouse fix para CI sin psutil); audit [`docs/audits/pii-live-migration-2026-Q3.md`](audits/pii-live-migration-2026-Q3.md) **PASS** ampliada con sección "## PR6 Additions (2026-07-18, reverse apply + round-trip)"; runbook [`docs/runbooks/live-migration-apply.md`](runbooks/live-migration-apply.md) extendido con sección "Reverse direction (PR6 / M2)" cubriendo los 5 headings AGENTS §13 (when-to-trigger / pre-deploy checklist / deploy steps / verification / rollback); discovery [`docs/discovery/migration-risks.md`](discovery/migration-risks.md) extendido con reverse-path collision semantics (web-to-legacy `record_dni_collision` + `DniCollisionCounter` per-run mutable + reconcile CLI `--filter-direction` consumiendo el `origin_direction="web-to-legacy"` stamp); full migration suite 261 passed (preserved), full local gate 2413 passed + 2 skipped + 0 warnings; CI run `29661279842` `conclusion=success` (lint + test + build PASS, GitGuardian PASS; e2e/deploy SKIPPED — esperado pre-MVP); validation gate `gentle-ai review validate` invalidated, se cae a CI verde por directiva pre-MVP "no reviewers in pipeline"; rama `feat/live-migration-reverse-apply` borrada en local y en origin per AGENTS §15.2

| # | Título | Área | Estado |
|---|---|---|---|

> **Cerradas hoy (2026-07-30) — 6 issues del wave post-2026-07-27:**
>
> - **#51** `HEALTH-02: batch API de actuaciones con commit transaccional + staging preview + D-24 per-record` — PR #322 (merge `f237c55`); endpoint `POST /sanidad/actuaciones/batch` con CTE PostgreSQL atómico para N≥5 records, dry-run staging preview, validación D-24 per-record, y helpers de query-builder seam (`sanidad/queries.py` + `batch_service.py` + `batch_routes.py`); 33 átomos TDD strict; cobertura 93.37%.
> - **#36** `VOL-03: pipeline de deduplicación fuzzy de voluntarios legacy` — PR #321 (merge `e0f6eeb`); `migration/volunteer_dedup.py` con union-find + 3 pre-passes exact-name/DNI/fuzzy + `rapidfuzz>=3.0` (decisión D-25); 19 átomos TDD; `rapidfuzz` añadida a `[project.optional-dependencies.etl]`.
> - **#32** `feat(animals): schema append-only animal_lifecycle_events + cache materializado` — PR #320 (merge `0049708`); tabla `animal_lifecycle_events` (12 cols + 14-event CHECK + 2 índices) + tabla `animal_current_state` (11 cols) + trigger append-only + service `evaluate_causal_pair` (D-23); bloquea LIFECYCLE-03 (#33).
> 
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
| Migración en vivo PR5 (M1 milestone) | `feat(migration): controles PII + reconcile + actualizar discovery` | PR4b cerrado (`8002010`) | ✅ merged 2026-07-18 vía PR #196 (merge `024dc973`, 10 commits squash + dysflow-config delegate, +2691/-384 sobre 16 archivos; 29 átomos nuevos en `tests/migration/{test_pii_redaction,test_dni_collision}.py` + `tests/test_public_paths.py`; CI run `29634884361` `conclusion=success` con GitGuardian PASS) |
| Migración en vivo — media forward | `feat(migration): photo_migration + storage block de animal.yaml` | PR4b cerrado (`8002010`) | 🔲 pendiente por scope-discipline |
| Migración en vivo PR6 | `feat(migration): apply_reverse.py + round-trip M2` | PR5 cerrado (`024dc973`) | ✅ merged 2026-07-18 vía PR #213 (merge `2782cb6e66a595de4dfbeff33d84e481f2522a3f`; +6391/-2533 sobre 26 archivos; 14 átomos nuevos sobre los 99 de PR5: 9 `test_reverse_apply.py` + 5 `test_round_trip.py`; lens-fix `52c328a`+`e69aa2b`; module-size ratchet R1+R2+R3 con `migration/reverse_apply/` package; CI run `29661279842` `conclusion=success` con GitGuardian PASS) |
| Migración en vivo PR7 | `feat(migration): verify-fallback-ready + gate CI` | PR6 cerrado (`2782cb6`) | 🔲 pendiente (gate M2) — **PR7 sigue sin issue de seguimiento abierta en GitHub**; crear con el skill `issue-creation` después de la revisión de este refresco (no en esta unidad). Naming propuesto: `feat(migration): PR7 verify-fallback-ready + gate CI`. Tras su creación, añadir fila a §4 y enlazar desde §5 |
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
- [`docs/audits/pii-live-migration-2026-Q3.md`](audits/pii-live-migration-2026-Q3.md) — auditoría PR4b + PR5 + PR6 de controles PII, redacción y almacenamiento privado de fotos (issue #191 / PR #192 / merge `8002010` + PR #196 / merge `024dc973` + PR #213 / merge `2782cb6`, **PASS**; secciones "## PR5 Additions (2026-07-15)" + "## PR6 Additions (2026-07-18, reverse apply + round-trip)" preservan el verdict PR4b y enumeran los 5 nuevos átomos M1 + los 14 átomos M2 simétricos)

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

---

## 10. Orden de ejecución en paralelo

> Sección añadida en el refresco 2026-07-22. Codifica la secuenciación
> acordada para el lote de issues abiertas identificadas en el audit del mismo
> día (16 issues en 5 cohortes), bajo la política pre-MVP single-branch
> (AGENTS.md §15.2: una sola rama al final de cada ciclo de merge; nada de
> `staging`; merge directo a `main` con CI verde + `code-review-expert`).

### 10.1 Constraints operativos

- **Merge serially a `main`**: en pre-MVP no hay `staging`. Cada PR cerrada se
  integra a `main` una por una; nunca dos PRs en paralelo sobre la misma
  rama, nunca un PR que asuma el contenido de otro PR aún no mergeado. Si dos
  unidades de trabajo se pisan en archivos comunes, la segunda se rebasa sobre
  la primera tras el merge (no se apila antes).
- **Una rama de trabajo por unidad**: cada issue / PR usa su propia rama
  dedicada (`docs/<scope>`, `feat/<scope>`, `fix/<scope>`, `refactor/<scope>`
  según §15.2). No se comparten worktrees entre unidades; cada subagente /
  sesión trabaja sobre su rama y, tras merge verde, la rama se borra
  (`git branch -d` local + `git push origin --delete`).
- **TDD estricto antes de merge**: tests rojos primero (§4 proceso); merge
  bloqueado si pytest `-W error::DeprecationWarning` no está verde o si
  ruff/check_rules/check_module_size/check_route_size fallan (§5 proceso).

### 10.2 Cohortes y secuencia

Las 16 issues abiertas identificadas en el audit del 2026-07-22 se agrupan en
5 cohortes. Dentro de cada cohorte, las issues se mergean en serie a `main`
con la cadencia indicada. Entre cohortes, la dependencia es dura: la cohorte
N+1 no arranca hasta que la cohorte N cierra.

#### Cohorte A — bajo-choque (reglas, refactors de hygiene, discovery)

Issues que tocan áreas disjuntas y no chocan entre sí; pueden prepararse en
paralelo en worktrees separados, pero **se mergean en serie a `main`**.

1. **#210** (`fix(make) check-rules`) — corrige el escaneo raíz del linter
   APAP001/APAP003 + detecs 5-8. **Primero** porque desbloquea la señal
   verde/roja local antes de cualquier otro refactor de hygiene.
2. **#204** (`refactor(app) main.py`) — extrae middleware de auth + registro
   de rutas. **Después** de #210 para que el linter esté saneado.
3. **#205** (`refactor(services) query builders`) — extracción de query
   builders en `materiales`, `acogidas`, `adopciones`. **Split por módulo**
   (#205a materiales, #205b acogidas, #205c adopciones), cada uno en su PR;
   merge seriado para mantener review focus bajo el presupuesto de 400 líneas
   (regla 15.1).
4. **#30** (`LIFECYCLE-05 search API`) — independiente; orden flexible dentro
   de la cohorte.
5. **#6** + **#7** (discovery UX/UI + motor de tareas) — abren como issues de
   discovery primero (no implementación); entrada de §3 transversal. No
   requieren PR de código en esta cohorte.

> **Por qué este orden:** #210 deja el linter fiable, #204/#205 luego pueden
> confiar en la señal local del linter antes de tocar código compartido.

#### Cohorte B — triage de bugs de migración (M2 follow-ups)

Issues #217 / #218 / #219 son bugs detectados en la revisión de PR6/M2
(`apply_reverse`). Reglas:

- **#218 primero**: `execute_legacy_write` swallowing `conn.commit()` failure
  es un silent durability gap que precede al PR7. Sin #218 cerrado, PR7 no
  se puede certificar como `verify-fallback-ready` (la durabilidad del round-trip
  no está probada bajo fallo de commit).
- **#217 segundo**: increment semantics del `dni_collision_counter` en
  `apply_reverse`; depende de que la escritura sea ya durable (#218).
- **#219 tercero**: `_PII_VALUE_PATTERNS` (NIE / NIF-especiales / numeric-NCHIP
  false-positives); ortogonal a #217/#218, pero se mete en la misma cohorte
  porque comparte review focus (capa `migration/`).
- Tras los tres bugs cerrados: **PR7 (`verify-fallback-ready`)** se puede
  ejecutar en serio. PR7 sigue sin issue de seguimiento abierta en GitHub —
  el refresh actual lo deja como follow-up a crear con el skill
  `issue-creation` tras la revisión de este doc.

> **Por qué este orden:** la precedencia #218 → #217 → #219 está dictada por
> la cadena de dependencia dura (durabilidad → counter semantics → PII
> patterns); el PR7 no se ejecuta hasta que las tres cierran.

#### Cohorte C — preflight del ciclo de vida animal

- **#32 + #69** primero, en cualquier orden (schema del timeline + cache
  materializado `estado_actual_animal`). Ambos son trabajo estructural
  previo al state resolver.
- **#33 después**: state resolver (`DameSituacion()` legacy replication)
  consume el schema de #32 y la materialización de #69. Sin las dos
  predecesoras, #33 no se puede testear con golden fixtures.
- **#29** (`LIFECYCLE-04 cambio de chip con cascade`) corre en paralelo a #33
  en worktrees separados, pero **se mergea después de #33** porque la cascade
  necesita el state resolver para validar la transición pre-cambio.

#### Cohorte D — voluntarios legacy

- **#36** (`VOL-03 pipeline de deduplicación fuzzy`) ✅ cerrada 2026-07-27
  (esta unidad de entrega) y **#37** (`VOL-04 migración FK free-text → FK
  estructurada`) son ortogonales pero ambas tocan `voluntarios` y
  `legacy` adapters; **se mergean en serie a `main`** en el orden
  #36 → #37 (primero deduplicación para que el siguiente paso
  encuentre menos filas). #37 desbloqueada por cierre de #36.

#### Cohorte E — health batch + RBAC

- **#51** (`HEALTH-02 API batch`) y **#52** (`HEALTH-03 API resumen`) requieren
  cada uno su propio service + seam de query builder separado (`#205b` ya
  introduce el patrón en `materiales`; replicar a `salud`). **No se mergean
  hasta que cada uno tenga su propio seam de servicio** — comparten la misma
  tabla (`actuacion_sanitaria`) pero exponen shapes distintos. Tras #205
  cerrado, se pueden abordar en cualquier orden.
- **#66** (`RBAC-01 matriz de permisos`) corre en paralelo en su propia rama;
  se mergea al final porque consolida el modelo RBAC que las unidades
  anteriores asumieron implícitamente.

### 10.3 Visualización del orden

```
Cohorte A:  #210 → #204 → #205a (materiales) → #205b (acogidas) → #205c (adopciones) → #30 → #6/#7 (discovery)
Cohorte B:                ↓                                  #218 → #217 → #219 → [PR7]
Cohorte C:                                                            ↓           #32+#69 → #33 → #29
Cohorte D:                                                                            ↓   #36 → #37
Cohorte E:                                                                                ↓   #51 / #52 (paralelo en worktrees, serie en main) → #66
```

Las flechas verticales son dependencias duras; las horizontales son merge
serializado. Las unidades paralelas dentro de una misma fila usan worktrees
distintos pero se mergean una a una a `main`.

### 10.4 E2E y discoverability

- **#206** (E2E real) y **#223** (runner dedicado) viven en una cohorte
  transversal separada, fuera de las cinco cohortes principales. **#206 está
  bloqueada por la ausencia de `APAP_OAUTH_CLIENT_ID` en CI**; **#223 es el
  desbloqueador de #206** (un runner autoalojado puede tener el secret sin
  filtrarlo). Mientras ambos estén abiertos, la cobertura E2E real queda
  diferida y los tests `tests/e2e/` siguen siendo público-only (sin
  autenticación).



---

## 11. Protocolo de sincronización (refresco 2026-07-22)

Esta sub-sección codifica el protocolo de sincronización entre `main`, las
issues de GitHub y este roadmap. Es **obligatoria** a partir de este refresh;
toda unidad de trabajo que toque issues o fases debe aplicarla en el mismo
ciclo de entrega.

### 11.1 Regla base

**Cada issue que se cierra (merged o resuelta sin PR) debe actualizar
`docs/roadmap.md` §4 + la fila de la fase correspondiente en §3 en la misma
unidad de entrega.** No se acepta "lo actualizo mañana": la doc queda
sincronizada con el commit que cierra la issue, en el mismo PR (o, si la
issue se cierra sin PR, en un PR de docs dedicado `docs(roadmap): ...`).

### 11.2 Refresco del roadmap antes de seleccionar nueva issue

Antes de tomar una nueva issue abierta, **el roadmap debe estar al día**.
Procedimiento:

1. Ejecutar `gh issue list --repo ardelperal/APAP_WEB --state open` y comparar
   contra §4.
2. Si hay issues abiertas en GitHub que no están en §4 → añadir fila en §4
   (o mover de §5 si estaba como "pendiente por crear").
3. Si hay filas en §4 cuyo estado GitHub es `CLOSED` → moverlas a la lista
   de "Cerradas hoy" con la fecha y el SHA / PR de cierre.
4. Si una fase (§3) cambia de estado (🔲 → 🟡 → ✅) → actualizar la fila de
   la fase + la fecha "Última actualización" de la línea 5.
5. Solo entonces seleccionar la siguiente issue.

### 11.3 Sincronización dentro del mismo ciclo

Acciones que viven en el **mismo PR** que la implementación (no en PRs
separados, salvo cuando el cambio sea docs-only):

- Apertura de issue: añadir fila a §4, retirar de §5 (si estaba).
- Cierre de issue: quitar fila de §4 (o reemplazar el 🔲 por ✅ con SHA + PR),
  reflejar el cambio en §2 si toca algo visible allí, actualizar fase §3.
- Cambio de estado de fase: leyenda 🔲 / 🟡 / ✅ en §3 + fecha línea 5.
- Nueva documentación: añadir a §6 en el mismo PR.
- Nueva decisión: añadir a `docs/decisiones-proyecto.md` y enlazar desde §3,
  no duplicar.

### 11.4 Anti-patrones explícitos

- ❌ Cerrar issue en GitHub sin tocar `docs/roadmap.md` → violación del §11.1.
- ❌ Marcar una issue como cerrada en §4 sin verificar `gh issue view <N>`
  (`state=CLOSED`) → falso cierre; auditoría en §4 #55 es el ejemplo
  canónico de lo que NO se hace.
- ❌ Acumular cierres en una sola entrada "Cerradas hoy (últimas 2 semanas)"
  → cada cierre tiene su bloque fechado para que la búsqueda temporal
  funcione.
- ❌ Refrescar el roadmap **después** del PR en vez de en el mismo PR → la
  doc se desactualiza entre el merge y el refresh, ventana en la que otro
  agente puede tomar decisiones sobre estado obsoleto.
- ❌ Modificar `docs/proceso.md` o `AGENTS.md` desde la rama de un feature
  PR → los docs operativos van por rama dedicada `docs/<scope>` per §17.3.
