[← Back to README](../../README.md)

# auth-dependencies-audit-2026-Q2.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto de la revisión de cada función pública de `app/core/auth_dependencies.py` ejecutada en 2026 Q2, con addenda posteriores para issues #226, #229, slice #420-7 e issue #430.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Funciones públicas y callers de `app/core/auth_dependencies.py`. |
| [Methodology](#methodology) | Procedimiento aplicado para auditar las cuatro funciones. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final de cumplimiento de las reglas. |
| [References](#references) | Spec, design, tasks y PRs relacionados. |

## Scope

| Item | Value |
|---|---|
| Fichero auditado | `app/core/auth_dependencies.py` |
| Líneas auditadas | 142 |
| Funciones públicas | 4 (`get_insforge_client_dep`, `get_current_user_optional`, `return_early_if_response`, `require_authorized_user`) |
| Cross-references | `app/main.py` (middleware + helper `_redirect`), `app/core/session.py` (`read_session`, `session_cookie_name`), `app/core/csrf.py` (PR-5B, planificado) |
| Auditores | `sdd-apply` PR-5A sobre `hardening-2026-q2/slice-5a-audit-doc` desde `staging` (bd8a98e) |
| Fecha | 2026-06-27 |

### Funciones auditadas

### `get_insforge_client_dep()` — línea 40

| Aspecto | Detalle |
|---|---|
| Firma | `def get_insforge_client_dep():` (sin anotación, generator) |
| Retorno | `Iterator[InsForgeClient]` (implícito) |
| Callers | 5 sitios en `app/modules/{animals,entradas,voluntarios}/routes.py`; tests vía `app.dependency_overrides[...]` |
| Cobertura | Indirecta — ejercida por cada test de ruta que use `app.dependency_overrides` |
| Hallazgos | Falta anotación de tipo de retorno (LOW-2); contrato de gestión de recursos correcto |
| Oportunidades de consolidación | Ninguna — responsabilidad única (ciclo de vida del cliente por request) |

### `get_current_user_optional(request: Request) -> dict | None` — línea 68

| Aspecto | Detalle |
|---|---|
| Firma | `def get_current_user_optional(request: Request) -> dict \| None` |
| Retorno | dict del payload de sesión, o `None` si la cookie falta o es inválida |
| Callers | `require_authorized_user` (línea 110), `app/main.py:208` (ruta `/unauthorized`) |
| Cobertura | Cubierta indirectamente vía tests de `require_authorized_user` + test de ruta `/unauthorized` |
| Hallazgos | Ninguno funcional |
| Oportunidades de consolidación | HIGH PRIORITY para PR-5B — el futuro `CsrfMiddleware.dispatch` en `app/core/csrf.py` replicará este patrón exacto de lectura de cookie y decodificación. Extraer `read_session_payload(request) -> dict \| None` y que ambos lo llamen. Rastreado como MEDIUM-1 (la extracción es mayor que un fix de una línea; se ata al finding de "triple duplication" de abajo). |

### `return_early_if_response(value: object) -> Response | None` — línea 83

| Aspecto | Detalle |
|---|---|
| Firma | `def return_early_if_response(value: object) -> Response \| None` |
| Retorno | el valor si es `Response`; en otro caso `None` |
| Callers | `app/main.py:193`, `app/main.py:343`; no usado por rutas de módulo (que aún esperan que `user` sea dict y usan otros patrones) |
| Cobertura | Indirecta (cubierta por tests de ruta que ejercen el auth guard) |
| Hallazgos | MEDIUM-1 — el tipo del parámetro `object` es demasiado amplio. Los únicos callers pasan `Response \| dict`; tighten a `Response \| dict` captura el misuse en tiempo de type-check y hace explícita la intención del helper. Toca los callers en `app/main.py` (2 sitios). |
| Oportunidades de consolidación | Ninguna — helper leaf, responsabilidad única |

### `require_authorized_user(request, payload=Depends(get_current_user_optional)) -> Response | dict` — línea 108

| Aspecto | Detalle |
|---|---|
| Firma | `def require_authorized_user(request: Request, payload: dict \| None = Depends(get_current_user_optional)) -> Response \| dict` |
| Retorno | `RedirectResponse` (sin sesión o sin autorización) o dict del payload (autorizado) |
| Callers | 23 usos en producción repartidos en `app/main.py` (4 sitios), `app/modules/animals/routes.py` (7), `app/modules/entradas/routes.py` (7), `app/modules/voluntarios/routes.py` (5) |
| Cobertura | Directa: `tests/test_auth_dependencies.py::test_require_authorized_user_default_false`, `::test_pre_fix_cookie_redirects_to_unauthorized`. Indirecta: tests de ruta en `tests/test_animals_routes_redirects.py`, `tests/test_entradas_routes.py`, `tests/test_auth_session_is_authorized.py` |
| Hallazgos | Cumple Regla 7: devuelve `RedirectResponse` (no `HTTPException`); default-flip a `False` confirmado (PR-3); docstring ya explica el linaje de Regla 6 + Regla 7 |
| Oportunidades de consolidación | LOW-1 (triple duplication) — el middleware en `app/main.py:147-175` (`protect_user_facing_routes`) TAMBIÉN lee la cookie de sesión, decodifica el payload y comprueba `is_authorized`. Tras PR-5B, `CsrfMiddleware` será una tercera copia de este patrón. Las copias en el middleware no pueden importar esta dependency (corren antes de la dep injection de FastAPI), así que la consolidación debe ser un leaf helper (`read_session_payload(request)`) al que los tres llamen. Rastreado como MEDIUM-2 porque cruza límites de fichero y se beneficia de hacerse junto con `CsrfMiddleware` de PR-5B (el nuevo call site es el motivador más fuerte). |

## Methodology

1. **Lectura** de cada línea de `app/core/auth_dependencies.py` y de los 4 ficheros caller (`app/main.py`, `app/modules/animals/routes.py`, `app/modules/entradas/routes.py`, `app/modules/voluntarios/routes.py`).
2. **codegraph_explore** para análisis de callers cross-file (blast radius por símbolo).
3. **Comprobación de cobertura de tests existente** — lectura de `tests/test_auth_dependencies.py`, `tests/test_auth_session_is_authorized.py`, `tests/test_middleware_is_authorized.py`, `tests/test_animals_routes_redirects.py` para confirmar que el comportamiento de la Regla 7 está pineado.
4. **Static grep audit** — confirmación de que `HTTPException(status_code=302` devuelve 0 coincidencias en `app/`.
5. **Pre-slice form audit** (per round-2 fix `REG-S-2`) — enumeración de todos los `<form method="post">` en `app/templates/`, conteo, mapeo a las rutas handler, confirmación de que ninguno lleva actualmente `<input type="hidden" name="csrf_token">`. Capturado como estado inicial para `tests/test_all_post_forms_have_csrf_input.py` de PR-5B.

### Pre-slice form audit (per round-2 fix REG-S-2)

Grep de `<form method="post">` en `app/templates/`:

| # | Plantilla | Línea | Atributo action | Mapeo al handler |
|---|---|---|---|---|
| 1 | `admin.html` | 19 | `/admin/users` | `app/main.py:366` (`@application.post("/admin/users")`) |
| 2 | `admin.html` | 76 | `/admin/users/{{ u.id }}/deactivate` | `app/main.py:393` (`@application.post("/admin/users/{user_id}/deactivate")`) |
| 3 | `animales/detail.html` | 16 | `/animales/{{ animal.id }}/delete` | `app/modules/animals/routes.py:357` |
| 4 | `animales/form.html` | 20 | `""` (self-submit) | `app/modules/animals/routes.py:144` (create) y `:282` (update) — misma plantilla reutilizada |
| 5 | `entradas/detail.html` | 14 | `/entradas/{{ entrada.id }}/delete` | `app/modules/entradas/routes.py:244` |
| 6 | `entradas/form.html` | 20 | `"{{ form_action }}"` (variable Jinja) | `app/modules/entradas/routes.py:103` (create) y `:192` (update) — misma plantilla reutilizada |
| 7 | `voluntarios/detail.html` | 11 | `/voluntarios/{{ voluntario.id }}/deactivate` | `app/modules/voluntarios/routes.py:177` |
| 8 | `voluntarios/form.html` | 18 | `""` (self-submit) | `app/modules/voluntarios/routes.py:103` |

Conteos: 8 tags `<form method="post">` distintos, **10 handlers POST** (los dos `form.html` se reutilizan para create y update). El "10 forms" de la spec se refiere a handlers, no a tags de formulario. El test parametrizado del audit (PR-5B, T-5B.20) parametrizará sobre los 10 handlers.

Comprobación de cobertura CSRF: grep de `csrf_token` en `app/templates/` devuelve **0 coincidencias** (confirmado). Los 8 tags de formulario son vulnerables a cross-site form submission hasta que PR-5B aterrice.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| HIGH | Sin defensa CSRF en ningún formulario POST | deferred (PR-5B) | Una cookie `apap_session` robada o reusada (p. ej. vía XSS, leak de log) permite a un atacante impersonar al usuario en POSTs a los 10 handlers. Comportamiento actual: `apap_session` y `apap_pkce` llevan `samesite="lax"` (app/main.py:261, :307). Sin validación de token. Mitigación: PR-5B implementa `app/core/csrf.py::CsrfMiddleware`, fija `samesite="strict"`, inyecta `<input type="hidden" name="csrf_token">` en las 8 plantillas de formulario. Spec REQ-AH-5..10. Estado: TRACKED — PR-5B (siguiente slice de este cambio). |
| MEDIUM | Parámetro de `return_early_if_response` tipado como `object`; debería ser `Response \| dict` | deferred (FOLLOW-UP #1) | El helper acepta cualquier valor y solo comprueba `isinstance(value, Response)`. Mitigación: tighten a `Response \| dict`; actualizar los 2 call sites en `app/main.py` para que solo pasen `Response \| dict`. Tighten puro de tipos, sin cambio de comportamiento. Bundle con F-4. |
| MEDIUM | Triple duplicación del patrón "leer cookie de sesión + decodificar payload" | deferred (FOLLOW-UP #2) | El mismo snippet de 4 líneas copy-pasted en tres ubicaciones. Mitigación: extraer leaf helper `read_session_payload(request) -> dict \| None` en `app/core/auth_dependencies.py` (o `app/core/session.py`); que `get_current_user_optional`, `protect_user_facing_routes` y `CsrfMiddleware` lo llamen. Recomendado co-shipped con PR-5B. |
| MEDIUM | Falta anotación de tipo de retorno en `get_insforge_client_dep` | deferred (FOLLOW- #1, bundle con F-2) | El type checker trata el retorno como `Any`. Mitigación: añadir `from collections.abc import Iterator` y anotar como `Iterator[InsForgeClient]`. Cambio de una línea, delta de comportamiento cero. |
| LOW | Helper local `_redirect` en `app/main.py:115` redundante con `RedirectResponse` inline | deferred (DOCUMENTED ONLY) | Mitigación: consolidar en `app/core/redirects.py::redirect(path: str) -> RedirectResponse` e importar desde ambos. Fuera del alcance del Slice 5 (spec §Out of scope lo difiere explícitamente). |
| LOW | Dos llamadas casi idénticas a `RedirectResponse` en `require_authorized_user` | no action | Dos early-return; la legibilidad es OK. Sin acción. Documentado por completitud. |
| LOW | Import legacy `from app.modules.animals.routes import require_authorized_user` en un test | deferred (DOCUMENTED ONLY) | `tests/test_auth_session_is_authorized.py:52` importa desde `app.modules.animals.routes` (camino legacy); el import canónico es `app.core.auth_dependencies`. Mitigación: actualizar import. Limpieza trivial, diferida a un pass de tests-cleanup. |

## Verdict

PASS (con un hallazgo HIGH rastreado para PR-5B). `app/core/auth_dependencies.py` cumple actualmente con todas las reglas en alcance para este audit:

- **Regla 6** — default-deny: `payload.get("is_authorized", False)` confirmado vía `tests/test_auth_dependencies.py::test_require_authorized_user_default_false` (PR-3).
- **Regla 7** — `RedirectResponse`, no `HTTPException`: confirmado vía static grep (`HTTPException(status_code=302` devuelve 0 coincidencias en `app/`) y pineado por el nuevo `tests/test_rule_7_compliance.py` añadido en este PR.
- **SB-3** — `PUBLIC_PATHS` incluye `/auth/callback`: confirmado vía resolución del slice-3 (engram:14531). `/auth/callback` está en `app/main.py:63-70` dentro del conjunto public-paths.

El hallazgo HIGH único (F-1, defensa CSRF ausente) es el alcance explícito de PR-5B, que sigue inmediatamente. Los hallazgos MEDIUM se difieren a follow-up issues numerados que se abrirán tras el merge de PR-5B.

### Addenda

### Issue #226 Addendum — 2026-07-20

**Scope**: extracción estructural del enum `Rol` de `app/core/auth.py` a `app/core/roles.py` libre de dependencias, con actualización de imports en `config.py` y `auth_dependencies.py`.

**Methodology**: análisis de callers/impact con CodeGraph, smoke checks de orden de import, focused auth tests e inspección estática de imports de rol restantes en funciones.

| Severity | Title | Form | Details |
|---|---|---|---|
| INFO | El import lazy previo de `Rol` enmascaraba un ciclo entre `auth.py` y `config.py` | fixed | `Rol` ahora tiene un único módulo home libre de dependencias. |
| INFO | El import lazy de `get_user_by_email` ya no era necesario una vez eliminado el ciclo de roles | fixed | Promovido a import module-level; los focused authorization tests siguen verdes. |

**Verdict**: PASS — no cambió comportamiento de autorización, valor de rol, regla default-deny, cookie, sesión, CSRF ni contrato de logging.

### Issue #229 Addendum — 2026-07-20

**Scope**: deduplicación de la decisión de developer-role compartida por `require_developer_user` y `require_developer_user_redirect`.

**Methodology**: análisis de callers con CodeGraph, focused dependency tests, verificación de denial-log y revisión estática de default-deny y propagación de redirects.

| Severity | Title | Form | Details |
|---|---|---|---|
| INFO | Las dos dependencias públicas repetían la misma decisión de rol y podían divergir | fixed | Un helper privado ahora posee el role check y el denial audit event. |
| INFO | Las señales públicas de fallo difieren intencionadamente | no action | Los wrappers preservan los contratos existentes de 403 y 302 respectivamente. |

**Verdict**: PASS — el acceso de developer sigue default-deny, los redirects upstream se propagan sin cambios y el denial logging continúa exclusivamente vía `log_safe`.

### Slice #420-7 Addendum — 2026-08-05 (auth-dependencies)

**Scope**: mover `app/core/auth_dependencies.py` (9 deps FastAPI, ~419 líneas) a `app/core/di/auth_dependencies_di.py` según el layout §33.3. Reducir el original a un re-export shim. Aplicar el fix §32.P4 sobre `InsForgeError` en `require_authorized_user` en el mismo PR. Refrescar este audit doc y añadir el pin test arquitectónico.

Ficheros cambiados (5 totales — corregido del tally previo de 4):

- Creado: `app/core/di/auth_dependencies_di.py` (443 líneas tras el fix de ciclo §Lazy-import helper; 510 líneas contando líneas en blanco)
- Creado: `tests/test_auth_dependencies_slice.py` (8 átomos tras el backfill de gate-review: átomos 1–7 más átomo 8 fresh-process regression test)
- Modificado: `app/core/auth_dependencies.py` → shim de re-export de 24 líneas tras la compactación del docstring (down from the prior 41 lines; the cycle fix did not require touching the shim)
- Modificado: `tests/test_middleware_is_authorized.py` — actualización de source-pin location (la comprobación default-deny pre-slice vive ahora en el módulo di, no en el cuerpo del shim)
- Modificado: `docs/audits/auth-dependencies-audit-2026-Q2.md` (este addendum)

**Methodology**:

1. CodeGraph caller map de los 9 símbolos: 35 ficheros consumer (corregido del 19 del design — el conteo previo era una muestra parcial; la superficie real incluye `app/core/admin_handlers.py`, `app/core/auth_flow.py`, `app/core/rbac.py`, cada `app/modules/*/routes.py` más 3 `batch_routes.py`, el cuerpo lifespan de `app/main.py` y 16 ficheros de test). El enfoque shim es transparente para todos.
2. AST diff: el cuerpo del shim post-fix es `from app.core.di.auth_dependencies_di import *` + `from app.core.logging import log_safe` + `from app.core.session import read_session_payload` más un docstring de módulo; sin lógica. Los re-exports extra de `log_safe` / `read_session_payload` permiten que los patches `monkeypatch.setattr("app.core.auth_dependencies.log_safe", ...)` de los tests existentes se propaguen a las llamadas del módulo di (el módulo di resuelve estos nombres vía `_shim().<name>` en tiempo de llamada).
3. Comparación de firmas: `inspect.signature()` para cada uno de los 9 nombres coincide byte a byte entre shim y módulo di (átomo 5 del pin test).
4. Revisión §32.P4: identificado el camino de `InsForgeError` sin manejar en `require_authorized_user` → paso de revalidación → diseñado Variante A.
5. Fix DI↔shim cycle (gate correction 1): el previo `from app.core import auth_dependencies as _shim` a nivel de módulo creaba un ciclo order-dependent. Un proceso fresh que importara el módulo di primero disparaba una carga parcial del shim; el `from app.core.di.auth_dependencies_di import *` del shim corría entonces contra el módulo di PARCIAL (los 9 símbolos públicos están definidos DESPUÉS del import shim module-level del módulo di) y el shim terminaba sin sus 9 re-exports consumer-facing. La fix reemplaza el binding module-level con un helper de lookup lazy `_shim()` dentro del módulo di — ver `:func:app.core.di.auth_dependencies_di._shim`. El shim no cambia estructuralmente; solo cambia la estrategia de import del módulo di. El fresh-process regression test `tests/test_auth_dependencies_slice.py::test_shim_exports_resolve_when_di_module_imported_first` pinea el invariante.
6. Lazy-import cycle (#226): documentado en `docs/architecture/decisiones-proyecto.md`; el import module-level desde `app.core.auth` no cambia. El nuevo módulo di ya NO importa el shim a nivel de módulo — busca el shim en tiempo de llamada vía `_shim()` — así que el ciclo module-level previo desaparece. Esta decisión (Opción A en observación de Engram #24065) es la forma canónica para los 11 slices de módulo que siguen.

| Severity | Title | Form | Details |
|---|---|---|---|
| CRITICAL | §32.P4: `InsForgeError` desde `get_user_by_email` escaparía como 500 (issue #294) | fixed | Variante A en el mismo PR — `try/except InsForgeError` envuelve la única llamada `get_user_by_email(client, email)`, emite `log_safe("auth.denied", reason="db_unreachable", user_id=...)`, devuelve `RedirectResponse("/unauthorized", 302)`. El cache NO se envenena (átomo 4 negative guard vía el `call_count` de la fixture `set_cached_auth`). |
| CRITICAL | DI↔shim cycle order-dependent module-level (gate correction 1) | fixed | Un proceso fresh que importara el módulo di primero rompía todos los paths `from app.core.auth_dependencies import <name>` de los consumers con `ImportError`. Reemplazado el module-level `from app.core import auth_dependencies as _shim` del módulo di por un helper de lookup lazy `_shim()`. Shim no cambia estructuralmente. Pineado por el nuevo átomo 8 fresh-process regression test (una invocación `subprocess` que limpia `sys.modules` y luego importa el módulo di primero). |
| INFO | Import module-level desde `app.core.auth` (cycle #226) — convención preexistente | no action | Documentado en `docs/architecture/decisiones-proyecto.md`; sin cambios. |
| INFO | Constraint R04 leak, set completo (gate correction 3) | no action | El átomo 3 actualizado aplica el set completo: (a) sin palabras clave raw de SQL en literales string de código, (b) sin construcción de `InsForgeClient(...)` fuera del único sitio de fallback permitido, (c) sin acceso directo a `app.core.auth_cache` fuera del facade `get_cached_auth` / `set_cached_auth`. Pineado por el átomo 3 con el AST helper `_module_r04_violations`. |
| INFO | Shim de 24 líneas, bien por debajo del cap de 50 líneas (gate correction 4) | no action | Sin nueva entrada `BASELINE` requerida (Regla §21). |
| INFO | Módulo di de 443 líneas (gate correction 4) | no action | Aún dentro del presupuesto de 700 líneas (átomo 6 + Regla §21). |
| INFO | El Protocol `AuthCacheBackend` existe pero el facade module-level `get_cached_auth` / `set_cached_auth` lo bypassea | no action | Deuda preexistente (issue #287); fuera del alcance de este slice. |
| INFO | `app.dependency_overrides[<key>]` sigue funcionando para `get_insforge_client`, `get_insforge_client_dep`, `get_current_user_optional` | no action | El primero viene de `app.main` (sin cambios); los otros dos son re-exportados por el shim con identidad (`shim.<X> is di.<X>`, átomo 2). Sin cambios necesarios. |

**Verdict**: PASS — slice migrado a `app/core/di/`, 9 firmas byte-idénticas (pin test átomo 5), fix §32.P4 en su sitio con negative guard de cache poisoning (pin test átomo 4), ningún import path de consumer roto en ninguno de los dos órdenes de import (pin test átomos 1, 2 y el nuevo átomo 8 fresh-process regression test), los 49 tests existentes pasan sin modificación, addendum del audit doc enviado.

**Fuera de alcance (gate correction 4)**: los 11 slices de módulo listados en `auth-dependencies-audit-2026-Q2.md` §Out of scope (acogidas, adopciones, animals, cesiones, entradas, foster, materiales, salud, sanidad, tasks, voluntarios). Cada uno aterrizará su propio `app/core/di/<module>_di.py` siguiendo el mismo patrón shim de este slice y aplicando el patrón `_shim()` de lazy-import donde el módulo necesite leer helpers del shim legacy.

### Issue #430 Addendum — 2026-08-07

**Scope**: partir las dependencias de session y backend-revalidation desde `app/core/di/auth_dependencies_di.py` a `app/core/di/auth_dependencies_session_di.py` sin cambiar la API pública de los nueve símbolos.

**Methodology**: comparación de identidad de objetos exportados y firmas, ejecución de los tests del slice de auth y Rule 7, escaneo de ambos ficheros DI por transport leaks, y ejecución del suite completo, mutation-sites, CRAP, module-size, Ruff, rules, mypy, coverage y build.

| Severity | Title | Form | Details |
|---|---|---|---|
| INFO | El módulo DI original excedía el techo de 250 mutation-site en 252 | fixed | Split a 124 y 92 sitios; total combinado reducido a 216 y la entrada del mutation baseline fue retirada. |
| INFO | Mover `require_authorized_user` dejaba stale el path del baseline CRAP | fixed | Movido el mismo baseline shrink-only al path del session DI y bajado de 14.05 a 9.01. |
| INFO | La medición de código duplicado es sensible a la versión de Python | no action | Bajado el baseline CI-authoritative jscpd para Python 3.14 de 1.88% a 1.81%; Python 3.11 mide 1.72%. |
| INFO | Los contratos de redirect, default-deny, cache, logging e import-order podían diverger durante la extracción | no action | Pines existentes actualizados para escanear el nuevo seam; todas las aserciones de comportamiento e identidad de objetos pasan. |

**Verdict**: PASS — el split reduce complejidad sin cambiar comportamiento de autenticación, autorización, redirect, logging, cache ni import público.

## References

- Spec: `openspec/changes/hardening-2026-q2/specs/05-auth-hardening/spec.md` (REQ-AH-1..4 cubre este PR; REQ-AH-5..10 cubren PR-5B)
- Design: `openspec/changes/hardening-2026-q2/design.md` §Slice 5 (PR-A subsection)
- Tasks: `openspec/changes/hardening-2026-q2/tasks.md` T-5A.1..6
- Audit relacionado: `docs/audits/xss-audit-2026-Q2.md` (PR-XSS, debe preceder a PR-5B)
- PRs relacionados: PR-3 (Regla 6, mergeada), PR-XSS (XSS audit, ABIERTO #112), PR-7 (TOCTOU, ABIERTO #113)
- Motivación: engram:14518 (audit de seguridad — CSRF defense-in-depth + admin endpoints), engram:14516 (audit de cumplimiento de reglas)
- Resolución SB-3: engram:14531 (design; `/auth/callback` ya está en `PUBLIC_PATHS`)
- AGENTS.md §1 (límite de capas), §5 (validación en servicio), §6 (default-deny), §7 (RedirectResponse), §11 (CRITICAL_HELPERS), §26 (lazy-import justificado), §32.P4 (partial exception handling)
- Issues #226, #229, slice #420-7, #430
