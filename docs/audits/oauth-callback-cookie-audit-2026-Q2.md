[← Back to README](../../README.md)

# oauth-callback-cookie-audit-2026-Q2.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del estudio sobre el atributo `SameSite` de la cookie `apap_pkce` emitida por `/login` y consumida por `/auth/callback` durante el flujo OAuth en producción durante 2026 Q2.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Cookie `apap_pkce` y el callback OAuth de Google/LocalBackend. |
| [Methodology](#methodology) | Procedimiento aplicado para reproducir y verificar el bug. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del contrato `SameSite` de `apap_pkce`. |
| [References](#references) | Pruebas, logs de Coolify y PRs de cierre. |

## Scope

| Item | Value |
|---|---|
| Cookie auditada | `apap_pkce` (PKCE `code_verifier`) |
| Rutas en alcance | `/login` (emisión), `/auth/callback` (consumo) |
| Proveedor OAuth | Google / LocalBackend |
| Navegador de referencia | Chrome en producción |
| Periodo de análisis | 2026 Q2 |

Fuera de alcance: la cookie de sesión `apap_session` (mantiene `SameSite=Strict` por contrato y no se ve afectada), el endpoint `/auth/google` (no emite ni consume cookies PKCE) y los tokens de portador de la API interna.

## Methodology

1. Revisión del código de `app/main.py` para localizar el atributo `SameSite` aplicado a la cookie `apap_pkce` en el momento de la emisión.
2. Inspección de logs de Coolify para reproducir la secuencia de redirecciones observada en el navegador.
3. Captura de navegador del error `ERR_TOO_MANY_REDIRECTS` en `https://apap.romancaba.com/auth/callback?oauth_code=...`.
4. Diseño de una prueba regresiva que afirme el atributo `SameSite=Lax` sobre `apap_pkce` tras el fix.
5. Ejecución de la prueba regresiva y verificación del flujo OAuth completo (`/login` → Google → `/auth/callback` → `/`).

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| HIGH | `apap_pkce` emitida con `SameSite=Strict` | fixed | Bloqueaba el callback OAuth porque Chrome no enviaba la cookie en la navegación GET cross-site de vuelta desde Google/LocalBackend. El callback no encontraba el `code_verifier`, redirigía a `/login` y producía un bucle `ERR_TOO_MANY_REDIRECTS`. Cambio aplicado a `SameSite=Lax`. |

### Detalle del hallazgo

`apap_pkce` se emitía en `/login` con `SameSite=Strict`. En producción, Chrome no envía esa cookie en la vuelta OAuth a `/auth/callback` porque la navegación de retorno es una GET de primer nivel entre sitios. El callback no encontraba el `code_verifier`, redirigía a `/login` y se generaba el bucle `ERR_TOO_MANY_REDIRECTS`.

La corrección cambia `apap_pkce` a `SameSite=Lax`. Mantiene la protección frente a subpeticiones y formularios cross-site, pero permite la navegación GET del callback OAuth sin perder el `code_verifier`.

## Verdict

PASS: la cookie `apap_pkce` usa `SameSite=Lax` y la cookie de sesión `apap_session` mantiene `SameSite=Strict` por separado, de modo que el callback OAuth funciona y la defensa CSRF por cookie sigue intacta en el resto del flujo.

## References

- Captura de usuario: Chrome muestra `ERR_TOO_MANY_REDIRECTS` en `https://apap.romancaba.com/auth/callback?oauth_code=...`.
- Logs de Coolify: secuencia repetida `/auth/callback?... -> 302` y `/login -> 302`, con nuevas peticiones al proveedor OAuth.
- Prueba regresiva: `tests/test_auth_flow.py::test_login_apap_pkce_cookie_uses_samesite_lax_for_oauth_callback`.
- AGENTS.md §10 (contrato CSRF y SameSite).
