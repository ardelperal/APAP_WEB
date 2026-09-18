# #797 — Remediación CRAP pre-existente en `migration/`

## Goal

Bajar el CRAP score de dos funciones en `migration/` por debajo de sus baselines pineados, sin tocar lógica de negocio. El objetivo es dejar `ci / required` verde estable para que el cherry-pick + merge de #780 (que ya está mergeado en `bb476a5`) siga siendo el camino limpio.

Issue viva: #797 (`status:approved`, `type:bug`).
Análisis refinado: ver comentario publicado en la issue tras la investigación del run #35274071081.

## Scope (este slice)

Cherry-pick contra `origin/main` (`af48dcf` post-PR #799) sobre una rama nueva `ci/797-crap-remediation`. Solo `migration/`:

1. **`migration/apply.py::apply_legacy_to_web`** — CRAP 21.60 (baseline 21.02).
   - Causa: 1-2 ramas del flujo principal sin cubrir.
   - Solución: tests adicionales sin refactor.
   - Hipótesis: branches del path `dry_run` que el coverage no exercita.

2. **`migration/apply_helpers.py::_apply_value_transform`** — CRAP 165.41 (baseline 23.82).
   - Causa: dispatcher de 9 ramas (`identity`, `nullify_empty_string`, `normalize_sexo`, `normalize_especie`, `normalize_si_no`, `currency_to_numeric`, `double_to_numeric`, defaults) con cobertura directa 0%.
   - Solución: refactor a tabla de dispatch + tests directos para cada transform.
   - Cada transform pasa a ser su propia función pura testeable.

## Out of scope (hasta que PR 2 DOC-01 mergee a `origin/main`)

- `_safe_content_length` en `app/modules/contratos/...` — solo vive en `feat/56-doc-01-pr2-pdf-storage`.
- Falsos positivos gitleaks en `tests/test_contratos_local_backend_storage.py` — idem.

## Work-unit commits planeados

| WU | Descripción | Estado |
|---|---|---|
| WU-1 | Tracking + rama `ci/797-crap-remediation` desde `origin/main` | en curso |
| WU-2 | TDD: tests directos para `_apply_value_transform` (uno por transform) | pendiente |
| WU-3 | Refactor de `_apply_value_transform` a tabla de dispatch (`TRANSFORMS = {"identity": _identity, ...}`) | pendiente |
| WU-4 | TDD: tests adicionales para ramas no cubiertas en `apply_legacy_to_web` | pendiente |
| WU-5 | Validar: `uv run python3 scripts/check_crap.py` + `uv run pytest tests/test_apply*` + `uv run make verify` | pendiente |
| WU-6 | Push + PR contra `origin/main` con `Closes #797` + label `type:refactor` | pendiente |
| WU-7 | Merge `--no-ff` (post CI verde) | pendiente |
| WU-8 | Limpiar rama local (sin `--delete-branch` remoto) | pendiente |

## Gates (CI required check, pre-MVP single-branch)

- `uv run python3 scripts/check_crap.py` verde (las 2 violaciones resueltas).
- `uv run python -m mypy` verde.
- `uv run ruff check .` limpio.
- `uv run pytest tests/test_apply*.py tests/migration/ -q` verde (sin reducir cobertura).
- `ci / required` verde en el head del PR (incluye `test` con CRAP ratchet).
- Diff ≤ 400 líneas o `size:exception`.

## Legacy fidelity (P1)

N/A — el slice es remediación de cobertura/refactor en código de migración, no toca legacy Access ni dominio.

## Estrategia de implementación

Cherry-pick de los 2 archivos modificados sobre `origin/main`. Como es código de `migration/`, no hay solapamiento con DOC-01 (que vive en `app/modules/contratos/`).

**TDD estricto** (AGENTS §4): para cada transform nuevo (`_identity`, `_nullify_empty_string`, etc.) y para cada rama adicional de `apply_legacy_to_web`, escribir el test rojo primero, luego el código que lo pasa verde.

El refactor del dispatcher es seguro: cada `if transform == "..."` actual ya tiene el comportamiento documentado en docstrings; extraído a función pura sigue siendo el mismo contrato. Los tests cubren el contrato antes y después del refactor.

## Riesgos identificados

1. **`_apply_value_transform` se invoca desde `_legacy_to_web_row` en `migration/apply_row_mapping.py`**: el refactor no debe cambiar el comportamiento observable. Cobertura del test_apply_row_mapping antes y después debe ser idéntica.
2. **`apply_legacy_to_web` es una función grande con muchos paths (bootstrap, partial check, MSACCESS, lock, snapshot, read loop)**: agregar tests para 1-2 ramas no es trivial si esas ramas son del flujo SIGINT o partial-apply (que ya están cubiertas en otros tests, pero el coverage no las cuenta). Hay que verificar con `coverage json` qué líneas específicas faltan.
3. **La rama `ci/797-crap-remediation` no debe romper el flow de DOC-01**: como cherry-pickeo contra `origin/main`, no introduzco los contratos PR 2 (que están en `feat/56-doc-01-pr2-pdf-storage`). El diff queda aislado a `migration/`.

## Criterios de cierre del slice

- [ ] Cherry-pick mergeado en `ci/797-crap-remediation` con SHA fresco (sin `Co-Authored-By`).
- [ ] CRAP ratchet verde: `apply_legacy_to_web` ≤ 21.02 (baseline), `_apply_value_transform` ≤ 23.82 (baseline).
- [ ] Cobertura de `migration/` no disminuye.
- [ ] `uv run pytest tests/` verde (suite completa).
- [ ] CI verde en el head del PR.
- [ ] PR mergeado con `--no-ff` contra `origin/main`.
- [ ] #797 cerrada con SHA + path del test (commit de cobertura).
- [ ] Documentación de las nuevas funciones puras en el docstring (sin cambiar la prosa del archivo).
- [ ] Worktree + rama local limpiados.
- [ ] Memoria de sesión guardada con `mem_session_summary`.
