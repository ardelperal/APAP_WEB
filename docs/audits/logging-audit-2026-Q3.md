[← Back to README](../../README.md)

# logging-audit-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del endurecimiento del envelope de logging (`log_safe` → `LogRecord` → `JsonFormatter`) para corregir el `KeyError` por colisión con atributos reservados de `LogRecord` (#283) y el leakage de la deny-list interna de `JsonFormatter` (#284), ejecutado en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Envelope de logging y sus consumidores. |
| [Methodology](#methodology) | Procedimiento TDD aplicado sobre `log_safe`, `JsonFormatter` y `RedactionFilter`. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del envelope de logging. |
| [References](#references) | Ficheros revisados, pruebas y dashboards. |

## Scope

| Item | Value |
|---|---|
| Feature | Logging envelope — fixes #283 y #284 |
| Issues | #283 (`KeyError` por atributos reservados de `LogRecord`), #284 (leakage de deny-list interna en `JsonFormatter`) |
| Datos sensibles | `email`, `session_token`, `jwt`, `oauth_code`, `pkce_verifier`, `csrf_token`, `pkce_challenge`, `authorization`, `cookie`, `referer`, `ip_address`, `x_forwarded_for`, `dni`, `tel1`, `tel2` (lista cerrada de 15 campos) |
| Ficheros revisados | `app/core/logging.py` (`log_safe`, `JsonFormatter`, `RedactionFilter`, `_stamp_caller_fields`), `tests/test_logging.py`, `tests/test_log_safe_redaction.py`, `tests/test_logging_redaction_adversarial.py`, `tests/migration/test_pii_redaction.py`, `tests/test_csrf_middleware.py`, `tests/test_csrf_rejected_log_event.py`, `tests/test_adopciones.py` |
| Controles principales | Envelope anidado (una sola clave extra `_caller_fields`), `JsonFormatter` con strict allow-list de 11 keys, `RedactionFilter` que recorre `_caller_fields` anidado |
| Fecha | 2026-07-26 |

## Methodology

1. Redacción de la suite RED para `_stamp_caller_fields` (3 casos: redacción, carriage, kwargs vacíos) antes de escribir producción.
2. Redacción de la suite RED parametrizada para 21 atributos reservados de `LogRecord` como kwargs de `log_safe`: ninguno lanza `KeyError` post-refactor.
3. Redacción de la suite RED para `JsonFormatter` con set exacto de claves (3 casos: plain, redacted, exc_info) y redacción anidada.
4. Implementación GREEN: `_stamp_caller_fields`, `log_safe` reescrito, `JsonFormatter` allow-list (11 keys), `RedactionFilter.filter` que recorre `_caller_fields` anidado.
5. Migración de 35 tests existentes que accedían a `record.<field>` como atributo top-level → `record._caller_fields["field"]`.
6. Registro de `_stamp_caller_fields` en `CRITICAL_HELPERS` (cobertura 100%).
7. Verificación de mypy con cero errores en `app/core/logging.py` y `scripts/pytest_plugin/coverage_gate.py`.
8. Verificación de lint (`ruff check .` + `scripts/check_rules.py`) limpio.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| BLOCKER | `log_safe("e", module=…)` causaba `KeyError: "Attempt to overwrite 'module' in LogRecord"` | fixed | Nuevo helper `_stamp_caller_fields` que recolecta todos los kwargs del caller en un único dict, pasado como valor de la clave extra `"_caller_fields"`. Ningún kwarg colisiona con atributos reservados de `LogRecord` por construcción. |
| BLOCKER | `JsonFormatter` era deny-list: cualquier clave de `record.__dict__` no presente en la deny-list de 7 se emitía, filtrando ~15 atributos internos al JSON stdout | fixed | `JsonFormatter` usa strict allow-list de 11 keys: `{timestamp, level, logger, message, module, func, line, event, _caller_fields, exc_info, exc_text, stack_info}`. Ningún atributo interno de `LogRecord` escapa. |
| CRITICAL | `exc_info=True` pasado a `log_safe` no llegaba a la maquinaria de logging porque se incluía en `_caller_fields` en vez de pasarse como kwarg a `logger.info()` | fixed | Se extrae `exc_info` de kwargs antes de construir `_caller_fields`; se pasa explícitamente a `logger.info(exc_info=...)`. `record.exc_info` y `record.exc_text` se emiten cuando están presentes. |
| CRITICAL | La closed-list de 15 campos PII no recorría `_caller_fields` anidado; `RedactionFilter` solo mutaba `record.__dict__` top-level | fixed | `RedactionFilter.filter` aplica un segundo paso: `record.__dict__.get("_caller_fields")` y, si es dict, itera sus claves y reemplaza si coincide con la lista cerrada normalizada. |
| INFO | `event` aparecía en `_caller_fields` y como clave top-level extraída por la allow-list — duplicación | deferred | La allow-list de `JsonFormatter` extrae `event` de `_caller_fields` y la emite como `event` top-level. La clave `event` dentro de `_caller_fields` está permitida (es caller-supplied, no interna de `LogRecord`). Aceptado por diseño. |
| MEDIUM | Consultas de dashboard que hacen grep sobre `payload["event"]` top-level siguen funcionando (la allow-list la emite); las consultas a `payload._caller_fields.event` también | deferred | La migración de dashboards no requiere acción del operador. Aceptado por diseño. |

## Verdict

PASS: el envelope de logging resuelve los dos defectos originales (#283 `KeyError` y #284 leakage de la deny-list) con un único mecanismo: `_caller_fields` anidado como única clave extra más strict allow-list en `JsonFormatter`. La lista cerrada de 15 campos PII sigue operativa con defensa en profundidad dentro del dict anidado. `exc_info` ahora sí llega a stdout. Cobertura total 89.37%, `CRITICAL_HELPERS` al 100%, mypy sin errores, lint limpio.

### Migración para dashboards

Los dashboards que hacen consultas tipo `$.event` en el JSON stdout siguen funcionando — la allow-list emite `event` como clave top-level. No se requiere acción de operador en el código de la aplicación.

Los dashboards que hacían consultas a `payload["_caller_fields"]["event"]` también funcionan — esa clave sigue presente en el payload anidado.

Si un dashboard hacía consulta a `payload["event"]` dentro del JSON (no como clave top-level), necesita actualizarse a `$._caller_fields.event` o `$.event` (top-level).

## References

- `app/core/logging.py` (`log_safe`, `JsonFormatter`, `RedactionFilter`, `_stamp_caller_fields`).
- `tests/test_logging.py`, `tests/test_log_safe_redaction.py`, `tests/test_logging_redaction_adversarial.py`.
- `tests/migration/test_pii_redaction.py`, `tests/test_csrf_middleware.py`, `tests/test_csrf_rejected_log_event.py`.
- `tests/test_adopciones.py` (test que valida la nueva forma del envelope).
- AGENTS.md §9 (`log_safe` como única vía de logging), §11 (`CRITICAL_HELPERS` con `_stamp_caller_fields`).
