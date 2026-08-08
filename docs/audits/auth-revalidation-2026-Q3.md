[← Back to README](../../README.md)

# auth-revalidation-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto de la introducción de la re-validación de autorización por request mediante caché TTL (issue #143), que cierra la ventana de revocación de 7 días (vida de la cookie) a un valor configurable que por defecto es 300 segundos, ejecutado en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | `require_authorized_user` y la cadena cookie ↔ DB. |
| [Methodology](#methodology) | Procedimiento TDD aplicado al fix. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del comportamiento de revocación. |
| [References](#references) | Ficheros de producción, tests y commits. |

## Scope

| Item | Value |
|---|---|
| Fix | #143 — autorización congelada en la cookie de sesión (P1) |
| Ficheros de producción | `app/core/auth_dependencies.py` (`require_authorized_user`), `app/core/auth_cache.py` (nuevo), `app/core/auth.py` (`add_authorized_user`, `deactivate_authorized_user`), `app/core/session.py` (docstring), `app/core/config.py` (`auth_cache_ttl_seconds`) |
| Cross-references | `app/main.py` (middleware `protect_user_facing_routes`, `/auth/callback`, panel `/admin`), los 11 call sites de `require_authorized_user` en `app/modules/*/routes.py` |
| Tabla | `usuarios_autorizados` (sin cambios de schema: ya tiene `activo`, `rol`, `email`) |
| Fecha | 2026-07-04 |

## Methodology

1. **codegraph_explore** (obligatorio, primero) sobre `require_authorized_user`, `protect_user_facing_routes`, `get_user_by_email` / `add_authorized_user` / `deactivate_authorized_user`, `Settings` y los call sites — para fijar el blast radius del nuevo dep `client` ANTES de editar.
2. **Code review** de la cadena: cookie firmada → middleware (gate DB-free) → `require_authorized_user` (revalidación DB con caché TTL).
3. **TDD estricto** (rojo → verde → refactor): 10 átomos de caché (`tests/test_auth_cache.py`), 7 átomos de la dep (`tests/test_auth_dependencies.py`), 3 átomos de invalidación (`tests/test_auth.py`), más la migración de los tests de integración de rutas.
4. **Verificación local**: suite completa con `-W error::DeprecationWarning`, `ruff check .`, `scripts/check_rules.py app`, `python -m build`.

## Diseño

Se eligió la **Opción A** (caché TTL + lookup por request) sobre la Opción B (query por request sin caché):

- La cookie firma la **identidad** (email, user_id): estable durante los 7 días de vida de la cookie.
- La **autorización** (`is_authorized` + `rol`) se re-valida contra `usuarios_autorizados` en cada request en `require_authorized_user`, con una caché TTL en proceso (`Settings.auth_cache_ttl_seconds`, default **300s = 5 min**).
- La caché se invalida explícitamente en `add_authorized_user` (nuevo/re-alta) y `deactivate_authorized_user` (baja) por el `email` correspondiente — el `email` de la baja se toma del `RETURNING` (la baja es por `id`, la caché por `email`), sin query extra.
- La caché es un dict en proceso protegido por `Lock`. Un reinicio de proceso (deploy) la deja vacía — esa es la invalidación de deploy. `AUTH_CACHE_KEY` es un marcador de versión de esquema de caché (documental).
- El middleware `protect_user_facing_routes` **sigue sin tocar la DB** (primera puerta barata y determinista, default-deny `payload.get("is_authorized", False)`); la revalidación DB es un endurecimiento ADICIONAL en la dep, no un reemplazo.

**Regla 1 (cero SQL en routes)**: la revalidación consulta la DB vía el service `app.core.auth.get_user_by_email`, nunca SQL crudo en la dep ni en el handler. El nuevo `client: InsForgeClient = Depends(get_insforge_client_dep)` en `require_authorized_user` está permitido porque la query se hace a través del service.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| CRITICAL | La autorización quedaba congelada en la cookie durante 7 días | fixed | Un usuario desactivado en `/admin/users/{id}/deactivate` seguía navegando con la cookie vieja hasta que expiraba, porque `require_authorized_user` solo leía el flag `is_authorized` de la cookie (nunca re-consultaba la DB). El docstring de `app/core/session.py` afirmaba falsamente que "per-request authorization is enforced by the auth middleware by looking up the email in the authorized_users table" — describía un comportamiento que el código no tenía (violaba la regla 10 del baseline web: los docstrings de seguridad deben describir lo que el código hace). Ambos corregidos: revalidación DB real por request + docstring alineado con la realidad. |
| MEDIUM | El `rol` también es autorización, no solo identidad | fixed | La revalidación refresca `rol` desde la DB, de modo que un cambio de rol mid-session (p. ej. `developer` → `reader`) se recoge en el siguiente request en vez de esperar a la expiración de la cookie. Pineado por `test_require_authorized_user_picks_up_role_change_mid_session`. |
| LOW | Ventana de staleness del TTL | deferred | Hasta `auth_cache_ttl_seconds` (default 5 min) tras una revocación, un request puede servirse desde caché. Trade-off aceptable: sin caché = 1 query por request; con caché = freshness de minutos. Configurable vía `APAP_AUTH_CACHE_TTL_SECONDS`. Si producto exige revocación inmediata (<1s), poner el TTL a `0` (deshabilita la caché; 1 query por request). La invalidación explícita en add/deactivate cierra la ventana para el flujo de admin de la propia app. |
| LOW | Caché por proceso | deferred | Con múltiples workers, cada uno tiene su copia; una desactivación desde el worker A no invalida la caché del worker B hasta que su TTL lapse. Aceptable dentro del mismo trade-off de minutos; un despliegue reinicia todos los procesos. |
| LOW | Cobertura de la dep | no action | La revalidación por request solo aplica a rutas que usan `require_authorized_user` (11 call sites, cubren todos los módulos). El middleware sigue siendo el gate grueso DB-free para el resto. |

## Blast radius del nuevo `client` dep

Añadir `client: InsForgeClient = Depends(get_insforge_client_dep)` a `require_authorized_user` significa que **todas** las rutas protegidas consultan `usuarios_autorizados` por request. FastAPI cachea la dep por request, así que los handlers que ya inyectaban `get_insforge_client` comparten la misma instancia (una sola query/cliente por request). Los tests de integración que autenticaban con una cookie `is_authorized=True` y un spy que devolvía `[]` para la query de auth pasaban a redirigir a `/unauthorized`; se migraron 17 ficheros de test para que sus spies respondan la query de revalidación con un usuario activo (helper compartido `tests/conftest.py::auth_reval_rows`), preservando las aserciones de SQL de dominio existentes.

## Verdict

PASS: la revocación de acceso es ahora operativa en ≤ 5 minutos (TTL configurable; 0 = inmediato). Superset del comportamiento anterior (P1 de fidelidad, `docs/proceso.md §0`): todas las rutas autenticadas siguen funcionando, pero la revocación ya no espera hasta 7 días.

### Issue-closure trail (PR de cierre, 2026-07-05)

El fix estructural está en `main` desde los commits `860f593`, `380c627`, `f4fa7ef`, `aea9e22`. Esta sección cierra el issue #143 con:

1. Cobertura explícita de los **escenarios nombrados** en el cuerpo del issue (los 5 tests nuevos en `tests/test_auth_dependencies.py`).
2. Limpieza del **comentario en línea** que aún describía el modelo pre-#143 (`app/main.py:486-492`).
3. Trazabilidad SDD (§regla de commits del proyecto) y enlace al PR.

### Commits de implementación

| Commit | Work unit | Tareas SDD | Tests | Audit / access sync |
|---|---|---|---|---|
| `0ff01db` | feat(auth-cache): añadir primitiva de caché TTL | introducir `auth_cache` (núcleo del fix) | `tests/test_auth_cache.py` (10 átomos) | creada junto al fix |
| `860f593` | feat(auth): revalidar autorización por request vía caché TTL | #143 núcleo: `require_authorized_user` revalida cada request | `tests/test_auth_dependencies.py` (7 átomos nuevos: cache miss, cache hit, revocation, role refresh) | revalidación real implementada |
| `380c627` | feat(auth): invalidar caché de auth en add/deactivate de usuario | #143 invalidación explícita (cierra la ventana del TTL para el flujo admin) | `tests/test_auth.py` (3 átomos: add, deactivate, unknown id) | invalidación atada al alta/baja |
| `f4fa7ef` | chore(auth): session.py docstring + audit doc + test fixture migrations | #143 docstring corregido (regla 10) + este audit doc + helper `auth_reval_rows` | 16 spies de tests de ruta migrados para invocar `auth_reval_rows` como primera línea | `docs/audits/auth-revalidation-2026-Q3.md` creado |
| `aea9e22` | fix(auth): cerrar race write-after-invalidate + extraer admin dep + audit denials (#145, #146) | endurecimiento post-#143: race CAS-style por email en el cache (#145) + `require_developer_user_redirect` + `log_safe("auth.denied", reason=...)` en las 3 deps (#146) | `tests/test_auth_cache.py` (+3 átomos de race), `tests/test_auth_dependencies.py` (+3 átomos de audit log) | audit trail completo |
| `8cc15e2` | test(auth): pinear #143 escenarios user-visible por nombre + audit doc closure | cierra #143 con los 5 escenarios nombrados + limpieza de comentario inline | `tests/test_auth_dependencies.py` (+5 átomos: deactivation, role revocation, audit emission, docstring AST guard, regression guard) | este audit doc ampliado |

### Cobertura nueva por escenario del cuerpo del issue

| Escenario del issue | Test nuevo | Estado |
|---|---|---|
| "desactivar un usuario vía POST /admin/users/{id}/deactivate no tiene efecto hasta que su cookie expire" | `test_deactivation_takes_effect_on_next_request` | green contra la implementación actual |
| "Expected: denegado en la siguiente request" | `test_role_revocation_takes_effect_on_next_request` | green — la siguiente request ve el rol refrescado |
| Audit trail (regla 9, 12-field redaction) | `test_log_safe_emitted_on_deactivation_denial` | green — `auth.denied / reason=db_reval_miss` con `user_id`, sin `email` |
| Docstring de `session.py` (regla 10) | `test_session_docstring_no_longer_lies` | green — guard AST que falla si vuelve el texto mentiroso |
| Happy path (regresión) | `test_no_regression_for_active_users` | green — usuario activo sigue pasando |

## References

- `app/core/auth_dependencies.py` (`require_authorized_user` con revalidación por request).
- `app/core/auth_cache.py` (núcleo del fix; primitiva de caché TTL).
- `app/core/auth.py` (`add_authorized_user`, `deactivate_authorized_user` invalidan caché).
- `app/core/session.py` (docstring corregido).
- `app/core/config.py` (`auth_cache_ttl_seconds`).
- `tests/test_auth_cache.py` (10 átomos + 3 de race de #145).
- `tests/test_auth_dependencies.py` (7 átomos nuevos + 5 de cierre + 3 de audit log).
- `tests/test_auth.py` (3 átomos de invalidación).
- `tests/conftest.py::auth_reval_rows` (helper compartido para spies de tests de ruta).
- Commits: `0ff01db`, `860f593`, `380c627`, `f4fa7ef`, `aea9e22`, `8cc15e2`.
- Issue #143: <https://github.com/ardelperal/APAP_WEB/issues/143>
- Issues relacionados: #145 (race write-after-invalidate), #146 (audit denials).
- AGENTS.md §1 (cero SQL en routes), §6 (default-deny), §9 (`log_safe`), §10 (docstrings como contrato).
