[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Security

Esta página posee las reglas §6 y §29 de AGENTS verbatim, junto con resúmenes de las reglas §9 (logging), §10 (CSRF) y §11 (CRITICAL_HELPERS). Las páginas dedicadas a CSRF, logging y codegraph cubren el contrato completo.

## Regla 6 — Los defaults de seguridad deniegan, no permiten

Cuando lea un flag de sesión o payload, use como default el valor más restrictivo. Un campo ausente debe tratarse como la opción más segura.

**Incorrecto** — flag ausente concede acceso

```python
if not payload.get("is_authorized", True):
    redirect("/unauthorized")
```

**Correcto** — flag ausente deniega acceso

```python
if not payload.get("is_authorized", False):
    redirect("/unauthorized")
```

## Regla 11 — Gate de cobertura para `CRITICAL_HELPERS`

Los helpers en `app/` (funciones que matchean el regex `_row_to_*` + la lista explícita `{_redirect, _render_form, _is_duplicate_error, _validate_create_params, _build_insert_params}`) deben tener 100% de cobertura de líneas. Si añade un nuevo helper que contiene lógica de producto testeable, añádalo a `CRITICAL_HELPERS` en el mismo PR.

**Aplicación**: `scripts/pytest_plugin/coverage_gate.py` lee `coverage.json` tras pytest y falla el build si alguna entrada de `CRITICAL_HELPERS` tiene <100% de cobertura de líneas. El auto-descubrimiento de helpers vía el regex `_row_to_*` captura nuevos helpers que cumplen la convención; la lista explícita es para helpers sin regex.

## Regla 29 — Cache de auth: backend in-process único + scope por worker (issues #262, #287)

El cache de auth que respalda `require_authorized_user` (`app/core/auth_cache.py`, issue original #143) soporta solo el backend `in_process`. `APAP_AUTH_CACHE_BACKEND` queda como guard de compatibilidad: `in_process` se acepta; `redis` y todo valor desconocido fallan la validación de settings durante el arranque de la aplicación, antes de servirse cualquier request. Cada proceso worker de uvicorn posee su propio cache en memoria, así que `invalidate_auth(email)` solo alcanza al worker que la llamó y la peor ventana de staleness cross-worker es `APAP_AUTH_CACHE_TTL_SECONDS` (default 300s). El deploy actual en Coolify se confirmó el 2026-07-25 como una réplica de la aplicación usando el `CMD` del Dockerfile con Uvicorn y sin override `--workers`, así que corre un solo worker hoy. Antes de aumentar la cuenta de workers o réplicas, fije `APAP_AUTH_CACHE_TTL_SECONDS=0` para revocación inmediata al costo de un `SELECT` de autorización extra por request autenticado. Los pasos completos de deploy, verificación y rollback viven en `docs/runbooks/auth-cache-multi-worker.md`.

## Resumen de reglas conectadas

| Regla | Página | Resumen |
|---|---|---|
| §6 | este doc | Defaults deniegan, no permiten |
| §9 | [logging-conventions.md](logging-conventions.md) | `log_safe` solo en `app/`; doce campos redactados |
| §10 | [csrf-defense.md](csrf-defense.md) | `CsrfMiddleware` + `csrf_token` en cada form post + `SameSite=Strict` |
| §11 | este doc | 100% de cobertura sobre `CRITICAL_HELPERS` |
| §29 | este doc | Cache de auth in-process; un worker = un cache |

## Core invariants

- **Default-deny en flags de seguridad**: cualquier `payload.get(key, False)` resuelve a denegado cuando la clave falta.
- **CSRF cobertura universal**: cada POST/PUT/DELETE/PATCH pasa por `CsrfMiddleware`; cada `<form method="post">` lleva `csrf_token`.
- **Log redaction automática**: doce campos PII/secret nunca aparecen en logs.
- **CRITICAL_HELPERS 100%**: la lista explícita más el regex `_row_to_*` cierra la cobertura de helpers de producto.
- **Un worker = un cache**: aumentar workers exige `APAP_AUTH_CACHE_TTL_SECONDS=0` y runbook de rollback.

## Contributor checklist

- [ ] Cada flag de auth nuevo defaultea a `False` o al valor más restrictivo.
- [ ] Ningún nuevo POST/PUT/DELETE/PATCH se sirve sin pasar por `CsrfMiddleware`.
- [ ] Cada `<form method="post">` que renderice incluye `{{ csrf_token }}`.
- [ ] Los nuevos helpers de producto se añaden a `CRITICAL_HELPERS` con su test al 100%.
- [ ] Si aumenta workers o réplicas, fija `APAP_AUTH_CACHE_TTL_SECONDS=0` y enlaza el runbook.

## Navigation

Previous: [Architecture](architecture.md) | Next: [CSRF defense](csrf-defense.md)
