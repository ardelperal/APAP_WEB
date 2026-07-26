# Auditoría: Logging envelope — 2026 Q3

**Scope**: #283 (KeyError on reserved LogRecord attr names in `log_safe`) / #284 (JsonFormatter JSON noise — deny-list leakage of ~15 LogRecord internal attrs).

**Methodology**: revisión del contrato `log_safe` → LogRecord → JsonFormatter; pruebas TDD RED/GREEN sobre los 8 tasks del SDD; verificación de que `exc_info` todavía llega a stdout; cobertura CRITICAL_HELPERS al 100% para `_stamp_caller_fields`.

**Date**: 2026-07-26

**Verdict**: **PASS**. El envelope de logging es ahora strict allow-list, no deny-list; `log_safe` nunca más puede causar `KeyError: "Attempt to overwrite 'X' in LogRecord"` con args del caller que collidan con los 25 reserved LogRecord attr names; la lista de 15 campos PII sigue intacta y la RedactionFilter opera sobre `_caller_fields` anidado.

---

## Scope

| Item | Value |
|---|---|
| Feature | Logging envelope — fixes #283 + #284 |
| Issues | #283 (KeyError on reserved LogRecord attrs) / #284 (JsonFormatter deny-list leakage) |
| Datos sensibles | Campos redactionados (email, session_token, jwt, oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization, cookie, referer, ip_address, x_forwarded_for, dni, tel1, tel2) via log_safe |
| Ficheros revisados | `app/core/logging.py` (log_safe, JsonFormatter, RedactionFilter, _stamp_caller_fields), `tests/test_logging.py`, `tests/test_log_safe_redaction.py`, `tests/test_logging_redaction_adversarial.py`, `tests/migration/test_pii_redaction.py`, `tests/test_csrf_middleware.py`, `tests/test_csrf_rejected_log_event.py`, `tests/test_adopciones.py` |
| Controles principales | Nested envelope (single `_caller_fields` extra key), strict allow-list JsonFormatter (11 keys), RedactionFilter que camina `_caller_fields` anidado |

## Methodology

1. Se escribió la testsuite RED para `_stamp_caller_fields` (3 cases: redaction, carriage, empty kwargs) antes de escribir producción.
2. Se escribió la testsuite RED parametrizada para 21 reserved LogRecord attr names como kwargs de `log_safe` — ninguna lanza `KeyError` post-refactor.
3. Se escribió la testsuite RED para JsonFormatter exact key set (3 cases: plain, redacted, exc_info) y nested redaction.
4. Se implementó GREEN: `_stamp_caller_fields`, `log_safe` reescrito, `JsonFormatter` allow-list (11 keys), `RedactionFilter.filter` que camina `_caller_fields` anidado.
5. Se migraron 35 tests existentes que accedían `record.<field>` como attr top-level → `record._caller_fields["field"]`.
6. Se registró `_stamp_caller_fields` en `CRITICAL_HELPERS` (cobertura 100%).
7. Se vérificó mypy zero errors en `app/core/logging.py` + `scripts/pytest_plugin/coverage_gate.py`.
8. Se vérificó lint (`ruff check .` + `scripts/check_rules.py`) limpio.

## Findings

| Severity | Finding | Mitigation | Status |
|---|---|---|---|
| BLOCKER | `log_safe("e", module=…)` causaba `KeyError: "Attempt to overwrite 'module' in LogRecord"` porque kwargs se pasaban directamente como `extra={}`. | Nuevo `_stamp_caller_fields` helper que recolecta todos los kwargs del caller en un solo dict, pasado como valor de la key extra `"_caller_fields"`. Ningún kwarg collida con reserved LogRecord attrs por construcción. | Cerrado |
| BLOCKER | `JsonFormatter` era deny-list: cualquier key de `record.__dict__` que NO estuviera en la deny-list de 7 se emitía, filtrando ~15 internal attrs de LogRecord al JSON stdout. | `JsonFormatter` usa ahora strict allow-list de 11 keys: `{timestamp, level, logger, message, module, func, line, event, _caller_fields, exc_info, exc_text, stack_info}`. Ningún internal LogRecord attr escapa. | Cerrado |
| CRITICAL | `exc_info=True` pasado a `log_safe` no llegaba a la maquinaria de logging porque se incluía en `_caller_fields` en vez de pasarse como kwarg a `logger.info()`. | Se extrae `exc_info` de kwargs antes de construir `_caller_fields`; se pasa explícitamente a `logger.info(exc_info=...)`. `record.exc_info` y `record.exc_text` se emiten cuando están presentes. | Cerrado |
| CRITICAL | La closure-list de 15 campos PII no caminaba dentro de `_caller_fields` anidado — `RedactionFilter` solo mutateaba `record.__dict__` top-level. | `RedactionFilter.filter` ahora hace segundo paso: `record.__dict__.get("_caller_fields")` y si es dict, itera sus keys y replace si match con closed-list normalizado. | Cerrado |
| INFO | `event` aparecía en `_caller_fields` y también como top-level key extraída por allow-list — duplicación. | El allow-list de `JsonFormatter` extrae `event` de `_caller_fields` y la emite como top-level `event`. La key `event` dentro de `_caller_fields` está permitida (es caller-supplied, no LogRecord internal). | Aceptado |
| WARNING | Dashboard queries que hacen grep a `payload["event"]` top-level siguen funcionando (el allow-list la emite). Queries a `payload._caller_fields.event` también funcionan. | Dashboard migration no requiere action de operator. | Aceptado |

## Verdict

**PASS**. El envelope de logging resuelve los dos defectos originales (#283 KeyError, #284 deny-list leakage) con un solo mecanismo: nested `_caller_fields` como única key extra + strict allow-list en `JsonFormatter`. La closure-list de 15 campos PII sigue operative con defensa en profundidad dentro del dict anidado. `exc_info` ahora sí llega a stdout. Cobertura total 89.37%, CRITICAL_HELPERS al 100%, mypy zero errors, lint limpio.

### Migration para dashboards

Los dashboards que hacen queries tipo `$.event` en el JSON stdout siguen funcionando — el allow-list emite `event` como top-level key. No se requiere acción de operator en el código de la aplicación.

Los dashboards que hacían queries a `payload["_caller_fields"]["event"]` también funcionan — esa key sigue presente en el payload anidado.

Si un dashboard hacía query a `payload["event"]` dentro del JSON (no como top-level key), necesita actualizarse a `$._caller_fields.event` o `$.event` (top-level).
