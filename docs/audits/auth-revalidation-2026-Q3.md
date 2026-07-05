# Auditoría: re-validación de autorización por request — 2026 Q3

**Scope**: `require_authorized_user` y la cadena de autorización cookie ↔ DB (issue #143)
**Method**: code review + codegraph caller analysis + cobertura de tests (TDD) + análisis de blast radius del nuevo `client` dep
**Date**: 2026-07-04
**Verdict**: **PASS** — la autorización es ahora revocable en ≤ `auth_cache_ttl_seconds` (default 300s), en vez de hasta 7 días. La cookie firma la identidad; la DB (`usuarios_autorizados`) es la fuente de verdad de la autorización.

---

## Scope

| Item | Value |
|---|---|
| Fix | #143 — autorización congelada en la cookie de sesión (P1) |
| Ficheros de producción | `app/core/auth_dependencies.py` (`require_authorized_user`), `app/core/auth_cache.py` (nuevo), `app/core/auth.py` (`add_authorized_user`, `deactivate_authorized_user`), `app/core/session.py` (docstring), `app/core/config.py` (`auth_cache_ttl_seconds`) |
| Cross-references | `app/main.py` (middleware `protect_user_facing_routes`, `/auth/callback`, panel `/admin`), los 11 call sites de `require_authorized_user` en `app/modules/*/routes.py` |
| Tabla | `usuarios_autorizados` (sin cambios de schema: ya tiene `activo`, `rol`, `email`) |

## Methodology

1. **codegraph_explore** (obligatorio, primero) sobre `require_authorized_user`, `protect_user_facing_routes`, `get_user_by_email`/`add_authorized_user`/`deactivate_authorized_user`, `Settings`, y los call sites — para fijar el blast radius del nuevo `client` dep ANTES de editar.
2. **Code review** de la cadena: cookie firmada → middleware (gate DB-free) → `require_authorized_user` (revalidación DB con caché TTL).
3. **TDD estricto** (rojo → verde → refactor): 10 atoms de caché (`tests/test_auth_cache.py`), 7 atoms de la dep (`tests/test_auth_dependencies.py`), 3 atoms de invalidación (`tests/test_auth.py`), más la migración de los tests de integración de rutas.
4. **Verificación local**: suite completa con `-W error::DeprecationWarning`, `ruff check .`, `scripts/check_rules.py app`, `python -m build`.

---

## Diseño

Se eligió la **Opción A** (caché TTL + lookup por request) sobre la Opción B (query por request sin caché):

- La cookie firma la **identidad** (email, user_id): estable durante los 7 días de vida de la cookie.
- La **autorización** (`is_authorized` + `rol`) se re-valida contra `usuarios_autorizados` en cada request en `require_authorized_user`, con una caché TTL en proceso (`Settings.auth_cache_ttl_seconds`, default **300s = 5 min**).
- La caché se invalida explícitamente en `add_authorized_user` (nuevo/re-alta) y `deactivate_authorized_user` (baja) por el `email` correspondiente — el `email` de la baja se toma del `RETURNING` (la baja es por `id`, la caché por `email`), sin query extra.
- La caché es un dict en proceso protegido por `Lock`. Un reinicio de proceso (deploy) la deja vacía — esa es la invalidación de deploy. `AUTH_CACHE_KEY` es un marcador de versión de esquema de caché (documental).
- El middleware `protect_user_facing_routes` **sigue sin tocar la DB** (primera puerta barata y determinista, default-deny `payload.get("is_authorized", False)`); la revalidación DB es un endurecimiento ADICIONAL en la dep, no un reemplazo.

**Regla 1 (cero SQL en routes)**: la revalidación consulta la DB vía el service `app.core.auth.get_user_by_email`, nunca SQL crudo en la dep ni en el handler. El nuevo `client: InsForgeClient = Depends(get_insforge_client_dep)` en `require_authorized_user` está permitido porque la query se hace a través del service.

## Findings

### P1 (CRÍTICO) — fixed

La autorización quedaba **congelada en la cookie** durante 7 días. Un usuario desactivado en `/admin/users/{id}/deactivate` seguía navegando con la cookie vieja hasta que expiraba, porque `require_authorized_user` sólo leía el flag `is_authorized` de la cookie (nunca re-consultaba la DB). Además, el docstring de `app/core/session.py` afirmaba falsamente que "per-request authorization is enforced by the auth middleware by looking up the email in the authorized_users table" — describía un comportamiento que el código no tenía (viola la regla 10 del baseline web: los docstrings de seguridad deben describir lo que el código hace). **Ambos corregidos**: revalidación DB real por request + docstring alineado con la realidad.

### P2 — fixed (role-refresh)

`rol` también es autorización, no sólo identidad. La revalidación refresca `rol` desde la DB, de modo que un cambio de rol mid-session (p. ej. `developer` → `reader`) se recoge en el siguiente request en vez de esperar a la expiración de la cookie. Pinneado por `test_require_authorized_user_picks_up_role_change_mid_session`.

### P3 — accepted (no fixed)

- **Ventana de staleness del TTL**: hasta `auth_cache_ttl_seconds` (default 5 min) tras una revocación, un request puede servirse desde caché. Tradeoff aceptable: sin caché = 1 query por request; con caché = freshness de minutos. Configurable vía `APAP_AUTH_CACHE_TTL_SECONDS`. Si producto exige revocación inmediata (<1s), poner el TTL a `0` (deshabilita la caché; 1 query por request). La invalidación explícita en add/deactivate cierra la ventana para el flujo de admin de la propia app.
- **Caché por proceso**: con múltiples workers, cada uno tiene su copia; una desactivación desde el worker A no invalida la caché del worker B hasta que su TTL lapse. Aceptable dentro del mismo tradeoff de minutos; un despliegue reinicia todos los procesos.
- **Cobertura de la dep**: la revalidación por request sólo aplica a rutas que usan `require_authorized_user` (11 call sites, cubren todos los módulos). El middleware sigue siendo el gate grueso DB-free para el resto.

## Blast radius del nuevo `client` dep

Añadir `client: InsForgeClient = Depends(get_insforge_client_dep)` a `require_authorized_user` significa que **todas** las rutas protegidas consultan `usuarios_autorizados` por request. FastAPI cachea la dep por request, así que los handlers que ya inyectaban `get_insforge_client` comparten la misma instancia (una sola query/cliente por request). Los tests de integración que autenticaban con una cookie `is_authorized=True` y un spy que devolvía `[]` para la query de auth pasaban a redirigir a `/unauthorized`; se migraron 17 ficheros de test para que sus spies respondan la query de revalidación con un usuario activo (helper compartido `tests/conftest.py::auth_reval_rows`), preservando las aserciones de SQL de dominio existentes.

## Verdict

**PASS**. La revocación de acceso es ahora operativa en ≤ 5 minutos (TTL configurable; 0 = inmediato). Superset del comportamiento anterior (P1 de fidelidad, `docs/proceso.md §0`): todas las rutas autenticadas siguen funcionan, pero la revocación ya no espera hasta 7 días.

---

## Issue-closure trail (PR de cierre, 2026-07-05)

El fix estructural está en `main` desde los commits `860f593`, `380c627`, `f4fa7ef`, `aea9e22`. Esta sección cierra el issue #143 con:

1. Cobertura explícita de los **escenarios nombrados** en el cuerpo del issue (los 5 tests nuevos en `tests/test_auth_dependencies.py`).
2. Limpieza del **comentario en línea** que aún describía el modelo pre-#143 (`app/main.py:486-492`).
3. Trazabilidad SDD (§regla de commits del proyecto) y enlace al PR.

### Implementation commits

| Commit | Work unit | SDD tasks | Tests | Audit / access sync |
|---|---|---|---|---|
| `0ff01db` | feat(auth-cache): add TTL cache primitive | introducir `auth_cache` (núcleo del fix) | `tests/test_auth_cache.py` (10 atoms) | creada junto al fix |
| `860f593` | feat(auth): revalidate authorization per request via TTL cache | #143 núcleo: `require_authorized_user` revalida cada request | `tests/test_auth_dependencies.py` (7 atoms nuevos: cache miss, cache hit, revocation, role refresh) | revalidación real implementada |
| `380c627` | feat(auth): invalidate auth cache on user add/deactivate | #143 invalidación explícita (cierra la ventana del TTL para el flujo admin) | `tests/test_auth.py` (3 atoms: add, deactivate, unknown id) | invalidación atada al alta/baja |
| `f4fa7ef` | chore(auth): session.py docstring + audit doc + test fixture migrations | #143 docstring corregida (regla 10) + este audit doc + helper `auth_reval_rows` | 16 route-test spies migrados a invocar `auth_reval_rows` como primera línea | `docs/audits/auth-revalidation-2026-Q3.md` creado |
| `aea9e22` | fix(auth): close write-after-invalidate race + extract admin dep + audit denials (#145, #146) | endurecimiento post-#143: race CAS-style por email en el cache (#145) + `require_developer_user_redirect` + `log_safe("auth.denied", reason=...)` en las 3 deps (#146) | `tests/test_auth_cache.py` (+3 race atoms), `tests/test_auth_dependencies.py` (+3 audit log atoms) | audit trail completo |
| `8cc15e2` | test(auth): pin #143 user-visible scenarios by name + audit doc closure | cierra #143 con los 5 scenarios nombrados + limpieza de comentario inline | `tests/test_auth_dependencies.py` (+5 atoms: deactivation, role revocation, audit emission, docstring AST guard, regression guard) | este audit doc ampliado |

### Cobertura nueva por escenario del cuerpo del issue

| Escenario del issue | Test nuevo | Estado |
|---|---|---|
| "desactivar un usuario vía POST /admin/users/{id}/deactivate no tiene efecto hasta que su cookie expire" | `test_deactivation_takes_effect_on_next_request` | ✅ green contra la implementación actual |
| "Expected: denegado en la siguiente request" | `test_role_revocation_takes_effect_on_next_request` | ✅ green — la siguiente request ve el rol refrescado |
| Audit trail (regla 9, 12-field redaction) | `test_log_safe_emitted_on_deactivation_denial` | ✅ green — `auth.denied / reason=db_reval_miss` con `user_id`, sin `email` |
| Docstring de `session.py` (regla 10) | `test_session_docstring_no_longer_lies` | ✅ green — guard AST que falla si vuelve el texto mentiroso |
| Happy path (regresión) | `test_no_regression_for_active_users` | ✅ green — usuario activo sigue pasando |

### Review lenses (auto-revisión `code-review-expert`)

Lanzado en este PR contra `main...test/issue-143-closure-2026-Q3`. Resumen:

- **BLOCKER**: 0
- **CRITICAL**: 0
- **WARNING**: 1 — la rama de trabajo (`test/issue-143-closure-2026-Q3`) no coincide con el nombre solicitado en el prompt original (`fix/auth-per-request-validation-2026-Q3`); el nombre original fue reclamado por otro proceso en el mismo repo durante la sesión. Sin impacto en el código; lo trato como nota informativa, no bloqueante (ver "Notas operativas" abajo).
- **SUGGESTION**: 0

Verdict del review-lens: **APPROVED**.

### Pruebas locales

- `pytest tests/test_auth_dependencies.py tests/test_auth_cache.py tests/test_auth.py` → **68 passed** (5 nuevos + 63 existentes).
- `pytest -W error::DeprecationWarning` → **1858 passed, 3 skipped, 5 deselected** (los deselected y 2 fallos en `test_foster_assignment.py` y `test_sanidad.py::test_create_accepts_today_*` son **pre-existentes**, no causados por este PR — verificadas restaurando `tests/test_domain.py` + `tests/test_foster_assignment.py` a main y reproduciendo el mismo fallo).
- `ruff check .` → **All checks passed!**.
- `scripts/check_rules.py app` → **0 violations** en este PR (las 4 que reporta son de fixtures de detector + `tests/test_migration_004.py`, pre-existentes).

### Notas operativas

- La rama `test/issue-143-closure-2026-Q3` diverge del nombre `fix/auth-per-request-validation-2026-Q3` solicitado en el prompt original por motivos operativos (la rama original fue simultáneamente reclamada por otro agente en el mismo repo durante esta sesión; `git push` contra el mismo nombre hubiera fallado o pisado trabajo ajeno). El código y el contenido del PR son los mismos que habrían aterrizado en la rama solicitada.
- El fix estructural #143 estaba en `main` antes de empezar este PR (commits arriba). Lo que añado es **cobertura explícita + cierre trazable del issue**, no el fix en sí.
