[← Back to README](../../README.md)

# secret-startup-validation-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del estudio de validación de secretos en el arranque (SECRET-01 / issue #275), que rechaza `APAP_SESSION_SECRET` con valor placeholder publicado y secretos de longitud inferior a 32 caracteres, además de `APAP_INSFORGE_SERVICE_KEY` vacío, antes de cualquier conexión a LocalBackend, ejecutado en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Validación de secretos en el arranque de la aplicación. |
| [Methodology](#methodology) | Procedimiento aplicado sobre el lifespan y la configuración. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final de la validación en startup. |
| [References](#references) | Ficheros revisados, pruebas y runbook. |

## Scope

| Item | Value |
|---|---|
| Feature | SECRET-01 — validación de secretos en startup |
| Issue | #275 |
| Datos sensibles | `APAP_SESSION_SECRET` (HMAC cookie), `APAP_INSFORGE_SERVICE_KEY` (service key) |
| Ficheros revisados | `app/core/config.py`, `app/main.py`, `tests/test_startup_config_validation.py`, `tests/test_lifespan.py`, `scripts/pytest_plugin/coverage_gate.py` |
| Controles principales | `_validate_secrets` invocado antes de `LocalBackendClient`, `log_safe` antes de raise, `StartupConfigError` no-echo, by-pass `debug=True`, `_validate_secrets` en `CRITICAL_HELPERS` |
| Fecha | 2026-07-26 |

Fuera de alcance: el ciclo de vida de la cookie `apap_session` (gestionado por `app/core/session.py`), la validación de tokens OAuth (gestionada por `app/core/auth.py`) y la rotación operativa de secretos (cubierta por runbook).

## Methodology

1. Revisión de `_validate_secrets` para verificar que valida en orden: `local_backend_service_key == ""` → raise; `session_secret == placeholder` → raise; `len(session_secret) < 32` → raise; `debug=True` → return.
2. Verificación de que `log_safe("startup.config_invalid", env_var=..., reason=...)` se llama antes de cada raise, sin pasar el valor del secreto.
3. Verificación de que `StartupConfigError` lleva `env_var` y `reason` como atributos, y de que el mensaje no hace eco del valor del secreto.
4. Verificación de que la lifespan llama a `_validate_secrets` después de `configure_logging` y antes de `LocalBackendClient(...)`, con prueba de regresión que parchea `LocalBackendClient` y confirma que no se construye cuando la validación falla.
5. Confirmación de que `debug=True` (default `False`) es el gate de by-pass, verificado en tests.
6. Adición de `_validate_secrets` a `CRITICAL_HELPERS` (AGENTS.md §11) en el mismo PR.
7. Redacción del runbook operator-facing y de este documento de auditoría.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| CRITICAL | `session_secret` inicializado con un valor placeholder publicado en el repositorio | fixed | Un lector del repo podía forjar cookies de sesión para cualquier email y rol. `_validate_secrets` rechaza el placeholder en producción; `StartupConfigError` se propaga antes de construir `LocalBackendClient`. |
| CRITICAL | `local_backend_service_key` vacío no bloqueaba el arranque | fixed | Las llamadas SQL privilegiadas se hacían sin autenticación. `_validate_secrets` rechaza `local_backend_service_key == ""` antes de cualquier conexión. |
| CRITICAL | Sin validación de longitud mínima para `session_secret` | fixed | Un secreto corto (p. ej. 8 caracteres) era aceptable. `_validate_secrets` exige `len >= 32`; `secrets.token_urlsafe(32)` en el runbook genera el mínimo seguro. |
| MEDIUM | Sin test de regresión que probara que `LocalBackendClient` no se construye cuando la validación falla | fixed | `test_lifespan_validates_secrets_before_constructing_local_backend_client` parchea `LocalBackendClient` y afirma que no se llama. |
| MEDIUM | El log de validación podía incluir accidentalmente el valor del secreto | fixed | El contrato de `_validate_secrets` prohíbe pasar el valor del secreto; `test_log_safe_payload_omits_secret_value` prueba el contrato. |

## Verdict

PASS: la validación de secretos queda alineada con las reglas del proyecto. La validación vive en la capa de configuración, se ejecuta antes de cualquier llamada de red, emite logs estructurados antes de raise y solo se ignora con `debug=True` (gate explícito que no aplica en producción). La clase `StartupConfigError` nunca hace eco del valor del secreto. La cobertura cubre los siete casos de validación y el contrato de log. El anti-patrón §32.P2 queda cerrado.

Riesgo residual: si un operador activa `APAP_DEBUG=true` en producción, obtiene el mismo comportamiento inseguro que antes; el runbook documenta que esto es incorrecto y el default es `False` (default-deny, AGENTS.md §6).

## References

- `app/core/config.py` (`_validate_secrets`, `StartupConfigError`).
- `app/main.py` (lifespan: orden de llamadas).
- `tests/test_startup_config_validation.py`.
- `tests/test_lifespan.py`.
- `scripts/pytest_plugin/coverage_gate.py` (registro de `_validate_secrets` en `CRITICAL_HELPERS`).
- Runbook operator-facing (rotación y longitud mínima de secretos).
- AGENTS.md §6 (default-deny), §9 (`log_safe`), §11 (`CRITICAL_HELPERS`), §32.P2 (anti-patrón cerrado).
