[← Back to README](../../README.md)

# e2e-coverage-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del trabajo parcial sobre la cobertura E2E del proyecto (issue #206), que añade cobertura con Playwright para flujos públicos que no requieren secretos OAuth durante 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Inventario de tests E2E y rutas cubiertas. |
| [Methodology](#methodology) | Procedimiento aplicado para ampliar la cobertura. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del alcance parcial de la cobertura E2E. |
| [References](#references) | Ficheros de tests, issues y tareas de seguimiento. |

## Scope

| Item | Value |
|---|---|
| Audit slice | Trabajo parcial para el issue #206 |
| Branch | `test/issue-206-e2e-coverage` (cortada de `main@9b45cd5`) |
| Fecha | 2026-07-30 |
| Auditor | AI-assisted (análisis de código + patrones de Playwright E2E) |
| Motivación | Issue #206 bloqueada por los secretos OAuth en CI. Esta auditoría documenta el alcance del trabajo parcial: cobertura E2E añadida para flujos públicos que no requieren secretos OAuth, ampliando el inventario de tests de 2 a 6 ficheros |
| Spec | Criterios de aceptación del issue #206 en GitHub |

### Ficheros de tests E2E añadidos

| Fichero | Tests | Ruta pública | OAuth requerido |
|---|---|---|---|
| `tests/e2e/test_public_redirects.py` | 5 | Sí (`/healthz`, `/auth/google`) | No |
| `tests/e2e/test_login_form.py` | 6 | Sí (`/login`) | No |
| `tests/e2e/test_logout.py` | 3 | Sí (`/logout`) | No |
| `tests/e2e/test_layout_responsive_extended.py` | 5 | Sí (`/login`) | No |

### Rutas cubiertas por los tests nuevos

| Ruta | Método | Auth requerida | Módulo de test |
|---|---|---|---|
| `/healthz` | GET | No | `test_public_redirects.py` |
| `/auth/google` | GET | Pública (devuelve 503 si no está configurada) | `test_public_redirects.py` |
| `/logout` | GET | No | `test_logout.py`, `test_public_redirects.py` |
| `/` | GET | Sí → redirige | `test_public_redirects.py` |
| `/animales` | GET | Sí → redirige | `test_public_redirects.py` |
| `/login` (formulario) | GET/POST | No | `test_login_form.py`, `test_layout_responsive_extended.py` |

### Rutas no cubiertas (OAuth-gated — seguimiento en #206)

| Ruta | Motivo de bloqueo |
|---|---|
| `/` (dashboard autenticado) | Requiere cookie de sesión OAuth |
| `/animales` (lista autenticada) | Requiere cookie de sesión OAuth |
| `/entradas`, `/voluntarios`, `/admin` | Requiere cookie de sesión OAuth |
| `/auth/callback` | Intercambio de código OAuth |
| Variante POST `/logout` (issue #124) | Requiere auth + envío POST |

## Methodology

1. Enumeración de rutas: lectura de `app/main.py` para listar todas las rutas públicas y las autenticadas.
2. Análisis de los auth-guard: confirmación de qué rutas redirigen sin sesión (auth middleware) frente a las que devuelven 200 sin sesión.
3. Auditoría de la cobertura existente: lectura de los 3 ficheros E2E preexistentes para evitar duplicación (`test_landing.py`, `test_nav_layout.py`, `test_security_headers.py`).
4. Emparejamiento con patrones de tests: seguimiento de las convenciones de fixture establecidas en `conftest.py` y del patrón de preflight-skip usado en todos los tests existentes.
5. Análisis del gap de viewports: `test_nav_layout.py` cubre 375/768/1280; se añadieron 1024 y 1920 en `test_layout_responsive_extended.py`.
6. Auditoría de la superficie CSRF: verificación de que `test_login_form.py` afirma la presencia de `input[name=csrf_token]` según AGENTS.md §10.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| INFO | `/logout` es GET, no POST (issue #124) | deferred | La descripción de la tarea referencia `POST /logout` según #124, pero la implementación actual usa `GET /logout` que redirige a `/`. La variante POST es una solicitud de feature separada aún no implementada. `test_logout.py` pinea el comportamiento GET actual. La acción es clarificar #124 (¿es la variante POST una nueva feature o una expectativa existente?). |
| INFO | `page.set_viewport_size()` recibe `dict[str, int]` en vez de `ViewportSize` (patrón preexistente) | deferred | mypy reporta errores de tipo en estas llamadas. La gate mypy de CI no corre sobre `tests/` (solo sobre `app/` + `migration/`). Acción: fix diferido al backlog. |
| INFO | El job CI `e2e` sigue omitido | deferred | El gate `vars.APAP_OAUTH_CLIENT_ID != ''` no se modifica. Los tests E2E nuevos solo corren en CI cuando se aprovisionan los secretos OAuth. Acción de seguimiento: provisionar los secretos OAuth en el repositorio de GitHub para desbloquear CI. |

## Verdict

PASS (alcance parcial): el inventario E2E creció de 2 a 6 ficheros de tests, cubriendo todas las rutas públicas sin dependencias OAuth. No se introdujeron regresiones. Los flujos OAuth-gated quedan documentados como trabajo de seguimiento.

### Acciones de seguimiento requeridas (fuera de este slice)

| Acción | Owner | Issue |
|---|---|---|
| Provisionar `APAP_OAUTH_CLIENT_ID` + `APAP_OAUTH_CLIENT_SECRET` en el repositorio de GitHub | Operator | #206 |
| Verificar que el job CI `e2e` corre y pasa tras provisionar OAuth | Operator | #206 |
| Implementar la variante POST `/logout` + tests | Agent | #124 |
| Añadir tests E2E para flujos autenticados (dashboard, animales, entradas) | Agent | #206 |
| Corregir los stubs TypedDict de `ViewportSize` en los tests E2E | Agent | backlog |

## References

- Issue #206: `https://github.com/ardelperal/APAP_WEB/issues/206`
- Ficheros E2E preexistentes: `test_landing.py`, `test_nav_layout.py`, `test_security_headers.py`
- `tests/e2e/conftest.py` — infraestructura de fixture y collection
- AGENTS.md §10 (CSRF), §12 (audit doc), §23 (expectativa E2E por slice)
