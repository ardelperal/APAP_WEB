[← Back to README](../../README.md)

# security-headers-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del corte que añade el middleware de cabeceras de seguridad HTTP (CSP, X-Frame-Options, nosniff, Referrer-Policy, HSTS) para cerrar el finding §32.P1 Perimeter Blindness del audit del 2026-07-25 (issue #276), ejecutado en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Cabeceras de seguridad HTTP y orden del middleware. |
| [Methodology](#methodology) | Procedimiento TDD aplicado al middleware. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del endurecimiento del borde HTTP. |
| [References](#references) | Ficheros modificados, propuesta, spec y design. |

## Scope

| Item | Value |
|---|---|
| Audit slice | `feat/issue-276-security-headers` |
| Branch | `issue-276-security-headers` (cortada de `main`) |
| PR | pendiente de apertura |
| Fecha | 2026-07-27 |
| Auditor | AI-assisted audit (TDD + code review) |
| Motivación | Issue #276 — ausencia de cabeceras de seguridad HTTP en toda la superficie de la aplicación. Era un finding §32.P1 (Perimeter Blindness): el endurecimiento se concentraba en mecanismos internos de auth mientras el borde HTTP quedaba sin protección |
| Spec | Observaciones de Engram #21823 (propuesta) + #21824 (spec, REQ-1..REQ-12) |
| Design | Observación de Engram #21825 (design D1..D9) |

### Ficheros modificados

| Fichero | Resumen |
|---|---|
| `app/core/middleware.py` | Añadido `SecurityHeadersMiddleware` + `install_security_headers_middleware`; cableado como outermost en `install_auth_middleware` |
| `tests/test_security_headers_middleware.py` | 19 aserciones cubriendo los 7 REQs |
| `docs/audits/security-headers-2026-Q3.md` | Este documento |

### Cadena de middleware (post-orden)

`add_middleware` de Starlette inserta en posición 0, así que el último middleware registrado es el más externo (alcanza la respuesta primero):

| Orden | Middleware | Notas |
|---|---|---|
| 1 (outermost) | `SecurityHeadersMiddleware` | issue #276 — añade 5 cabeceras defense-in-depth |
| 2 | `UADetectionMiddleware` | Selección de plantilla por UA (issue #157) |
| 3 | `protect_user_facing_routes` | Auth guard (issue #204) |
| 4 | `CsrfMiddleware` | Validación de token CSRF (issue #143) |
| 5 | `RateLimitMiddleware` | Rate limiting (issue #286) |
| 6 (innermost) | Handlers de ruta | Lógica de dominio |

Design D3: como `SecurityHeadersMiddleware` es el más externo, ve **todas** las formas de respuesta, incluidas las 403 de CSRF y las 429 de RateLimit.

## Methodology

1. TDD (Strict TDD, RED → GREEN): tests fallidos primero (`tests/test_security_headers_middleware.py`), confirmación de 19 fallos, implementación del middleware para hacerlos pasar.
2. Descubrimiento iterativo de CSP: el CSP inicial (`default-src 'self'`) provocó un warning de consola del navegador sobre URIs `data:` que no encajan con `'self'`. Se ajustó `img-src` a `'self' data:` para permitir URIs inline de tipo data (logos, sprites SVG) sin abrir fetch cross-origin. Ninguna otra directiva se relajó; cada relajación tiene una razón documentada.
3. Test del gate de HSTS: verificación de que la cabecera `Strict-Transport-Security` se emite con `settings.debug=False` y se omite con `settings.debug=True`. El camino dev-mode se probó con monkeypatching de `get_settings()`.
4. Verificación del orden del middleware: test explícito (`test_csrf_403_carries_security_headers`) que hace POST a `/animales` con un token CSRF incorrecto y afirma que las 5 cabeceras de seguridad están presentes en la respuesta 403, confirmando el contrato de outermost.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| INFO | `img-src` tuvo que relajarse de `'self'` a `'self' data:` | deferred | El CSP inicial provocaba el warning `Refused to load image 'data:image/svg+xml,...' because it violates the following Content Security Policy directive: "img-src 'self'"`. Causa: las plantillas del proyecto embeben sprites SVG con URIs `data:`. Resolución: relajar `img-src` para permitir SVGs y data URIs sin abrir imágenes cross-origin arbitrarias. Ninguna otra directiva se relajó. `default-src 'self'` se mantiene como fetch por defecto; `script-src 'self'` se mantiene como script por defecto (sin `unsafe-inline`, sin `unsafe-eval`). |

## Verdict

PASS: la implementación cumple los 7 requisitos (REQ-1..REQ-7) y aporta endurecimiento HTTP defense-in-depth que antes faltaba. El baseline de CSP requirió una relajación puntual (`img-src 'self' data:`) para acomodar el patrón de sprites SVG del proyecto; el resto de directivas permanece en el ajuste más estricto.

## References

| Recurso | Referencia |
|---|---|
| Propuesta | Engram #21823 |
| Spec | Engram #21824 (REQ-1..REQ-12) |
| Design | Engram #21825 (D1..D9) |
| Tasks | Engram #21826 (T1..T8) |
| Tests | `tests/test_security_headers_middleware.py` (19 aserciones) |
| Finding §32.P1 | Perimeter Blindness — el endurecimiento de auth se concentraba en mecanismos internos; el borde HTTP estaba desprotegido |
| AGENTS.md §32.P1 (Perimeter Blindness) | Criterio de revisión cumplido |

### Estado de los criterios de aceptación

| Criterio | Estado |
|---|---|
| [REQ-1] `X-Content-Type-Options: nosniff` en cada respuesta | 5 aserciones pasan |
| [REQ-2] `X-Frame-Options: DENY` en cada respuesta | 5 aserciones pasan |
| [REQ-3] `Referrer-Policy: strict-origin-when-cross-origin` en cada respuesta | 3 aserciones pasan |
| [REQ-4] `Content-Security-Policy` baseline en cada respuesta | 3 aserciones pasan |
| [REQ-5] `Strict-Transport-Security` en producción (`debug=False`) | 2 aserciones pasan |
| [REQ-6] `Strict-Transport-Security` omitido en development (`debug=True`) | 1 aserción documenta el contrato |
| [REQ-7] Todas las cabeceras presentes en CSRF 403 (orden outermost) | 1 aserción pasa |
| [Audit doc] `docs/audits/security-headers-2026-Q3.md` con scope y verdict | este documento |
