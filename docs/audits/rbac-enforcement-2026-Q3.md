# Auditoría: enforcement de roles en write routes — 2026 Q3

**Scope**: fix #144 — el RBAC era binario en la práctica: los roles `reader` y `key_user` declarados en `app/core/auth.py::Rol` existían en el enum, pero **ninguna ruta** los aplicaba. Un usuario con rol `reader` podía hacer POST/PUT/PATCH/DELETE en animales, acogidas, cesiones, entradas, batch de entradas, casas de acogida, asignación de casas y voluntarios.

**Method**: code review de las 44 rutas declaradas en `app/modules/*/routes.py` (incluyendo `app/modules/entradas/batch_routes.py` y `app/modules/foster/assignment_routes.py`); codegraph_explore para fijar el blast radius de `require_authorized_user` antes de añadir `require_writer_user`; TDD estricto (rojo → verde → refactor).

**Date**: 2026-07-04

**Verdict**: **PASS**. `reader` queda explícitamente read-only en todas las write routes de los 7 módulos de dominio. Cambio de rol surte efecto dentro del TTL del per-request auth cache de #143 (default 300s, configurable vía `APAP_AUTH_CACHE_TTL_SECONDS`).

---

## Scope

| Item | Value |
|---|---|
| Fix | #144 — RBAC binario en la práctica (P1) |
| Ficheros de producción | `app/core/config.py` (nuevo `writer_rols` property), `app/core/auth_dependencies.py` (nuevo `require_writer_user`), los 7 módulos `app/modules/*/routes.py` + `app/modules/entradas/batch_routes.py` + `app/modules/foster/assignment_routes.py` (cambio de dep en 20 write routes) |
| Cross-references | `app/main.py` (rutas `/admin/*` se mantienen con `require_authorized_user` + check inline de `rol == "developer"`: developer es más restrictivo que writer, no cambia), `tests/conftest.py::auth_reval_rows` (sin cambios: `rol` default sigue siendo `"key_user"`) |
| Tabla | `usuarios_autorizados` (sin cambios de schema) |
| Roles afectados | `reader` (denegado en writes), `developer` / `admin` / `key_user` (sin cambios — siguen pasando) |

## Methodology

1. **codegraph_explore** (obligatorio, primero) sobre `Rol`, `require_authorized_user`, `VALID_ROLES`, `return_early_if_response`, y los 19 call sites de `require_authorized_user` — para confirmar el patrón exacto que la nueva `require_writer_user` debe componer y para identificar todas las write routes candidatas.
2. **Code review** de las 44 declaraciones `@router.*` (incluyendo `app/modules/entradas/batch_routes.py` y `app/modules/foster/assignment_routes.py`) y clasificación por verbo HTTP. Resultado del inventario:

   | Módulo | Write routes (POST/PUT/PATCH/DELETE) | Read routes (GET) |
   |---|---|---|
   | `app/modules/animals/routes.py` | 3 (`""` create, `"/{id}/update"`, `"/{id}/delete"`) | 4 (list, new form, detail, edit form) |
   | `app/modules/acogidas/routes.py` | 4 (`""` create, `"/{id}/update"`, `"/{id}/close"`, `"/{id}/delete"`) | 4 (list, new form, detail, edit form) |
   | `app/modules/cesiones/routes.py` | 1 (`""` create) | 1 (new form) |
   | `app/modules/entradas/routes.py` | 3 (`""` create, `"/{id}/update"`, `"/{id}/delete"`) | 3 (list, new form, detail, edit form — el form se cuenta en detail/edit) |
   | `app/modules/entradas/batch_routes.py` | 3 (`""` stage, `"/{id}/commit"`, `"/{id}/cancel"`) | 2 (new form, preview) |
   | `app/modules/foster/routes.py` | 3 (`""` create, `"/{id}/update"`, `"/{id}/delete"`) | 3 (list, new form, detail, edit form) |
   | `app/modules/foster/assignment_routes.py` | 1 (`"/{id}/asignar"` submit) | 2 (form, overrides list) |
   | `app/modules/voluntarios/routes.py` | 2 (`""` create, `"/{id}/deactivate"`) | 3 (list, new form, detail) |
   | **Total** | **20** | **22** |

3. **Diseño** (siguiendo AGENTS.md regla 6 — default-deny, regla 1 — cero duplicación, regla 4 — fuente única del dominio):
   - **Nueva dep `require_writer_user`** en `app/core/auth_dependencies.py`. Compone sobre `require_authorized_user` (NO re-implementa la revalidación per-request de #143: la cache TTL y el `invalidate_auth` siguen funcionando). Si el upstream devuelve `RedirectResponse`, lo propaga sin tocar lógica de auth (helper `return_early_if_response`). Si devuelve dict, mira `rol` y emite `HTTPException(403, detail="Permisos insuficientes para escribir.")` cuando el rol no está en `Settings.writer_rols`.
   - **`Settings.writer_rols`** property que deriva del enum `Rol` (no hardcoded) — `frozenset({Rol.DEVELOPER.value, Rol.ADMIN.value, Rol.KEY_USER.value})`. `reader` queda explícitamente excluido. La importación de `Rol` es **perezosa dentro del property** (comentario `noqa: PLC0415`) porque `app/core/auth.py` ya importa `Settings`, así que un `from app.core.auth import Rol` a nivel de módulo cerraría un ciclo de import. Esto preserva la regla 4 sin crear un ciclo.
   - **Aplicación a write routes**: cambio de `Depends(require_authorized_user)` → `Depends(require_writer_user)` en las 20 rutas POST/PUT/PATCH/DELETE listadas arriba. Las GET quedan con `require_authorized_user` (la lectura sigue permitida a cualquier usuario activo, incluyendo readers).
   - **Excepción documentada**: las 3 rutas admin en `app/main.py` (`/admin`, `/admin/users`, `/admin/users/{id}/deactivate`) usan `require_authorized_user` + check inline `if current_user.get("rol") != "developer"`. NO se cambian: developer es más restrictivo que writer (writer = developer ∪ admin ∪ key_user), así que el inline check sigue siendo correcto. Una revisión futura podría extraerlas a una `require_developer_user` paralela, pero queda fuera del scope de #144.

4. **TDD estricto** (rojo → verde → refactor):
   - **9 atoms** en `tests/test_auth_dependencies.py`: parametrizado `test_require_writer_user_allows_writer_roles` (3 casos: developer, admin, key_user), `test_require_writer_user_rejects_reader` (el caso P1), `test_require_writer_user_rejects_missing_rol_default_deny`, `test_require_writer_user_rejects_unknown_rol_default_deny`, `test_require_writer_user_propagates_unauthorized_redirect` (no rompe el flujo cuando el upstream ya redirigió a /login), `test_require_writer_user_propagates_unauthorized_redirect_when_deactivated` (idem para /unauthorized), `test_settings_writer_rols_is_derived_from_rol_enum` (regla 4).
   - **6 atoms** de integración por módulo en `tests/test_animals_routes.py` (parametrizado sobre create/update/delete), `tests/test_voluntarios_routes.py` (create + deactivate), `tests/test_cesiones_routes.py` (create). Cada uno prueba que `reader` → 403 SIN que la query de dominio correspondiente llegue al cliente InsForge (assertion `not any("UPDATE/INSERT INTO <table>" in q for q in spy.captured_queries)`), más una clase `auth_reval_rol = "reader"` en el spy para que la revalidación de #143 devuelva el rol del cookie.
   - **Sanity de los roles permitidos**: los tests existentes que loguean con `key_user` (`_login_as_key_user` por módulo) siguen pasando — regresión cero sobre la superficie autenticada.

5. **Verificación local**: `python -m pytest -W error::DeprecationWarning` (1467 passed, +15 vs baseline 1452), `ruff check .` (limpio), `python scripts/check_rules.py app` (limpio), `python -m build` (OK), `scripts/pytest_plugin/coverage_gate.py` (13 helpers críticos a 100%).

---

## Findings

### Pre-fix — P1 (CRÍTICO)

- **Rol declarado pero no aplicado**: `Rol.READER` existía en el enum (regla 4 — fuente única), pero **ningún handler** consultaba `rol` antes de aceptar una mutación. Las únicas comprobaciones de rol eran las 3 inline en `app/main.py` para `/admin/*`, restringidas a `developer`. Un usuario con `reader` podía hacer POST en animales/acogidas/cesiones/entradas/foster/voluntarios exactamente igual que un `key_user`. El RBAC era **binario en la práctica**: activo = puede escribir, inactivo = no puede escribir, sin importar el rol.
- **Violación de la regla 2 del baseline web** (todo rol declarado debe aplicarse en la capa de rutas): la regla fue introducida precisamente porque éste es el patrón que la originó. La auditoría externa del 2026-06-30 ya marcó que la presencia de `reader` en el enum sin un enforcement correspondiente era una bomba de tiempo.

### Post-fix — P3 (aceptados, no resueltos)

- **Multi-worker cache de auth** (carry-over de #143): cada proceso mantiene su propia copia del auth cache; un cambio de rol en el worker A no invalida la del worker B hasta que su TTL lapse o se reinicie (deploy). Tradeoff documentado en `docs/audits/auth-revalidation-2026-Q3.md`. Aceptable dentro del orden de magnitud de minutos; no resuelto por #144.
- **403 vs redirect a `/unauthorized`**: se eligió `HTTPException(403)` porque `/unauthorized` está reservado para "sesión no autorizada" (otro contexto: cookie pre-fix, usuario desactivado por un developer). Mezclar ambos significados confundiría a operadores y a Sentry. Si en el futuro se quiere una página HTML para el 403 (más amable que el JSON por defecto de FastAPI), se puede registrar un exception handler global; queda fuera del scope de #144.
- **Rutas `/admin/*` en `app/main.py` mantienen `require_authorized_user` + check inline de developer**: hoy es funcionalmente equivalente a una `require_developer_user` que NO existe como dep. Una refactorización posterior podría extraerla para simetría con `require_writer_user`, pero no es scope de #144 (developer es más restrictivo que writer, el inline check no se rompe).
- **Foster assignment_routes (`asignar_submit`)**: hoy no tiene restricción de developer, solo de authorized_user. Es writer (puede mutar una `foster_capacity_overrides` con override de capacidad), así que pasa a `require_writer_user`. Si en el futuro el equipo decide que la asignación de animales con override debe ser solo developer, se podría cambiar a una `require_developer_user` paralela — pero ese es un debate de producto, no de enforcement del RBAC ya declarado.

---

## Cross-references

- `docs/audits/auth-revalidation-2026-Q3.md` — la auditoría de #143. `require_writer_user` se apoya en la revalidación per-request que esa PR introdujo: si un developer desactiva a un reader vía `/admin/users/{id}/deactivate`, la revocación toma efecto dentro de los `auth_cache_ttl_seconds` (default 300s) sin esperar a que expire la cookie (7 días).
- `app/core/auth.py::Rol` — enum fuente de verdad (regla 4). `writer_rols` deriva de aquí.
- `app/main.py::admin_*` — rutas developer-only; se mantienen tal cual porque developer ⊂ writer.
- `tests/conftest.py::auth_reval_rows` — helper compartido para que los spies de test respondan la query de revalidación. Sin cambios de contrato: el default sigue siendo `key_user`.

## Verdict

**PASS**. El RBAC binario se cierra: `writer_rols = {developer, admin, key_user}` en `Settings`, derivado del enum `Rol` (regla 4, sin literales duplicados). Aplicado vía `require_writer_user` a las 20 write routes de los 8 ficheros de rutas (`animals`, `acogidas`, `cesiones`, `entradas`, `entradas/batch_routes`, `foster`, `foster/assignment_routes`, `voluntarios`). `reader` → 403 antes de cualquier SQL de dominio. Cambio de rol surte efecto dentro del TTL del per-request auth cache de #143 (default 300s).