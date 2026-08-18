[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Merge workflow

Esta página posee la regla §15 de AGENTS verbatim: política pre-MVP single-branch, ciclo de vida de rama, revert post-MVP y autorización standing de merge. La regla está activa hasta declaración explícita de MVP.

## §15 — Workflow de merge: política pre-MVP single-branch + revert post-MVP

Este proyecto está **pre-MVP**. La regla por defecto es: **todo el trabajo aterriza en `main`, toda rama no-`main` se borra inmediatamente después de su merge, y al final de cada ciclo de merge la única rama en pie es `main`.** No hay rama `staging` longeva en pre-MVP. Cuando el usuario declara MVP alcanzado, el workflow revierte al gate estándar `staging` + UAT descrito en §15.4 abajo.

### §15.1 Gate pre-MVP — todo debe ser verdadero antes de mergear a `main`

1. **`pytest` local está verde.** `python -m pytest -W error::DeprecationWarning` con los mismos `addopts` de `pyproject.toml` (bloque `[tool.pytest.ini_options]`) pasa localmente. Si `tests/test_voluntarios_concurrent.py` forma parte de la corrida, el entorno debe exponer `APAP_E2E_BASE_URL` (según `ci.yml` y el hardening REG-S-3) — en CI el archivo se `--deselect`-ea porque GitHub no aprovisiona Postgres.
2. **`ci.yml` está verde en el head de la rama que se está mergeando.** Lint (`ruff check .` + el linter de reglas de AGENTS `python scripts/check_rules.py .`, regla §20), `test` (pytest con `DeprecationWarning` como error) y `build` (`python -m build`) DEBEN pasar. `e2e` y `deploy` son opcionales según `.github/workflows/ci.yml`: `e2e` se salta cuando `APAP_OAUTH_CLIENT_ID` no está fijado; `deploy` se salta cuando `COOLIFY_WEBHOOK_URL` no está fijado. Su ausencia no es un merge blocker en pre-MVP.
3. **El diff es revisable.** Un solo diff de PR debe quedar por debajo de `review_budget_lines: 400` (default del orchestrator). Si una feature es mayor, divídala en PRs encadenados usando la skill `chained-pr` — nunca reviente main con un merge sobredimensionado.
4. **Sin `--force`, sin reescritura de historial.** Merge con `--no-ff` para mantener visible el commit de feature; nunca `git push --force` a `main`; nunca rebase commits ya enviados.

### §15.2 Ciclo de vida de rama pre-MVP

- El trabajo ocurre en feature branches cortas desde `main`. Los nombres siguen el scope de conventional commits: `feat/<scope>`, `fix/<scope>`, `refactor/<scope>`, `docs/<scope>`, `ci/<scope>`, `test/<scope>`.
- **La rama remota se retiene tras el merge.** Nunca pase `--delete-branch` a `gh pr merge`, nunca ejecute `git push origin --delete <branch>` ni `git push origin :<branch>`, y nunca pida a `gh` limpiar el ref al hacer merge, cerrar o reabrir. El PR es el artefacto de merge; la rama remota es la historia, y otros contribuidores, forks y artefactos cacheados de CI pueden referenciarla. Esto aplica a todo tipo de rama, incluidas las ya mergeadas a `main`.
- **El worktree local se elimina tras el merge.** Cuando el trabajo ocurrió en un git worktree y su PR aterrizó: `git worktree remove <path>`, luego `git worktree prune`. Un worktree stale cuesta un checkout completo en disco y — el daño real — deja una rama obsoleta checked out en algún sitio donde una sesión posterior puede recogerla y trabajar en el lugar equivocado. La rama local puede irse con él (`git branch -d <branch>`); el ref remoto queda.
- "Limpiar la rama" tras un merge significa el worktree local, nunca el ref remoto.
- **Nunca** borre `main`. **Nunca** cree o persista una rama `staging` en pre-MVP — eso contradice la política single-branch. Si `staging` ya existía antes de que esta regla entrara en vigor, migre sus commits a `main` primero, luego `git branch -D staging`; el ref remoto `staging` se retiene como cualquier otro.
- Tras cada ciclo de merge la única rama checked out localmente es `main`. Los refs remotos se acumulan a propósito y no son una fuga.

### §15.3 Hook de pre-push staging-only — estado en este repo

El 2026-07-03 el usuario desactivó `git config gentleai.stagingOnly` específicamente en este repo. El hook global de pre-push en `~/.config/opencode/git-hooks/pre-push` sigue existiendo pero es un **no-op para ESTE repo** (solo actúa cuando el flag por-repo está fijado a `true`). Los opt-ins de otros repos en `~/.config/opencode/git-hooks/` quedan intactos — el guardarraíl global continúa protegiéndolos. **NO** re-active el flag en pre-MVP — eso rearmaría el hook silenciosamente y contradiría el gate pre-MVP.

### §15.4 Revert post-MVP — procedimiento cuando se declara MVP

Cuando el usuario señale MVP alcanzado ("ya tenemos MVC", "MVP reached", "pasamos a producción", "vamos a staging" o equivalente), ejecute este procedimiento EN ORDEN:

1. **Re-active el hook staging-only en este repo.** `git config gentleai.stagingOnly true` — el hook global vuelve a actuar en los push a `main`.
2. **Recree `staging` si falta.** `git checkout -b staging main && git push origin staging`. A partir de aquí, **todo** el trabajo posterior va a `staging`, no a `main`.
3. **Defiera al contrato global staging-acceptance-contract.** El workflow se vuelve el estándar: el código aterriza en `staging` → UAT corrida por **Virginia** (validador) usando la skill `feature-acceptance-uat` (`docs/uat/uat-staging-<YYYY-MM-DD>.html`) → el usuario revisa el sign-off de Virginia → el usuario instruye explícitamente "merge to main" → el agente mergea. `main` es read-only hasta que aterrice esa instrucción explícita.
4. **Marque esta regla 15 como DORMANT (post-MVP).** Edite AGENTS.md para reemplazar §15.1–§15.3 con un párrafo apuntador al global `staging-acceptance-contract` y al nombre de Virginia como validador. Conserve §15.4 como registro histórico del ciclo de vida pre-MVP, pero márquela "ARCHIVED".
5. **El agente NO debe voltear fases preventivamente.** La declaración de MVP es un evento user-driven. Espere instrucción explícita; no infiera de frases como "ya está" o "vamos cerrando" sin la palabra clave MVP/MVC.

### §15.5 Lo que sigue NO siendo automático en pre-MVP (consentimiento explícito requerido)

- Commits directos a `main` sin PR — sigue requiriendo OK del usuario. Siempre aterrice vía PR desde una feature branch.
- `--force` a cualquier rama — stop absoluto, sin importar CI.
- Etiquetado de releases / corte de `vX.Y.Z` — user OK.
- Renombrado del default branch, cambio de branch protection en GitHub — user OK.
- Cualquier cosa que toque `git-hooks/`, el `core.hooksPath` global del usuario o el flag `gentleai.stagingOnly` de cualquier otro proyecto — user OK.

**Aplicación**: cada merge de PR aterrizado bajo esta regla DEBE mencionar la URL del run de `ci.yml` que probó el gate verde, en el cuerpo del merge commit o en la descripción del PR. Tras MVP, esta regla queda dormida y el global `staging-acceptance-contract` es autoritativo. Si el gate alguna vez deriva (por ejemplo, alguien añade un job CI adicional requerido, o la branch protection en `main` requiere un check extra), esta regla 15 es la fuente de verdad a actualizar en pre-MVP.

### §15.6 Autorización standing de merge (otorgada 2026-07-26, hasta fin de proyecto)

Efectivo desde el 2026-07-26 y hasta que el usuario señale el fin del proyecto, el orchestrator tiene autorización standing para mergear PRs a `main` sin OK por push. Esta es una conveniencia temporal para la fase pre-MVP.

**Alcance de la autorización**: el orchestrator puede mergear un PR a `main` él mismo cuando TODAS las siguientes se cumplen:

1. Los gates pre-MVP de §15.1 están visiblemente verdes:
   - `pytest -W error::DeprecationWarning` local pasa
   - `ci.yml` en el head de la rama mergeada está verde (lint, test, typecheck, build)
   - diff ≤ `review_budget_lines` (o `size:exception` aprobado por el mantenedor)
   - sin `--force`, sin reescritura de historial
2. El merge es un merge normal feature-branch → main (NO es force-push, NO es release tag, NO es rename del default branch, NO es cambio a git-hooks o `gentleai.stagingOnly`).
3. El cuerpo del merge commit o la descripción del PR cita la URL del run de `ci.yml` que probó el gate verde (según la nota de aplicación de §15.5).
4. Ningún cambio toca ningún elemento de la lista de §15.5 que aún requiere OK explícito del usuario.

**Items que SIGUEN requiriendo OK explícito por push del usuario** (la lista de §15.5 no cambia):

- Commits directos a `main` sin PR.
- `--force` a cualquier rama.
- Etiquetado de releases / corte de `vX.Y.Z`.
- Renombrado del default branch, cambio de branch protection en GitHub.
- Cualquier cosa que toque `git-hooks/`, el `core.hooksPath` global del usuario o el flag `gentleai.stagingOnly` de cualquier otro proyecto.

**Revocación**: el usuario puede revocar esta autorización standing en cualquier momento con frases como "stop auto-merging", "back to per-push OK", "revoke merge authorization" o equivalente. Tras la revocación, esta sección queda dormida y el orchestrator revierte a devolver PRs sin mergear.

**Señal de fin de proyecto**: cuando el usuario señale fin de proyecto ("MVP reached", "project end", "archive" o equivalente), esta sección queda dormida. El trabajo posterior revierte al flujo post-MVP estándar (§15.4 revierte; staging re-engancha según el global `staging-acceptance-contract`).

Esta autorización standing fue otorgada en chat el 2026-07-26 y codificada por el mismo PR que actualizó §17.3 paso 6. Cross-reference: §17.3 paso 6.

## Core invariants

- **Pre-MVP single-branch**: el único branch estable es `main`; `staging` no existe.
- **PR diff ≤ 400 líneas**: o `size:exception` aprobado por el mantenedor.
- **Merge con `--no-ff`**: el feature commit queda visible.
- **Refs remotos retenidos**: ningún `git push origin --delete` ni `--delete-branch` al mergear.
- **Worktrees locales podados**: `git worktree remove` + `git worktree prune` post-merge.
- **Standing auth hasta revocación**: §15.6 puede ser revocado en cualquier momento con frase explícita.

## Contributor checklist

- [ ] El branch de trabajo se nombra con scope conventional (`feat/...`, `fix/...`, etc.) y sale de `main`.
- [ ] Antes de mergear, el diff se queda ≤ 400 líneas o carga label `size:exception`.
- [ ] El merge usa `--no-ff` y cita la URL del run de `ci.yml` verde.
- [ ] No se pasó `--delete-branch` ni se ejecutó `git push origin --delete`.
- [ ] Tras el merge, el worktree local se removió con `git worktree remove` + `git worktree prune`.

## Navigation

Previous: [Process](process.md) | Next: [Orchestrator discipline](orchestrator-discipline.md)
