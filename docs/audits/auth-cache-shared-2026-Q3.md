[← Back to README](../../README.md)

# auth-cache-shared-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del corte que introdujo un seam estructural para el backend de la caché de autenticación (issue #262) — Protocol + `InProcessAuthCache` + `RedisAuthCache` stub + factory + facades — y que documentó el alcance per-worker del backend en proceso, ejecutado en 2026 Q3.

> **Registro histórico**: el seam Redis descrito aquí fue retirado por #287 porque nunca llegó a implementarse y el despliegue Coolify usa un único worker. El contrato vigente está auditado en [`auth-cache-in-process-audit-2026-Q3.md`](auth-cache-in-process-audit-2026-Q3.md).

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Seam estructural del backend de caché de auth. |
| [Methodology](#methodology) | Procedimiento TDD aplicado al refactor. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict) | Estado final del seam y su supersede posterior. |
| [References](#references) | Ficheros de producción, tests, runbook y cierre del issue. |

## Scope

| Item | Value |
|---|---|
| Fix | #262 — caché de auth per-worker + backend swappable (P1 documentación, P3 implementación opcional) |
| Ficheros de producción | `app/core/auth_cache.py` (refactor: Protocol + `InProcessAuthCache` + `RedisAuthCache` stub + factory + facades), `app/core/config.py` (`auth_cache_backend: str = "in_process"`) |
| Cross-references | `app/core/auth_dependencies.py:198-221` (`require_authorized_user`, único consumer del cache), `app/core/auth.py` (`add_authorized_user` / `deactivate_authorized_user` llaman `invalidate_auth`) |
| Tests nuevos | `tests/test_auth_cache_backend.py` (21 átomos) |
| Doc nuevos | `docs/runbooks/auth-cache-multi-worker.md`, este audit doc |
| Doc modificados | `app/core/auth_cache.py` (module docstring ampliado), `app/core/config.py` (setting docstring) |
| Fecha | 2026-07-22 |

Fuera de alcance: autenticación OAuth, cookies, roles, esquema de base de datos.

## Methodology

1. TDD estricto (rojo → verde → refactor): RED con 21 tests en `tests/test_auth_cache_backend.py` que cubren Protocol, `InProcessAuthCache` (happy / sad / edge), `RedisAuthCache` (stub fail-loud), factory (default + opt-in + fallback unknown), facades (backwards compat), `_current_generation` (issue #145 regression guard), docstrings (AST grep). GREEN: refactor de `auth_cache.py` para añadir Protocol + clases + factory. Hoisting del import de `Settings` (no hay ciclo real; el detector 11 no exige marker si no hay local import). REFACTOR: 13 tests existentes en `tests/test_auth_cache.py` siguen verdes sin tocar el módulo (los facades preservan el contrato público).
2. Code review: SOLID (Protocol = ISP / DIP), separación de concerns (backend puro, factory, facades), naming consistente.
3. Lint/type-check: `ruff check .` (0), `mypy` (0), `scripts/check_rules.py .` (0), `scripts/check_module_size.py` (OK), `scripts/check_route_size.py` (OK).
4. Cobertura: `tests/test_auth_cache_backend.py` + `tests/test_auth_cache.py` cubren el módulo al 100% (incluidos los caminos de fallback y el `NotImplementedError` del stub).

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| HIGH | Documentación del alcance per-worker | fixed | Sin esta documentación, un operador que despliega 4 workers de uvicorn descubre el límite cuando un ex-admin sigue entrando 5 minutos después del `/deactivate`. El módulo docstring + runbook + docstrings pineados por tests cubren los tres puntos donde el lector los encuentra: top-of-module, call site del operator action (`invalidate_auth`), y operator-facing remediation (runbook). |
| MEDIUM | Compatibilidad hacia atrás | fixed | Regla §15 (sin `--force` ni rewrite) y DoD del orchestrator ("Don't change the public API") exigen que los 5 call sites externos (`auth_dependencies.require_authorized_user`, `auth.add_authorized_user`, `auth.deactivate_authorized_user`, `session.py` docstring, tests) sigan funcionando sin tocar. Los facades module-level preservan el contrato byte por byte. 13 tests existentes en `test_auth_cache.py` + 70 tests en `test_auth*.py` siguen verdes sin modificación. |
| LOW | El backend Redis queda como follow-up | deferred | El seam es estructural: `RedisAuthCache` satisface el Protocol, es seleccionable vía config, y fail-loud (sin fallback silencioso). El wire-up real (TLS, retry, sentinel, JSON encoding, key layout) es una decisión de diseño de su propio PR. Pineado en `docs/runbooks/auth-cache-multi-worker.md` §"Option B". |
| LOW | Fallback a `in_process` en backend desconocido | deferred | Fail-soft: un typo en `APAP_AUTH_CACHE_BACKEND=redddis` no puede crashear el primer request. Trade-off: el operador puede no notar el typo. Mitigación: el runbook menciona explícitamente este fallback + el log de `app.core.auth_cache._get_backend()` emite el nombre desconocido (TODO follow-up: añadir `log_safe` al factory). |
| HIGH | El seam Redis resulta dead code alcanzable por configuración | fixed (issue #287, 2026-07-25) | `APAP_AUTH_CACHE_BACKEND=redis` alcanzaba `NotImplementedError` en el primer request autenticado. El seam estructural se retiró; el contrato vigente vive en `auth-cache-in-process-audit-2026-Q3.md`. |

### Cobertura por criterio de aceptación (issue #262 body)

| Criterio | Estado | Evidencia |
|---|---|---|
| Per-worker límite documentado (runbook / AGENTS.md) + TTL recommendation | Cumplido | `docs/runbooks/auth-cache-multi-worker.md` (matriz de decisión + 3 opciones); AGENTS.md §29 nuevo |
| (Opcional / fase 2) Backend compartido opt-in detrás de la interfaz | Cumplido (seam only) | `AuthCacheBackend` Protocol + `RedisAuthCache` stub + `Settings.auth_cache_backend` |
| `invalidate_auth` documentado respecto a su alcance (worker-local vs shared) | Cumplido | docstring de `auth_cache.invalidate_auth` (bloque "Scope (issue #262)") + module docstring + runbook; pineado por `test_invalidate_auth_docstring_documents_scope` |
| Suite verde; CI verde | Cumplido | `pytest -W error::DeprecationWarning` → 2485 passed (3 pre-existing failures, no relacionados con este PR); ruff + mypy + check_rules + check_module_size + check_route_size: 0 violations |

### Cierre del issue #280 (2026-07-27)

| Item | Value |
|---|---|
| Fix | #280 — `invalidate_all` ya no limpia `_generation` (bug: `self._generation.clear()` reabría la race write-after-invalidate que #145 cerró) |
| Root cause | `invalidate_all` hacía `_generation.clear()` → reset a 0 → una lectora que capturó verdict antes de `invalidate_all` podía re-escribir bajo la misma key `(email, 0)` y la entry volvía a ser reachable |
| Ficheros de producción | `app/core/auth_cache.py` (3 cambios: `set` ahora inicializa `_generation[email]`, `invalidate_all` itera sobre `_cache` keys, docstrings sync) |
| Tests | `tests/test_auth_cache.py` (2 assertions flip + 1 new race regression test `test_invalidate_all_write_after_invalidate_is_unreachable`) |
| Docstrings sync | Module header, `InProcessAuthCache.invalidate_all` method, module-level `invalidate_all` facade (AGENTS.md §30) |
| Verdict | PASS |

Causa raíz según el cuerpo de #280: el bug consistía en que `invalidate_all` ejecutaba `self._generation.clear()` reseteando todos los contadores a 0. Tras el reset, si una lectora R1 había capturado un verdict antes del `invalidate_all` y R1 escribía su verdict bajo `(email, 0)` después, esa entry colisionaba con la generation real (0 después del clear, o 1 después del primer bump) y volvía a ser reachable — la race se reabría.

La fix (#280) elimina `self._generation.clear()`. Los contadores de generation persisten (carry forward) tras el bump. La lectora R1 que escribió bajo la generation vieja (pre-invalidate) ya no colisiona con la current generation (post-invalidate). La race queda cerrada de nuevo.

## Verdict

PASS histórico: el seam estaba en su sitio, el default no cambiaba, los tests cubrían el contrato (Protocol, factory, facades, scope docs) y el runbook daba al operador una matriz de decisión accionable. La implementación real del backend Redis quedaba para el follow-up PR (issue #262 fase 2). Este slice entregaba exactamente lo que el cuerpo del issue pedía: documentación + seam estructural + opt-in.

El seam Redis descrito en este audit fue retirado por #287 (ver `auth-cache-in-process-audit-2026-Q3.md`); este documento queda como registro histórico del camino tomado.

## References

- `app/core/auth_cache.py` (refactor del slice; `RedisAuthCache` posteriormente retirado por #287).
- `app/core/config.py` (`auth_cache_backend: str = "in_process"`).
- `tests/test_auth_cache_backend.py` (21 átomos).
- `tests/test_auth_cache.py` (13 átomos preexistentes; +3 átomos por #280).
- `docs/runbooks/auth-cache-multi-worker.md`.
- Issue #262: <https://github.com/ardelperal/APAP_WEB/issues/262>
- Issue #280: <https://github.com/ardelperal/APAP_WEB/issues/280>
- Issue #287: <https://github.com/ardelperal/APAP_WEB/issues/287> (supersede del seam Redis).
- AGENTS.md §29 (contrato vigente tras #287).
- AGENTS.md §30 (docstrings como contrato — sync aplicada tras #280).
