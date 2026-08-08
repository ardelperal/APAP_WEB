[← Back to README](../../README.md)

# issue-204-middleware-extraction-audit-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del refactor de extracción de la cadena de autenticación fuera de `app/main.py` (issue #204), sin cambio de comportamiento, ejecutado en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Orden del middleware de FastAPI y contratos de la cadena de auth. |
| [Methodology](#methodology) | Procedimiento aplicado al refactor. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final de la extracción y corrección posterior. |
| [References](#references) | Ficheros revisados, plan de rollback y runbook. |

## Scope

| In-scope | Out-of-scope |
|---|---|

| Cadena de middleware FastAPI (`CsrfMiddleware` → `protect_user_facing_routes` → `UADetectionMiddleware`) | Handler-level `Depends(require_authorized_user)` (sin cambios, sigue importando de `app/core/auth_dependencies.py`) |
| Contratos de auth-redirect (302 a `/login`, 302 a `/unauthorized`) para rutas protegidas | Handlers del flujo OAuth (`/auth/google`, `/auth/callback`, `/logout`) — se quedan en `app/main.py` porque son glue de aplicación, no rutas de "módulo de dominio" |
| Invariante default-deny `payload.get("is_authorized", False)` | Módulos de dominio (`/animales`, `/voluntarios`, etc.) — sin cambios, sin SQL tocado |
| `Settings.csrf_enabled` feature flag (Slice 5) | Nuevas dependencias (sin cambio en `pyproject.toml` en este PR) |
| `UADetectionMiddleware` sigue disparándose antes del middleware de auth (contrato arquitectónico, ver comentario en `app/core/middleware.py:296-302`) | Plantillas / assets estáticos |

| Item | Value |
|---|---|
| Audit slice | Issue `#204` (refactor — sin cambio de comportamiento) |
| Branch | `refactor/issue-204-auth-extraction` |
| PR | pendiente (`ardelperal/APAP_WEB`) |
| Fecha | 2026-07-22 |
| Auditor | AI-assisted audit driven by `code-review-expert` lens + full local validation (`pytest`, `ruff`, `mypy`, `scripts/check_rules.py`, `scripts/check_module_size.py`) + coverage gate |
| Motivación | El audit del 2026-07-18 recomendó extraer la setup de la cadena de auth fuera de `app/main.py` para reducir un factory de 689 líneas a una cáscara fina y centralizar el registro junto a las definiciones de middleware existentes (`CsrfMiddleware`, `UADetectionMiddleware`). La extracción es un **refactor**: sin cambio de comportamiento. Esta auditoría certifica que los contratos que la cadena de auth enforce siguen idénticos tras el move y que no se introdujo nueva superficie de ataque |

## Methodology

1. **Diff del runtime stack pre-/post-refactor**: introspección tanto del `app/main.py::create_app` pre-refactor (checked out at `origin/main`) como de la versión post-refactor de la misma llamada. Comparación de los descriptores de middleware en `app.user_middleware` y los sets `(method, path)` en `app.routes` — igualdad exacta requerida.
2. **Full pytest run**: `python -m pytest -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py --cov=app --cov-report=json --cov-fail-under=80 -q`. Coverage floor cumplido (89.18%); `CRITICAL_HELPERS` gate PASS a 21/21 helpers @100%.
3. **Rule linter**: `python scripts/check_rules.py .` — Detector 7 (`csrf_middleware_registered`) re-escopeado para verificar tanto `app/main.py` (que llama a `install_auth_middleware`) como `app/core/middleware.py` (que registra `CsrfMiddleware`). Detector 8 (`csrf_samesite_strict`) y 6 (`print_in_app`) sin cambios; ambos siguen verdes.
4. **Type/static checks**: `ruff check .` limpio; `python -m mypy` limpio.
5. **Nueva superficie TDD**: `tests/test_middleware_install.py` y `tests/test_routes_registry.py` ejercen la nueva estructura con introspección de `app.user_middleware` y `app.routes` (la misma superficie de introspección que el `tests/test_middleware.py::test_ua_detection_middleware_is_registered_in_app` existente).
6. **Contrato auth end-to-end**: `tests/test_public_paths.py` (4 átomos) y `tests/test_middleware_is_authorized.py` (átomos funcionales) siguen pasando sin reescribir sus aserciones de comportamiento. Solo se actualizaron source-pins para seguir el move `app/main.py` → `app/core/middleware.py` (ver §Source-pin tracking abajo).

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| LOW | Scope del Detector 7 (informativo) | fixed | `scripts/check_rules.py::_check_csrf_middleware_registered` antes recorría `app/main.py` para el literal `CsrfMiddleware`. Tras #204, la referencia de clase vive en `app/core/middleware.py::install_auth_middleware`. El detector se actualizó para recorrer AMBOS ficheros: `app/main.py` debe llamar a `install_auth_middleware` (la superficie de bootstrapping), `app/core/middleware.py` debe referenciar `CsrfMiddleware` (el registro real). Soltar cualquier mitad es una regresión. La comprobación de dos ficheros es estructuralmente equivalente a la antigua de un fichero (misma ventana de regresión cubierta); sin cambio operator-facing. |

### Source-pin tracking (informativo)

Dos meta-tests preexistentes pineaban la ubicación en el código del substring default-deny y de la llamada `read_session_payload`:

- `tests/test_middleware_is_authorized.py::test_middleware_default_false_en_fuente` — lee `app/main.py`, afirma que el literal `payload.get("is_authorized", False)` está presente. **Actualizado** para leer `app/core/middleware.py`.
- `tests/test_middleware_is_authorized.py::test_solo_dos_call_sites_en_app` — cuenta las líneas `if not payload.get("is_authorized"` en `app/`, afirma que el set de ficheros es `{app/main.py, app/core/auth_dependencies.py}`. **Actualizado** para afirmar `{app/core/middleware.py, app/core/auth_dependencies.py}`. El invariante de count (2) se preserva.
- `tests/test_auth_dependencies.py::test_middleware_uses_read_session_payload` — lee `app/main.py`, afirma el literal `read_session_payload(`. **Actualizado** para leer `app/core/middleware.py`.

El **comportamiento** pineado por cada test (default-deny; sin snippet inline; la llamada existe) es sin cambios; solo el FICHERO que el test lee se actualizó para seguir el move del refactor. Este es el resultado correcto: los source-pinning tests son anti-patterns para refactors, y actualizarlos para seguir el código movido es requerido cuando el move es el objetivo explícito del issue. Cada test actualizado lleva un comentario de migración en el diff explicando el cambio.

Ningún otro test o plantilla se modificó.

## Verdict

PASS: issue #204 es una extracción que preserva el comportamiento. El orden de la cadena de auth en una request (`UADetection → protect → Csrf → routes`) no cambia. El contrato default-deny de `is_authorized` se preserva. El feature-flag guard de `CsrfMiddleware` se preserva. El contrato de redirect del auth-flow (302 a `/login`, 302 a `/unauthorized`) no cambia. Cada test de public-path y PII-path sigue pasando sin reescribir las aserciones. Los dos source-pinning tests siguen la ubicación movida con el invariante de count intacto.

No se introdujo nueva superficie de ataque. No hay nuevas dependencias. No hay nuevas env vars.

## Corrección (2026-07-22): fallo del test de prefix de routes-registry en FastAPI >=0.137

La run de CI `29953269866` (job `test`) falló los 8 átomos parametrizados de `tests/test_routes_registry.py::test_register_routers_includes_each_module_router` (`/animales`, `/entradas`, `/voluntarios`, `/sanidad`, `/adopciones`, `/acogidas`, `/cesiones`, `/materiales`) sobre una app FastAPI fresh. La pre-push local pasó solo porque el venv dev pineó `fastapi==0.133.1`; CI resuelve `fastapi>=0.115` y pip trae `fastapi 0.137.2`, que cambió `app.include_router(...)` (PR [fastapi/fastapi#15745](https://github.com/fastapi/fastapi/pull/15745)) para almacenar un wrapper `_IncludedRouter` en `app.routes` que no expone `.path` ni `.methods`. El set comprehension `{r.path for r in app.routes if hasattr(r, 'path')}` descartó entonces todas las rutas del registro, dejando solo los defaults de FastAPI (`/openapi.json`, `/docs`, `/redoc`) — ninguno encaja con los prefixos afirmados.

Fix en `tests/test_routes_registry.py:58-87, 229-271`: el helper `_extract_method_path_pairs` y el walker inline del path-set en `test_register_routers_includes_each_module_router` ahora recurren a `_IncludedRouter.original_router.routes` (las rutas hijas del `APIRouter` envuelto, cuyo `.path` ya está compuesto). `app/routes_registry.py` no cambia — el registro es correcto; el test dependía de una forma plana de `app.routes` que FastAPI 0.137 dejó de devolver deliberadamente (per discusión upstream [fastapi/fastapi#15791](https://github.com/fastapi/fastapi/discussions/15791)). Verificado localmente contra venvs limpios en `fastapi 0.133.1` (2505 passed, 0 failed) y `fastapi 0.137.2` (2503 passed, 0 failed), más `ruff`, `mypy`, `scripts/check_rules.py`, `scripts/check_module_size.py` limpios. Gate `CRITICAL_HELPERS` 21/21 @100% en ambos. Nueva URL de run de CI en el body del commit.

### Evidencia de re-ejecución del Test Plan

- `pytest … --cov-fail-under=80`: **2517 passed, 2 skipped, 2 deselected**, cobertura **89.18%** (por encima del suelo 80%). Gate `CRITICAL_HELPERS` 21/21 @100% PASS.
- `ruff check .`: limpio.
- `python -m mypy`: limpio (92 ficheros).
- `python scripts/check_rules.py .`: limpio (Detector 7 nueva comprobación de dos ficheros + Detectores 6/8 sin cambios).
- `python scripts/check_module_size.py`: limpio. `app/main.py` reducido de 689 → 544 líneas (~21% de reducción). Nuevo `app/core/middleware.py` 197 líneas (bajo el presupuesto de 700 líneas); `app/routes_registry.py` 62 líneas.

## Verdict (refactor + corrección)

PASS: el refactor (#204) preserva comportamiento y reduce `app/main.py` de 689 a 544 líneas. La corrección posterior (FastAPI 0.137 compatibility) mantiene el contrato del registry sin tocar el código de producción.

## Rollback plan

El refactor es estructuralmente aditivo (módulos nuevos + comportamiento preservado en tiempo de import). Rollback es `git revert <merge-sha>` — sin migración de base de datos, sin cambio de env-var, sin acción del operador requerida. El `app/main.py` pre-refactor es totalmente self-contained (ningún módulo nuevo dependía de su definición inline), así que el rollback no puede romper ningún módulo que no hubiera optado por los nuevos imports durante la breve ventana que el PR estuvo abierto.

## References

- `app/main.py` (689 → 544 líneas).
- `app/core/middleware.py` (197 líneas, nuevo).
- `app/routes_registry.py` (62 líneas, nuevo).
- `tests/test_middleware_install.py`, `tests/test_routes_registry.py`.
- `tests/test_public_paths.py`, `tests/test_middleware_is_authorized.py`, `tests/test_auth_dependencies.py` (source-pins actualizados).
- `scripts/check_rules.py` (Detector 7 re-escopeado a dos ficheros).
- Issue #204: <https://github.com/ardelperal/APAP_WEB/issues/204>
- PRs relacionados: [fastapi/fastapi#15745](https://github.com/fastapi/fastapi/pull/15745), [fastapi/fastapi#15791](https://github.com/fastapi/fastapi/discussions/15791).
- CI run URL `29953269866` (job `test`).
- AGENTS.md §6 (default-deny), §21 (módulo ≤700 líneas), §28 (route handlers ≤50 líneas).
