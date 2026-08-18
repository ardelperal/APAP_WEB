[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Logging conventions

Esta página posee la regla §9 de AGENTS verbatim: `log_safe()` es la única vía permitida para emitir logs dentro de `app/`. El detector APAP003 y el detector `print_in_app` lo pinean en CI.

## Regla 9 — `log_safe()` es la única llamada de logging permitida en `app/`

Toda ruta de código bajo `app/` que quiera emitir un log DEBE pasar por `log_safe(event, **fields)` desde `app.core.logging`. Las llamadas directas a `logging.getLogger(__name__).{info,warning,error,debug,critical,exception}(...)` Y `print(...)` están prohibidas en `app/`. La lista de redacción (doce campos cerrados) elimina automáticamente `email, session_token, jwt, oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization, cookie, referer, ip_address, x_forwarded_for` de los payloads de log.

**Incorrecto** — logger crudo o print

```python
logger.info(f"user {user_id} did X")
print(f"failed: {error}")
```

**Correcto** — `log_safe`

```python
log_safe("user.did_x", user_id=user_id, action="X")
```

**Aplicación**: el detector APAP003 (`scripts/check_rules.py` Detector 5) prohíbe las llamadas encadenadas `logger.*` en `app/`. El nuevo detector `print_in_app` (Detector 6) prohíbe `print(...)` en `app/`. Ejecute vía `make check-rules`. `app/core/logging.py` es la única ruta excluida (posee el wrapper).

## Core invariants

- **Único wrapper**: solo `log_safe` puede emitir logs en `app/`. `logger.*` y `print(...)` fallan en CI.
- **Redacción automática**: doce campos PII/secret se redactan sin acción del llamante.
- **Una exclusión legítima**: `app/core/logging.py` es la única ruta que importa `logging` y define el wrapper.

## Contributor checklist

- [ ] Cualquier log nuevo va por `log_safe("event.name", **kwargs)` con kwargs nombrados, no f-strings.
- [ ] No se añadió `import logging` ni `print(...)` a un módulo nuevo en `app/`.
- [ ] Si un detector APAP003 marca un falso positivo, documéntelo en `.check_rulesignore` con justificación.

## Navigation

Previous: [Codebase Guide](../CODEBASE-GUIDE.md) | Next: [Security](security.md)
