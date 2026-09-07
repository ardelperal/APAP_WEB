[← Back to README](../../README.md)

# rawsql-auth-gate-audit-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the security fix that closes the unauthenticated ``POST /api/database/advance/rawsql`` surface in the LocalBackend compatibility app (issue #680). The fix replaces the open SQL-execution endpoint with a default-deny handler that requires ``Authorization: Bearer <APAP_RAWSQL_AUTH_TOKEN>`` and validates the secret with ``hmac.compare_digest`` (constant-time comparison) before touching the executor. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del cierre del endpoint ``/api/database/advance/rawsql`` sin autenticación, ejecutada en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Cierre del handler sin auth y contrato del token compartido. |
| [Methodology](#methodology) | Default-deny en startup + helper de validación + tests unitarios e integración. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del endpoint y de la superficie atacada. |
| [References](#references) | Ficheros de producción, tests y configuración. |

## Scope

| Área | Evidencia |
|---|---|
| Producción | `app/core/local_backend/rawsql.py`, `app/core/config.py` |
| Startup | `app.core.config._validate_secrets` valida el token al arrancar |
| Settings | `Settings.rawsql_auth_token`, `Settings.shared_secret_min_length` |
| Tests | `tests/test_rawsql_auth.py` (unit, 9 casos), `tests/integration/test_local_backend.py` (integration, 6 round-trip cases con header) |
| AGENTS.md | §6 (auth default-deny), §11 (CRITICAL_HELPERS 100%), §32.P2 (secret validation al arranque) |
| Mitigante pre-existente | El endpoint no se monta en ``app.main`` — solo en ``app.core.local_backend.app.create_app`` (usado por los verificadores de migración y por los tests de integración). Hoy no es explotable en producción; este PR elimina la bomba latente. |
| Dependencias | Ninguna añadida (usa ``hmac`` stdlib y ``fastapi.Header`` ya importados). |
| Fecha | 2026-09-07 |

Fuera de alcance: autorización granular por usuario sobre rawsql (no hay sesión — el operador decide quién recibe el token); rate limiting sobre el endpoint (actualmente sin rate-limit porque el operador decide su exposición); autenticación de los verificadores de migración que hoy hablan al executor directamente sin pasar por HTTP.

## Methodology

1. **Clasificación del activo (hr / apap-security §1)**: el endpoint ejecuta SQL arbitrario contra Postgres. Cualquier request sin auth equivale a ``GRANT ALL`` sobre la DB local. Severidad High como defecto de código, Low en el despliegue actual por el mitigante de arriba.
2. **Default-deny en startup (hr-1 / §6)**: ``Settings.rawsql_auth_token`` es string vacío por defecto. ``_validate_secrets`` rechaza arrancar producción con token vacío o más corto que ``shared_secret_min_length`` (32). En modo debug, la validación se omite — el handler en sí sigue siendo default-deny porque lee el token desde settings y rechaza cuando está vacío.
3. **Validación en runtime**: ``_require_rawsql_token`` extrae el header, lo compara con ``hmac.compare_digest`` (no operador ``==``, que es vulnerable a timing attacks), y rechaza con 401 + ``WWW-Authenticate: Bearer`` antes de tocar ``app.state.local_postgres_executor``. El handler solo llama al helper; el resto del flujo no cambia.
4. **Tests unitarios (hr-13, 100% coverage del helper)**: nueve casos en ``tests/test_rawsql_auth.py`` cubren header ausente, header vacío, esquema incorrecto (Basic/Token/Digest/bearer minúscula), token correcto, whitespace trailing, token con un carácter cambiado, configured-token vacío (server-side), configured-token vacío + header vacío (doble vacío), prefix-match de 10 caracteres sobre un token de 40.
5. **Tests de integración actualizados**: el fixture ``local_backend_client`` provisiona ``APAP_RAWSQL_AUTH_TOKEN`` y las 6 llamadas existentes a ``/api/database/advance/rawsql`` reciben ``headers={"Authorization": "Bearer " + os.environ["APAP_RAWSQL_AUTH_TOKEN"]}``. Los tests de integración están fuera del ``pytest`` de CI (``--ignore=tests/integration``), pero el cambio mantiene paridad con el handler.
6. **Cobertura CRITICAL_HELPERS (hr-13 / §11)**: el helper ``_require_rawsql_token`` cae dentro del gate de coverage porque es función pura testeable sin side-effects.
7. **Sin logs sensibles (hr-7/hr-8 / §9)**: el helper no loguea el token ni el header. Solo ``log_safe("startup.config_invalid", env_var=..., reason=...)`` se emite al fallar la validación de startup, y nunca contiene el valor del token.

## Findings

### Finding 1 — Endpoint ejecuta SQL arbitrario sin auth (issue #680, severity High)

- **Forma**: handler ``execute_rawsql`` en ``app/core/local_backend/rawsql.py`` declara ``payload: dict`` como único input y pasa ``payload["query"]`` directo a ``executor.execute``. Sin ``Depends(require_authorized_user)``, sin header check, sin ``APAP_*`` env var.
- **Detalle**: confirmado por inspección directa del código (líneas 34-64 antes del fix). ``app/core/local_backend/app.py:139`` monta el router sin middleware de auth adicional.
- **Mitigante observado**: ``app/main.py`` (la app de producción) no monta ``rawsql_router``. El router solo se monta en ``app.core.local_backend.app:create_app``, usado por ``migration/verify_fallback_*.py``. La gravedad en producción actual es Low porque el código vulnerable no se ejecuta, pero el seam sigue siendo peligroso: cualquier futuro caller que importe ``create_app`` hereda el endpoint abierto.
- **Resolución**: el helper ``_require_rawsql_token`` se invoca al inicio del handler con default-deny (header ausente → 401, scheme incorrecto → 401, token mismatch → 401, token configurado vacío → 401). La validación startup rechaza producción sin token o con token corto.

### Finding 2 — Producción arranca insegura sin token (severity High derivado)

- **Forma**: ausencia de validación startup para ``APAP_RAWSQL_AUTH_TOKEN``.
- **Detalle**: antes del fix, el handler siempre respondía 200 si recibía un payload válido, aunque la app no hubiese sido configurada. Producción arrancaba con ``Settings.rawsql_auth_token == ""`` y aceptaba cualquier request (hasta el cambio de comportamiento del handler).
- **Resolución**: ``_validate_secrets`` ahora emite ``log_safe("startup.config_invalid", env_var="APAP_RAWSQL_AUTH_TOKEN", reason="empty" | "too_short")`` y levanta ``StartupConfigError`` antes de servir tráfico cuando ``debug is False``. En debug, la validación se omite pero el helper sigue siendo default-deny a nivel de handler.

### Finding 3 — Las pruebas de integración asumían que el endpoint estaba abierto (severity Medium)

- **Forma**: ``tests/integration/test_local_backend.py::local_backend_client`` no configuraba ``APAP_RAWSQL_AUTH_TOKEN`` ni enviaba ``Authorization`` en los seis ``client.post("/api/database/advance/rawsql", ...)``.
- **Detalle**: los tests pasarían con el handler abierto pero fallarían con 401 contra el handler protegido. Actualizar los tests era necesario para mantener la cobertura de la rama integration.
- **Resolución**: el fixture provisiona ``rawsql_token = "test-rawsql-bearer-token-" + "a" * 24`` (44 caracteres, supera el piso de 32) y se inyecta en ``os.environ["APAP_RAWSQL_AUTH_TOKEN"]``. Cada ``client.post`` añade ``headers={"Authorization": "Bearer " + os.environ["APAP_RAWSQL_AUTH_TOKEN"]}``. El ``apps.state.rawsql_test_token`` queda como artefacto para futuras extensiones (tests que necesiten inspeccionar el token sin pasar por ``os.environ``); no es estrictamente necesario hoy.

## Verdict

**Status: success.** El endpoint ``POST /api/database/advance/rawsql`` ahora:

1. Requiere ``Authorization: Bearer <token>`` con token exactamente igual al configurado (``hmac.compare_digest``).
2. Responde 401 + ``WWW-Authenticate: Bearer`` ante cualquier desviación: header ausente, header vacío, esquema incorrecto, token incorrecto, token con whitespace inválido, token configurado vacío.
3. No se llega al executor si la auth falla (default-deny antes del side-effect).
4. Producción rechaza arrancar sin token válido de al menos 32 caracteres.
5. Tests unitarios del helper (9 casos) y tests de integración actualizados con el header.
6. Ningún log expone el token, el header, ni el resultado de la comparación.

Riesgos abiertos / fuera de alcance:

- No hay rate limiting sobre el endpoint (el operador decide su exposición). Si la superficie crece (ej. un cliente automatizado que sostiene el token), un futuro PR puede añadir ``RateLimitMiddleware`` con una bucket dedicada.
- No hay logging de los requests que llegaron pero fallaron la auth (se loguea el header ausente, pero no el token incorrecto para no contaminar logs con valores). Si el operador quiere detectar probing, puede activar ``log_level=DEBUG`` y añadir ``log_safe("rawsql.auth_failed", source_ip=...)`` siguiendo §9 redacción.
- La integración entre ``migration/verify_fallback_*.py`` y el endpoint HTTP sigue siendo opcional; los verificadores hoy hablan al executor directamente. Si en el futuro quieren pasar por HTTP, deben provisionar ``APAP_RAWSQL_AUTH_TOKEN`` explícitamente.

## References

- `app/core/local_backend/rawsql.py` — handler con el helper de auth
- `app/core/config.py` — ``Settings.rawsql_auth_token``, ``Settings.shared_secret_min_length``, validación startup
- `tests/test_rawsql_auth.py` — 9 casos unitarios del helper
- `tests/integration/test_local_backend.py` — fixture y tests de integración actualizados con header
- AGENTS.md §6, §11, §32.P2
