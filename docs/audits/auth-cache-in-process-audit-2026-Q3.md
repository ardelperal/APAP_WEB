# Auditoría: auth cache solo en proceso — resolución del seam Redis — 2026 Q3

**Scope**: resolución de #287 en `app/core/auth_cache.py`,
`app/core/config.py`, pruebas y contratos operativos.
**Methodology**: inspección del flujo de imports, TDD estricto, validación del
lifespan, revisión de la configuración Coolify y gates completos del repositorio.
**Date**: 2026-07-25.
**Verdict**: **PASS** — el selector Redis no implementado se ha retirado;
`redis` y cualquier backend desconocido se rechazan al cargar settings durante
el arranque, antes de aceptar tráfico. El backend en proceso conserva sin
cambios el TTL, el lock y la generación por email.

## Scope

| Área | Evidencia |
|---|---|
| Producción | `app/core/auth_cache.py`, `app/core/config.py` |
| Startup | `app.main.create_app()` y `app.main.lifespan` cargan `get_settings()` antes de servir tráfico |
| Tests | `tests/test_auth_cache_backend.py`, `tests/test_lifespan.py` |
| Contrato de repo | `AGENTS.md` §29 |
| Operación | `docs/runbooks/auth-cache-multi-worker.md` |
| Audit histórico | `docs/audits/auth-cache-shared-2026-Q3.md`, marcado como superseded |
| Dependencias | Ninguna añadida; `pyproject.toml` no cambia |

Fuera de alcance: autenticación OAuth, cookies, roles, consultas de
`usuarios_autorizados` y puntos de invalidación en `app/core/auth.py`.

## Methodology

1. **Fuente de verdad de la issue**: se evaluaron las dos opciones de #287.
   Se eligió retirar el seam porque el despliegue real no necesita invalidación
   compartida hoy.
2. **Confirmación de Coolify**: la aplicación `apap-web` usa build pack
   Dockerfile, no tiene override de start command, tiene una réplica y ejecuta
   el `CMD` Uvicorn sin `--workers`. Resultado: un proceso worker confirmado el
   2026-07-25.
3. **Análisis del flujo**:
   - `app.main.create_app()` valida settings al construir la aplicación y el
     lifespan los vuelve a obtener antes de crear el cliente o ejecutar bootstrap.
   - `auth_dependencies` y `auth` siguen usando los mismos facades públicos.
   - `auth_cache.py` ya no importa settings ni selecciona implementaciones.
4. **TDD estricto**:
   - Safety net: **35 passed** antes de cambios.
   - RED: **5 failed, 17 passed**, por las cinco carencias esperadas: clase
     Redis presente, dos valores de backend aceptados, docstring que ofrecía
     Redis y startup que aceptaba Redis.
   - GREEN: **35 passed** en auth cache + startup; refactor gate:
     **54 passed** en auth cache, lifespan y config.
5. **Verificación completa**:
   - Gate local canónico, con el worktree en `PYTHONPATH` y el atom de
     PostgreSQL real deseleccionado según `docs/proceso.md`:
     **2546 passed, 2 skipped, 1 deselected**.
   - Cobertura global: **89.33%**; `CRITICAL_HELPERS`: **21/21 al 100%**.
   - Ruff, `check_rules.py`, module-size, route-size y mypy: sin errores.

La ejecución cruda sin los ajustes locales reprodujo tres fallos ambientales ya
conocidos y no tocados por este cambio: dos subprocesses `pytester` sin el
worktree en `PYTHONPATH` y el test de concurrencia que exige PostgreSQL real.
No hubo fallos de producto relacionados con #287.

## Findings

| ID | Severidad | Hallazgo | Resolución |
|---|---|---|---|
| AC-287-1 | P1 | `APAP_AUTH_CACHE_BACKEND=redis` alcanzaba un `NotImplementedError` en el primer request autenticado. | **Fixed**: `RedisAuthCache` y la rama selectora se eliminaron. |
| AC-287-2 | P1 | El field `str` aceptaba Redis y valores desconocidos sin validar. | **Fixed**: `Literal["in_process"]`; Pydantic detiene el lifespan. |
| AC-287-3 | P2 | La invalidación sigue siendo local al worker. | **Accepted**: Coolify usa un worker; antes de escalar se exige TTL=0. |
| AC-287-4 | P2 | TTL=0 aumenta a una consulta de autorización por request. | **Accepted**: trade-off explícito, con deploy y rollback en el runbook. |
| AC-287-5 | P3 | El audit de #262 describía el seam como contrato vigente. | **Fixed**: banner histórico y enlace a este audit. |

## Security decisions

- **Fail at startup**: cualquier backend distinto de `in_process` impide que el
  lifespan llegue al bootstrap; no existe fallback silencioso ni fallo tardío.
- **No cambio de autorización**: se conservan la revalidación contra DB, el
  cache de positivos y negativos, el TTL y la generación por email.
- **No secretos nuevos**: no se añade URL, contraseña, token ni cliente Redis.
- **Semántica multi-worker explícita**: con más de un proceso no hay propagación;
  TTL=0 es la única remediación soportada para revocación inmediata.

## Verdict

**PASS**. No quedan hallazgos P0/P1 abiertos. La configuración imposible deja de
fallar en tráfico vivo y pasa a rechazarse en startup. El despliegue actual de un
worker conserva exactamente el comportamiento previo del backend en proceso.
Cualquier escalado futuro queda condicionado a `APAP_AUTH_CACHE_TTL_SECONDS=0`
y al procedimiento verificable de `docs/runbooks/auth-cache-multi-worker.md`.
