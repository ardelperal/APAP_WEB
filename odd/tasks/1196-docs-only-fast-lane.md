# #1196 — Carril rápido docs-only: PRs de documentación saltan los jobs pesados

## Goal

La directiva del operador: un PR simple que no significa un release nuevo
no puede tardar horas. Un PR docs-only (TODOS los archivos cambiados son
documentación) salta `test`, `integration`, `typecheck`,
`verify-fallback-ready`, `build` y `e2e` con skip explícito y documentado,
mientras los gates rápidos (issue-spec, pr-name, pr-size, lint, security,
CodeQL, required) siguen corriendo SIEMPRE. Fail-closed: la detección es
estricta (un solo archivo de código ⇒ carril completo).

## Scope

| Área | Archivos |
|---|---|
| Detección `docs_changed` (reutiliza el diff de ui-detection, #895) | `.github/workflows/ci.yml` |
| Clasificador + semántica de skip en el agregador | `scripts/check_required_jobs.py` |
| Pins de condiciones y skip acceptance (RED→GREEN) | `tests/test_ci_workflow.py`, `tests/test_check_required_jobs.py` |

## Design decisions

1. **Patrón previo #895 reutilizado, no reinventado**: el job
   `ui-detection` ya computa el changed-file set (`CHANGED`) con
   merge-base/event.before; se extiende con un segundo output
   `docs_changed` clasificado por `--docs-changed` en el single source of
   truth (`check_required_jobs.py`), igual que `ui_changed` usa
   `--ui-changed`. Cero checkouts/diffs adicionales.
2. **Conjunto de patrones docs (propuesto en el PR body para revisión)**:
   - `docs/**` — todo el árbol de documentación.
   - `*.md` en la raíz (solo raíz: `README.md`, `AGENTS.md`, …).
   - `skills/**/*.md` — solo markdown; assets de skills no cuentan.
   - EXPLÍCITAMENTE FUERA: `.github/**` (incluido su markdown —
     code-adjacent), `app/`, `migration/`, `tests/`, `www/`, `scripts/`,
     `openspec/`, `odd/`, y markdown anidado fuera de `docs/` (p. ej.
     `app/README.md`).
3. **Fail-closed en ambas direcciones**: `docs_changed=false` por defecto;
   empty diff ⇒ false (no-op ≠ docs); toll anti-autoexención: los fuentes
   del gate (`ci.yml`, `deploy.yml`, `check_required_jobs.py`) jamás
   clasifican como docs (espejo del toll de #895).
4. **Skip semantics**: los jobs pesados llevan condición explícita
   `if: github.event_name != 'pull_request' || needs.ui-detection.outputs.docs_changed != 'true'`
   (necesitan `ui-detection` como need directo). El agregador acepta el
   skip solo con el marcador `docs_changed='true'` publicado por
   `ui-detection` (mismo contrato que el marcador e2e de #895, fail-closed
   ante marcador ausente/malformado). Release events (dispatch/tags) jamás
   aceptan el salto. `e2e` salta además cuando `docs_changed='true'`
   aunque `ui_changed` no sea `'false'` (un diff puramente documental no
   puede ser cambio de UI).
5. **Matriz de schedule intacta (#1046)**: las nuevas `if` de los jobs
   pesados no contienen status functions ⇒ el cascada de `pr-size`
   saltado sigue saltándolos en schedule. Pinned en
   `test_ci_workflow_schedule_runs_security_deep_only`.
6. **Refactor bajo ratchet**: la extensión de `evaluate` reventó
   PLR0912/PLR0911/PLR0913 (BASELINE shrink-only) — se extrajo
   `_allowed_skips_for_event` y `_e2e_marker_violation` en vez de subir
   baseline.

## Dependencias resueltas

- Patrón #895 (`ui_changed` + marcador en `required`): ✅ ya en main.
- Preflight #1192 (honra working-directory/env): ✅ 20/20 con las nuevas
  condiciones (preflight solo simula el job `lint`; las `if` son
  job-level y no añaden atributos de paso ignorados).

## Progress log

- 2026-10-01: issue #1196 creada y aprobada (type:chore, status:approved).
- 2026-10-01: RED capturado (ImportError `DOCS_ONLY_HEAVY_JOBS` + pins de
  condiciones ausentes). GREEN: 185 tests de las dos suites verdes.
- 2026-10-01: ratchet ruff OK (436 findings, bajo baseline), ruff/mypy
  limpios, actionlint limpio con los ignores declarados, preflight 20/20,
  suite completa 5307 passed / 21 skipped (env-dependent).
- 2026-10-01: simulación end-to-end: docs-only+marcador ⇒ required OK;
  docs-only sin marcador ⇒ FAIL con razón documentada por job; PR mixto ⇒
  verde con todo corrido; clasificador OK en las 4 formas de diff.
