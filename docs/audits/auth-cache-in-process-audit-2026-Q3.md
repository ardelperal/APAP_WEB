[← Back to README](../../README.md)

# auth-cache-in-process-audit-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del cierre del seam Redis en la caché de autenticación (resolución de #287), limitando la configuración a un único backend `in_process` y rechazando cualquier otro valor al arrancar la aplicación, ejecutado en 2026 Q3.

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Cierre del seam Redis y contrato de backend único. |
| [Methodology](#methodology) | Procedimiento TDD aplicado para reducir el seam. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del backend de caché de autenticación. |
| [References](#references) | Ficheros de producción, tests y runbook. |

## Scope

| Área | Evidencia |
|---|---|
| Producción | `app/core/auth_cache.py`, `app/core/config.py` |
| Startup | `app.main.create_app()` y `app.main.lifespan` cargan `get_settings()` antes de servir tráfico |
| Tests | `tests/test_auth_cache_backend.py`, `tests/test_lifespan.py` |
| Contrato de repo | AGENTS.md §29 |
| Operación | `docs/runbooks/auth-cache-multi-worker.md` |
| Audit histórico | `docs/audits/auth-cache-shared-2026-Q3.md`, marcado como superseded |
| Dependencias | Ninguna añadida; `pyproject.toml` no cambia |
| Fecha | 2026-07-25 |

Fuera de alcance: autenticación OAuth, cookies, roles, consultas a `usuarios_autorizados` y puntos de invalidación en `app/core/auth.py`.

## Methodology

1. Evaluación de las dos opciones planteadas en #287 y elección de retirar el seam porque el despliegue real no necesita invalidación compartida hoy.
2. Confirmación del estado de Coolify: la aplicación `apap-web` usa build pack Dockerfile, no tiene override de start command, tiene una réplica y ejecuta el `CMD` de Uvicorn sin `--workers`. Resultado: un proceso worker confirmado el 2026-07-25.
3. Análisis del flujo: `app.main.create_app()` valida settings al construir la aplicación y el lifespan los vuelve a obtener antes de crear el cliente o ejecutar bootstrap; `auth_dependencies` y `auth` siguen usando los mismos facades públicos; `auth_cache.py` ya no importa settings ni selecciona implementaciones.
4. TDD estricto: safety net inicial con **35 passed** antes de cambios; RED con **5 failed, 17 passed** por las cinco carencias esperadas (clase Redis presente, dos valores de backend aceptados, docstring que ofrecía Redis y startup que aceptaba Redis); GREEN con **35 passed** en auth cache + startup; refactor con **54 passed** en auth cache, lifespan y config.
5. Verificación completa: gate local canónico con **2546 passed, 2 skipped, 1 deselected**; cobertura global **89.33%**; `CRITICAL_HELPERS` con **21/21 al 100%**; ruff, `check_rules.py`, module-size, route-size y mypy sin errores.

La ejecución cruda sin los ajustes locales reprodujo tres fallos ambientales ya conocidos y no tocados por este cambio: dos subprocesses `pytester` sin el worktree en `PYTHONPATH` y el test de concurrencia que exige PostgreSQL real. No hubo fallos de producto relacionados con #287.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| HIGH | `APAP_AUTH_CACHE_BACKEND=redis` alcanzaba `NotImplementedError` en el primer request autenticado | fixed | `RedisAuthCache` y la rama selectora se eliminaron. |
| HIGH | El field `str` aceptaba Redis y valores desconocidos sin validar | fixed | Se sustituye por `Literal["in_process"]`; Pydantic detiene el lifespan. |
| MEDIUM | La invalidación sigue siendo local al worker | deferred | Coolify usa un worker; antes de escalar se exige TTL=0. Documentado en runbook. |
| MEDIUM | TTL=0 aumenta a una consulta de autorización por request | deferred | Trade-off explícito, con deploy y rollback en el runbook. |
| LOW | El audit de #262 describía el seam como contrato vigente | fixed | Banner histórico y enlace a este audit. |

## Verdict

PASS: no quedan hallazgos HIGH abiertos. La configuración imposible deja de fallar en tráfico vivo y pasa a rechazarse en startup. El despliegue actual de un worker conserva exactamente el comportamiento previo del backend en proceso. Cualquier escalado futuro queda condicionado a `APAP_AUTH_CACHE_TTL_SECONDS=0` y al procedimiento verificable de `docs/runbooks/auth-cache-multi-worker.md`.

## References

- `app/core/auth_cache.py` (sin seam Redis).
- `app/core/config.py` (`Literal["in_process"]`).
- `tests/test_auth_cache_backend.py`.
- `tests/test_lifespan.py`.
- `docs/runbooks/auth-cache-multi-worker.md`.
- `docs/audits/auth-cache-shared-2026-Q3.md` (superseded).
- AGENTS.md §29 (contrato vigente de la caché de autenticación).
