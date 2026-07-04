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

**PASS**. La revocación de acceso es ahora operativa en ≤ 5 minutos (TTL configurable; 0 = inmediato). Superset del comportamiento anterior (P1 de fidelidad, `docs/proceso.md §0`): todas las rutas autenticadas siguen funcionando, pero la revocación ya no espera hasta 7 días.
