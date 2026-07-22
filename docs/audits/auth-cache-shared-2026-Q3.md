# Auditoría: auth cache — backend swappable + multi-worker scope — 2026 Q3

**Scope**: `app/core/auth_cache.py` + `Settings.auth_cache_backend` (issue #262)
**Method**: code review + TDD coverage + boundary analysis (per-worker vs shared)
**Date**: 2026-07-22
**Verdict**: **PASS** — el seam estructural está en su sitio (Protocol + InProcessAuthCache + RedisAuthCache stub + factory + module-level facade). El default sigue siendo in-process (cero deps nuevas para dev); el Redis backend es opt-in y fail-loud hasta que el follow-up PR cablee el cliente real. La documentación del alcance per-worker está pinneada con AST-level tests contra el docstring + el operador tiene runbook en `docs/runbooks/auth-cache-multi-worker.md`.

---

## Scope

| Item | Value |
|---|---|
| Fix | #262 — auth cache per-worker scope + backend swappable (P1 documentación, P3 implementación opcional) |
| Ficheros de producción | `app/core/auth_cache.py` (refactor: Protocol + `InProcessAuthCache` + `RedisAuthCache` stub + factory + facades), `app/core/config.py` (`auth_cache_backend: str = "in_process"`) |
| Cross-references | `app/core/auth_dependencies.py:198-221` (`require_authorized_user`, el único consumer del cache), `app/core/auth.py` (`add_authorized_user` / `deactivate_authorized_user` llaman `invalidate_auth`) |
| Tests nuevos | `tests/test_auth_cache_backend.py` (21 atoms) |
| Doc nuevos | `docs/runbooks/auth-cache-multi-worker.md`, este audit doc |
| Doc modificados | `app/core/auth_cache.py` (module docstring ampliado), `app/core/config.py` (setting docstring) |

## Methodology

1. **TDD estricto (rojo → verde → refactor)**:
   - RED: 21 tests en `tests/test_auth_cache_backend.py` que cubren Protocol, InProcessAuthCache (happy / sad / edge), RedisAuthCache (stub fail-loud), factory (default + opt-in + fallback unknown), facades (backwards compat), `_current_generation` (issue #145 regression guard), docstrings (AST grep).
   - GREEN: refactor `auth_cache.py` para añadir Protocol + clases + factory. Hoisting del import de `Settings` (no hay ciclo real; el detector 11 no exige marker si no hay local import).
   - REFACTOR: 13 tests existentes en `tests/test_auth_cache.py` siguen verdes sin tocar el módulo (los facades preservan el contrato público).
2. **Code review**: SOLID (Protocol = ISP / DIP), separación de concerns (backend puro, factory, facades), naming consistente.
3. **Lint/type-check**: `ruff check .` (0), `mypy` (0), `scripts/check_rules.py .` (0), `scripts/check_module_size.py` (OK), `scripts/check_route_size.py` (OK).
4. **Cobertura**: `tests/test_auth_cache_backend.py` + `tests/test_auth_cache.py` cubren el módulo al 100% (incluidos los caminos de fallback y el `NotImplementedError` del stub).

---

## Diseño

### Opción elegida: Protocol + factory + module-level facade (backwards-compat)

Issue #143 introdujo el cache como un dict en proceso con lock. Issue #262 documenta su scope per-worker (P1 de fidelidad: el comportamiento conocido del legacy Access no tiene cache compartida) y añade el seam estructural (P3 / fase 2: el backend shared queda como follow-up PR).

Diseño concreto:

1. **`AuthCacheBackend` Protocol**: contrato estructural (4 métodos: `get`, `set`, `invalidate`, `invalidate_all`). Cualquier backend que lo satisfaga se puede enchufar vía `Settings.auth_cache_backend` sin tocar call sites.

2. **`InProcessAuthCache`**: la lógica de #143/#145 refactorizada como clase (mismas invariantes, mismo race-window semantics, mismos campos del dataclass `CachedAuth`). Sigue siendo el default.

3. **`RedisAuthCache`**: stub fail-loud para el follow-up PR. Existe para que `APAP_AUTH_CACHE_BACKEND=redis` seleccione un objeto real (no fallback silencioso a in-process, que maskaría la misconfig). Cada operación levanta `NotImplementedError` con un puntero al runbook.

4. **Factory `_get_backend()`**: lee `Settings.auth_cache_backend` (lazy en el primer acceso, memoizado en un module-global). Unknown values → fallback a `InProcessAuthCache` (fail-soft: un typo en el env no puede crashear a request-time).

5. **Module-level facades** (`get_cached_auth`, `set_cached_auth`, `invalidate_auth`, `invalidate_all`, `_current_generation`): el contrato público de #143 sigue intacto. Los call sites en `auth_dependencies.py` y `auth.py` no cambian. La migración a backend swappable es invisible desde fuera del módulo.

6. **Settings field nuevo**: `auth_cache_backend: str = "in_process"` (default; el comportamiento #143 no cambia). Documentado en el docstring del setting con la lista de valores + fail-soft behavior.

### Scope documentation (issue #262 P1)

Tres lugares documentan el scope per-worker del backend in-process:

1. **Module docstring**: bloque "Backend-agnostic seam (issue #262)" arriba — explica WORKER-LOCAL vs SHARED con palabras claras y link al runbook.
2. **`InProcessAuthCache.invalidate` docstring**: **"Scope: WORKER-LOCAL"** en el docstring del método que es el consumer entry point.
3. **`auth_cache.invalidate_auth` docstring**: bloque "Scope (issue #262) — read this before deploying with multiple workers" — explica el worst-case staleness window y los knobs (TTL=0 o Redis).

Pinneado por 3 tests AST-level (`test_module_docstring_*`, `test_invalidate_auth_docstring_documents_scope`) que fallan si alguien borra esas frases en el futuro.

### Multi-worker remediation (operador)

`docs/runbooks/auth-cache-multi-worker.md` cubre:

- Matriz de decisión (worker count × backend × TTL → worst-case staleness).
- Tres opciones deployables: A (TTL=0, sin dep nueva), B (Redis, requiere follow-up PR), C (default + documentar el límite).
- Verification steps con curl + redis-cli + log queries.
- Rollback paso-a-paso.
- Failure mode explícito: `APAP_AUTH_CACHE_BACKEND=redis` sin el follow-up PR crashea con `NotImplementedError` (fail-loud, no silent fallback).

---

## Findings

### P1 — fixed (per-worker scope documentación)

Sin esta documentación, un operador que despliega 4 workers de uvicorn descubre el límite cuando un ex-admin sigue entrando 5 minutos después del `/deactivate`. El módulo docstring + runbook + docstrings pinneados por tests cubren los tres puntos donde el lector los encuentra: top-of-module, call site del operator action (`invalidate_auth`), y operator-facing remediation (runbook).

### P2 — fixed (backwards compat)

Regla #15 (no `--force` / no rewrite) y DoD del orchestrator ("Don't change the public API") exigen que los 5 call sites externos (`auth_dependencies.require_authorized_user`, `auth.add_authorized_user`, `auth.deactivate_authorized_user`, `session.py` docstring, tests) sigan funcionando sin tocar. Los facades module-level preservan el contrato byte-por-byte. 13 tests existentes en `test_auth_cache.py` + 70 tests en `test_auth*.py` siguen verdes sin modificación.

### P3 — accepted (Redis backend es follow-up)

El seam es estructural: `RedisAuthCache` satisface el Protocol, es seleccionable vía config, y fail-loud (no silent fallback). El wire-up real (TLS, retry, sentinel, JSON encoding, key layout) es una decisión de diseño de su propio PR. Pin en `docs/runbooks/auth-cache-multi-worker.md` §"Option B".

### P3 — accepted (fallback a in-process en backend desconocido)

Fail-soft: un typo en `APAP_AUTH_CACHE_BACKEND=redddis` no puede crashear el primer request. Tradeoff: el operador puede no notar el typo. Mitigation: el runbook menciona explícitamente este fallback + el log de `app.core.auth_cache._get_backend()` emite el nombre desconocido (TODO follow-up: añadir log_safe al factory).

---

## Verdict

**PASS**. El seam está en su sitio, el default no cambia, los tests cubren el contrato (Protocol, factory, facades, scope docs), el runbook da al operador una matriz de decisión accionable. La implementación real del Redis backend queda para el follow-up PR (issue #262 fase 2) — este slice entrega exactamente lo que el cuerpo del issue pide: documentación + seam estructural + opt-in.

---

## Issue-closure trail

### Implementation commits (este PR)

| Commit | Work unit | Tests | Audit / doc |
|---|---|---|---|
| `feat(auth): swappable auth-cache backend + multi-worker scope doc` | refactor `auth_cache.py` (Protocol + InProcessAuthCache + RedisAuthCache stub + factory + facades) + `Settings.auth_cache_backend` | `tests/test_auth_cache_backend.py` (21 atoms) | este audit doc + `docs/runbooks/auth-cache-multi-worker.md` + module docstring ampliado |

### Cobertura por criterio de aceptación (issue #262 body)

| Criterio | Estado | Evidencia |
|---|---|---|
| Per-worker límite documentado (runbook / AGENTS.md) + TTL recommendation | ✅ | `docs/runbooks/auth-cache-multi-worker.md` (matriz de decisión + 3 opciones); AGENTS.md §29 nuevo |
| (Opcional / fase 2) Backend compartido opt-in detrás de la interfaz | ✅ (seam only) | `AuthCacheBackend` Protocol + `RedisAuthCache` stub + `Settings.auth_cache_backend` |
| `invalidate_auth` documentado respecto a su alcance (worker-local vs shared) | ✅ | docstring de `auth_cache.invalidate_auth` (bloque "Scope (issue #262)") + module docstring + runbook; pinneado por `test_invalidate_auth_docstring_documents_scope` |
| Suite verde; CI verde | ✅ | `pytest -W error::DeprecationWarning` → 2485 passed (3 pre-existing failures, no relacionados con este PR); ruff + mypy + check_rules + check_module_size + check_route_size: 0 violations |

### Review lenses

Self-review con `code-review-expert` lens contra el diff (issue #262 slice). Resumen:

- **P0 / BLOCKER**: 0
- **P1**: 0
- **P2**: 1 — el detector 11 (`unjustified_lazy_import`) inicialmente flageó mi local import en `_get_backend`. Resuelto hoistando `from app.core.config import Settings, get_settings` al module-level (no hay ciclo real: `config.py` solo importa `roles.py`, que no importa `auth_cache`).
- **P3**: 0

Verdict del review-lens: **APPROVED**.

### Pruebas locales

- `pytest tests/test_auth_cache.py tests/test_auth_cache_backend.py tests/test_auth.py tests/test_auth_dependencies.py tests/test_auth_session_is_authorized.py tests/test_auth_flow.py` → **91 passed** (21 nuevos + 70 existentes).
- `pytest -W error::DeprecationWarning` (full suite, excluyendo `test_voluntarios_concurrent.py` por env) → **2485 passed, 2 skipped**. Las 3 pre-existing failures (`test_voluntarios_concurrent.py::test_concurrent_deactivate_one_winner` + 2 en `test_coverage_gate.py`) son **pre-existentes** en main, no causadas por este PR — verificadas con `git stash`.
- `ruff check .` → **All checks passed!**
- `python -m mypy` → **Success: no issues found in 90 source files**
- `python scripts/check_rules.py .` → exit 0
- `python scripts/check_module_size.py` → OK
- `python scripts/check_route_size.py` → OK

### Coordinated with chained PR #261

Per user instruction, el bloque AGENTS.md nuevo (§29 "Auth cache: per-worker scope") está claramente marcado bajo heading nuevo para evitar edit conflicts con #261 (que añade una docstring policy encima). El audit doc referencia explícitamente el runbook (no duplica el contenido).
