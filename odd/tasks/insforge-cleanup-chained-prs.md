# InsForge cleanup — chained PRs (umbrella)

## Goal

Eliminar las referencias residuales a InsForge del repositorio APAP_WEB.
El código del slice hexagonal `error_handler` está muerto en runtime
(`app/main.py` ya tiene un handler genérico `@app.exception_handler(Exception)`
con `log_safe("server.unhandled_error")` — los archivos
`app/core/error_handler.py`, `app/core/di/insforge_error_handler_di.py`,
`app/core/ports/insforge_error_handler_port.py` y `app/core/adapters/insforge/`
no se importan en ningún sitio). Esta épica ejecuta el corte que el
CHANGELOG.md Unreleased documenta pero que el árbol todavía no refleja.

Esta limpieza también cierra de facto las issues abiertas que el
umbrella anterior dejó pendientes: #641 (épica de self-host Coolify),
#666 (drop de adapters), #670 (drop de test fakes).

## Scope (chained PRs)

| PR | Rama | Contenido | LOC est. |
|---|---|---|---|
| **A** | `chore/insforge-cleanup-A-hex-slice` | Eliminar 4 archivos del slice hexagonal muerto + actualizar `BASELINE_CRAP`, `check_layers.py` BASELINE, `check_slice_completeness.py` BASELINE, nota 38 de CHANGELOG.md + (incluye #967) allowlist por fingerprint en `.gitleaksignore` con nota en `docs/codebase/security.md` | ~150 |
| **B** | `chore/insforge-cleanup-B-route-aliases` | Eliminar `get_insforge_client_dep` aliases en `app/modules/{animals,adopciones,entradas}/routes.py` + verificar que ningún test los usa | ~30 |
| **C** | `chore/insforge-cleanup-C-migration-envvars` | Renombrar `APAP_INSFORGE_*` → `APAP_LOCAL_BACKEND_*` en `migration/` (`storage_spike.py`, `verify_fallback_*.py`, `web_reader_local_backend_adapter.py`) + tests afectados + fixture `fake_insforge` → `fake_backends` en `test_auth_flow.py` + eliminar la línea deprecada en `test_migrate_legacy_accdb_script.py` | ~200 |
| **D** | `chore/insforge-cleanup-D-quality-scripts` | Quitar `INSFORGE` de `_CLOUD_INFRASTRUCTURE_WHITELIST` en `scripts/check_alantyle.py` + sincronizar `check_alantyle.README.md` y `tests/test_check_alantyle.py` + limpiar `.atl/skill-registry.md` (entries `insforge*` dangling) | ~80 |
| **E** | `chore/insforge-cleanup-E-docs` | Actualizar runbooks, roadmap, audit doc: reemplazar `APAP_INSFORGE_*` por la nomenclatura nueva y marcar el audit doc como superseded por #658 | ~50 |

## Constraints

- TDD estricto: test que falla → fix → verde.
- Conventional commits sin atribución IA.
- `make verify` en verde antes de cada commit.
- Pre-MVP single-branch → todos los PRs van contra `main`.
- Presupuesto de revisión 400 líneas por PR; el PR C es el más grande y se queda justo bajo el límite.
- No merge sin OK explícito del usuario por PR (la autorización standing §15.6 aplica pero el tamaño del umbrella justifica un check-in explícito entre PRs).
- Nunca borrar ramas remotas (los worktrees locales sí se podan al cerrar).
- **Reapertura de #967**: el usuario confirmó que InsForge está deprecado en código (#924). Como evidencia formal de revocación del lado del proveedor no hay, trato "código deprecado + cleanup planificado" como suficiente para el allowlist por fingerprint. Esto se documenta explícitamente en el cuerpo del PR A con un comentario en el `.gitleaksignore` que apunte a esta limpieza.

## Renames canónicos

| Antes | Después | Razón |
|---|---|---|
| `APAP_INSFORGE_URL` | `APAP_LOCAL_BACKEND_URL` | El CHANGELOG Unreleased documenta el reemplazo |
| `APAP_INSFORGE_SERVICE_KEY` | `APAP_LOCAL_BACKEND_SERVICE_KEY` | Idem |
| `APAP_INSFORGE_ANON_KEY` | (eliminado en #654; ya no se referencia en código) | — |
| `BackendError` (mantener) | `BackendError` | El nombre actual es el canónico; no se renombra |
| `register_insforge_error_handler` (eliminar) | `app/main.py` ya tiene `@app.exception_handler(Exception)` genérico | El CHANGELOG documenta el reemplazo |
| `get_insforge_client_dep` (alias) | `get_local_postgres_executor_dep` (ya existe, el alias es backward-compat) | Eliminar el alias |
| Fixture `fake_insforge` | `fake_backends` | Cosmético + issue #670 |

## Acceptance criteria

Cada fila de la tabla Scope pasa a "PR mergeado, CI verde contra main".

## Progress log

- 2026-09-25 — Plan y chained PRs definidos tras el OK del usuario.
  4 PRs previos de la auditoría ci-audit (#968/#969/#970/#971)
  mergeados (PRs #977/#978/#979/#982). #972 cerrado (flag
  desactivada en main). #973 abierto en PR #981 esperando
  credenciales Docker Hub. #967 tratado en PR A con allowlist por
  fingerprint (con consentimiento del usuario de que InsForge está
  deprecado).
