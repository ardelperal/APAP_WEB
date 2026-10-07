# 1148 — docs(merge): documentar allow_auto_merge/allow_update_branch y su límite honesto

- Issue: https://github.com/ardelperal/APAP_WEB/issues/1148 (type:docs, status:approved)
- Origen: decisión 2 de la épica de CI (#958), opción B aplicada y verificada por read-back el 2026-09-30 (`allow_auto_merge=true`, `allow_update_branch=true`, `strict=true`). Traspaso `odd/HANDOFF-ci-2026-09-30.md` §3.2.1 pasos 5-6.
- Rama: `chore/1148-merge-option-b-docs` en worktree `/home/ubuntu/repos/apap-app-worktrees/chore-1148-merge-option-b-docs`.
- Superficies: `docs/codebase/merge-workflow.md` (nueva §15.8), `CONTRIBUTING.md` (sección «Control del merge»).
- Validación: `python3 scripts/check_alantyle.py docs/codebase/merge-workflow.md` (0), `uv run --extra dev pytest tests/test_ci_workflow.py`, `uv run python scripts/preflight.py`.
- Cierre: PR con `Closes #1148`; #958 recibe comentario puntero y **no** se cierra hasta probar `update-branch` con un PR real (este PR es la prueba).
