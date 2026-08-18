[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# CSRF defense

Esta página posee la regla §10 de AGENTS verbatim: defensa CSRF por defecto, cobertura de `CsrfMiddleware`, contrato de plantilla y detectores automáticos. La página de seguridad la resume; aquí está el contrato completo.

## Regla 10 — Defensa CSRF por defecto

Toda ruta POST/PUT/DELETE/PATCH debe estar protegida por `CsrfMiddleware` (`app/core/csrf.py`). Toda plantilla de formulario (`templates/`) debe renderizar `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">` en cada `<form method="post">`. El middleware valida el token por el header `X-CSRFToken` (para HTMX/fetch) o por el campo de formulario `csrf_token` (para envíos tradicionales). Las cookies de sesión y PKCE se sirven con `SameSite=Strict` — `Lax` es una regresión.

**Incorrecto** — formulario sin token CSRF

```html
<form method="post" action="/users">
  <input name="email" type="email">
  <button type="submit">Submit</button>
</form>
```

**Correcto** — formulario con token CSRF

```html
<form method="post" action="/users">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <input name="email" type="email">
  <button type="submit">Submit</button>
</form>
```

**Aplicación**: `CsrfMiddleware` devuelve 403 en tiempo de ejecución cuando el token falta o es inválido. `tests/test_all_post_forms_have_csrf_input.py` (10 casos) y `tests/test_csrf_form_enumeration.py` (10 casos) capturan regresiones. Los nuevos detectores `csrf_middleware_registered` y `csrf_samesite_strict` (`scripts/check_rules.py` Detectores 7 y 8) atrapan la eliminación accidental del middleware en la cadena y la regresión accidental a `Lax`.

## Core invariants

- **Cobertura universal**: cada POST/PUT/DELETE/PATCH pasa por `CsrfMiddleware`.
- **Plantillas contractuales**: cada `<form method="post">` lleva el `csrf_token` hidden.
- **Cookies estrictas**: `SameSite=Strict` para sesión y PKCE; `Lax` no es aceptable.
- **Doble vía de envío**: header `X-CSRFToken` (HTMX/fetch) y campo `csrf_token` (formularios).
- **Cierre 403**: el middleware responde 403 sin alcanzarse la lógica de negocio.

## Contributor checklist

- [ ] Cada nueva ruta POST/PUT/DELETE/PATCH pasa por `CsrfMiddleware` (verifique con `csrf_middleware_registered`).
- [ ] Cada nueva plantilla con `<form method="post">` incluye `{{ csrf_token }}` en un campo hidden.
- [ ] Ningún `SameSite=Lax` nuevo en código que firme cookies.
- [ ] Si una ruta acepta HTMX, el handler envía `X-CSRFToken` o el formulario cae en el campo hidden.

## Navigation

Previous: [Logging conventions](logging-conventions.md) | Next: [Security](security.md)
