# Auditoría OAuth callback cookie — 2026 Q2

**Alcance**: cookie `apap_pkce` emitida en `/login` y consumida en `/auth/callback`.
**Metodología**: revisión de código, revisión de logs de Coolify y prueba regresiva del atributo `SameSite`.
**Veredicto**: **PASS con corrección aplicada** — `apap_pkce` debe usar `SameSite=Lax`, no `Strict`, porque el callback OAuth vuelve desde Google/InsForge mediante una navegación GET de primer nivel entre sitios.

## Hallazgo

| Severidad | Ubicación | Descripción | Resolución |
|---|---|---|---|
| HIGH | `app/main.py` (`/login`) | `apap_pkce` se emitía con `SameSite=Strict`. En producción, Chrome no envía esa cookie en la vuelta OAuth a `/auth/callback`, por lo que el callback no encuentra el `code_verifier`, redirige a `/login` y se genera un bucle `ERR_TOO_MANY_REDIRECTS`. | Cambiar `apap_pkce` a `SameSite=Lax`. Mantiene protección frente a subpeticiones y formularios cross-site, pero permite la navegación GET de callback OAuth. |

## Evidencia

- Captura de usuario: Chrome muestra `ERR_TOO_MANY_REDIRECTS` en `https://apap.romancaba.com/auth/callback?insforge_code=...`.
- Logs de Coolify: secuencia repetida `/auth/callback?... -> 302` y `/login -> 302`, con nuevas peticiones al proveedor OAuth.
- Prueba regresiva: `tests/test_auth_flow.py::test_login_apap_pkce_cookie_uses_samesite_lax_for_oauth_callback`.

## Criterio de aceptación

1. `/login` debe emitir `apap_pkce` con `SameSite=Lax`.
2. `/auth/callback` debe poder leer el verificador PKCE tras la vuelta OAuth.
3. Tras completar el intercambio OAuth, la aplicación debe redirigir una sola vez a `/` y mostrar la página principal.
4. La cookie de sesión `apap_session` mantiene `SameSite=Strict`.
