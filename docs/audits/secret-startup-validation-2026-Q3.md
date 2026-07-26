# Auditoría: Startup Secret Validation — 2026 Q3

**Scope**: SECRET-01 / issue #275 — validación de `APAP_SESSION_SECRET` y
`APAP_INSFORGE_SERVICE_KEY` en el arranque de la aplicación, rechazando el
placeholder published y secretos menores de 32 caracteres antes de cualquier
conexión a InsForge.

**Methodology**: revisión del flujo lifespan → `_validate_secrets` →
`StartupConfigError`; verificación de que `InsForgeClient` nunca se construye
con configuración inválida; comprobación de que `log_safe` se emite antes del
raise sin incluir el valor del secreto; cobertura de tests de las 7 variantes
de validación; verificación del by-pass `debug=True`.

**Date**: 2026-07-26

**Verdict**: **PASS**. La validación de secretos vive en la capa de
configuración, se ejecuta antes de cualquier llamada de red, emite logs
estructurados antes de raise, y es ignorada solo con `debug=True` (gate
explícito que no aplica en producción). La класса `StartupConfigError`
nunca hace echo del valor del secreto. Cobertura completa de los 7 casos
de validación y del contrato de log. El patrón §32.P2 queda cerrado.

---

## Scope

| Item | Value |
|---|---|
| Feature | SECRET-01 — validación de secretos en startup |
| Issue | #275 |
| Datos sensibles | `APAP_SESSION_SECRET` (HMAC cookie), `APAP_INSFORGE_SERVICE_KEY` (service key) |
| Ficheros revisados | `app/core/config.py`, `app/main.py`, `tests/test_startup_config_validation.py`, `tests/test_lifespan.py`, `scripts/pytest_plugin/coverage_gate.py` |
| Controles principales | `_validate_secrets` called before `InsForgeClient`, `log_safe` before raise, `StartupConfigError` no-echo, `debug=True` bypass, `_validate_secrets` in CRITICAL_HELPERS |

## Methodology

1. Se revisó `_validate_secrets` para verificar que valida en orden:
   `insforge_service_key == ""` → raise; `session_secret == placeholder` →
   raise; `len(session_secret) < 32` → raise; `debug=True` → return.
2. Se verificó que `log_safe("startup.config_invalid", env_var=..., reason=...)`
   se llama ANTES de cada raise, sin pasar el valor del secreto.
3. Se verificó que `StartupConfigError` lleva `env_var` y `reason` como
   atributos, y que el mensaje no hace echo del valor del secreto.
4. Se verificó que la lifespan llama `_validate_secrets` DESPUÉS de
   `configure_logging` y ANTES de `InsForgeClient(...)`, con prueba
   de regresión que patching `InsForgeClient` y confirmando que no se
   construye cuando la validación falla.
5. Se confirmó que `debug=True` (default `False`) es el gate de by-pass,
   verificado en tests.
6. Se añadió `_validate_secrets` a `CRITICAL_HELPERS` (regla §11) en el
   mismo PR.
7. Se escribió runbook operator-facing y este documento de auditoría.

## Findings

| Severity | Finding | Mitigation | Status |
|---|---|---|---|
| CRITICAL | El `session_secret` se inicializaba con un valor placeholder publicado en el repositorio. Un lector del repo podía forjar cookies de sesión para cualquier email/rol. | `_validate_secrets` rechaza el placeholder en producción; `StartupConfigError` propagates antes de construir `InsForgeClient`. | Cerrado |
| CRITICAL | `insforge_service_key` vacío no bloqueaba el arranque. Privileged SQL calls se hacían sin autenticación. | `_validate_secrets` rechaza `insforge_service_key == ""` antes de cualquier conexión. | Cerrado |
| CRITICAL | No había validación de longitud mínima para `session_secret`. Un secreto corto (e.g. 8 chars) era aceptable. | `_validate_secrets` requiere `len >= 32`; `secrets.token_urlsafe(32)` en el runbook genera el mínimo seguro. | Cerrado |
| WARNING | No había test de regresión que probara que `InsForgeClient` no se construye cuando la validación falla. | `test_lifespan_validates_secrets_before_constructing_insforge_client` patchea `InsForgeClient` y afirma que no se llama. | Cerrado |
| WARNING | El log de validación podía incluir accidentalmente el valor del secreto si un developer pasaba el secreto a `log_safe`. | El contrato de `_validate_secrets`明确规定 never passes the secret value; `test_log_safe_payload_omits_secret_value` prueba el contrato. | Cerrado |

## Verdict

**PASS**. La validación de secretos en startup queda alineada con las reglas del proyecto: validación en la capa de configuración (no en routes), `log_safe` como único punto de logging, `StartupConfigError` con mensaje seguro, `debug=True` como gate de dev, y tests de regresión que prueban tanto la lógica de validación como el orden de llamada en el lifespan. El riesgo residual es que un operador que active `APAP_DEBUG=true` en producción obtiene el mismo comportamiento inseguro que antes; el runbook documenta que esto es incorrecto y el default es `False` (default deny, §6). La auditoría referencia §32.P2 como el anti-patrón cerrado.
