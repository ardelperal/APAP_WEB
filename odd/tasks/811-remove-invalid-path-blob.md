# #811 — Remove invalid-path tracked blob from `origin/main`

## Goal

Eliminar el blob tracked con path inválido en Windows que rompió `git checkout` desde `origin/main`. El path es literalmente un comando `sed` persistido como nombre de archivo por error en `1c02d86 refactor(migration): rewrite package against LocalBackend`. Hasta que se limpie, cualquier `git clone`, `git checkout -b <branch> origin/main`, `git worktree add` desde `origin/main` falla en Windows con `error: invalid path`. Eso bloquea a `DysTelefonica/team-skills` para propagar partials al catálogo, y bloquea a cualquier developer Windows que intente clonar el repo.

Issue viva: #811 (abierta por `ardelperal`, 2026-09-19).

## Acceptance criteria

1. `origin/main` deja de contener el path con caracteres NTFS-inválidos (`\n` literal en metadata, `|`, `$`).
2. `git checkout -b <tmp> origin/main` desde Windows / WSL ya no falla con `invalid path`.
3. El commit legítimo `1c02d86` mantiene intactos sus 43 archivos modificados (los stubs, el migration package rewrite, los tests).
4. El `propagate-team-skills.ps1` de DysTelefonica/team-skills puede crear `skill-fleet/APAP_WEB` desde `origin/main` sin workaround.

## Scope (este slice = #811)

Una rama, un commit, un PR.

- **Rama**: `fix/811-remove-invalid-path-blob` desde `origin/main` (`04c7b24`).
- **Commit**: `git rm -- "<path-basura>"` con quoting de comillas simples (path contiene `$`, `|`, `\` pero NO `\n` real — los `\n` son literal `\`+`n`).
- **Diff esperado**: 1 archivo, 0 insertions, 1 deletion.
- **PR body**: `closes #811`, cita el run de `ci / required` verde.
- **Merge**: `--no-ff`, vía standing auth §15.6 (CI verde).

## Out of scope

- **No reescribir historia**. §15.1.4 prohíbe `--force` y reescritura. El commit `1c02d86` permanece en la historia con su blob-basura; el commit de cleanup lo remueve del tree de `main` de forma no destructiva.
- **No migrar el cambio TYPE_CHECKING del sed a `migration/cli*.py`**. El sed apuntaba a `migration/cli.py`, `migration/cli_apply_reverse.py`, `migration/cli_ensure_bucket.py`. Esos archivos NO recibieron el `if TYPE_CHECKING: ...` block en `1c02d86` ni en commits posteriores. Ese gap funcional queda intacto y se aborda en una issue separada si corresponde.
- **No agregar smoke test CI** (regresión). El usuario eligió la opción mínima. La regresión queda documentada en este doc para issue futura si reaparece.
- **No tocar `.atl/skill-registry.md`** (modificación pre-existente del working tree, no relacionada con #811).

## Diagnosis (de la exploración previa)

- **Blob a remover**: SHA `384bb5d4753760ff01baaef3f09a886827c9446e`.
- **Path**: `eb_client,|g; s|^from typing import IO$|from typing import IO, TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from app.core.adapters.stubs.auth_users_stub import StubAuthUsersPort|g` (comilla doble al inicio y al final; los `\n` son `\`+`n` literales, no byte 0x0a).
- **Commit introductor**: `1c02d86 refactor(migration): rewrite package against LocalBackend` (aroman, 2026-09-07). El commit modificó legítimamente 43 archivos + introdujo el path-basura por error (probable `sed -i '...' file` sin argumento target, o `git mv` con path mal formado).
- **Contenido del blob**: `    None = None,| None = None,\n` (1 línea, no es código Python válido — `ast.parse` falla con `IndentationError`). Es ruido puro del patrón sed.
- **Referencias al path en el repo**: 0. Nadie lo importa ni lo lee.
- **Impacto en clones Linux/macOS**: `git clone` y `git checkout` funcionan (Linux/macOS aceptan esos caracteres en filenames). Por eso pasó desapercibido hasta que DysTelefonica/team-skills intentó propagar desde Windows.
- **Estado del path en `origin/main`**: tracked, en el root del tree (no en subdirectorio).

## Plan de validación local (pre-push)

1. Crear rama desde `origin/main`.
2. `git rm -- "<path>"` (probado en dry-run: `git rm --cached --dry-run` mostró `rm 'eb_client,...'`).
3. `git status` confirma: `D "eb_client,...|g"`, ningún archivo legítimo modificado.
4. `git diff --stat HEAD~1` muestra `1 file changed, 0 insertions(+), 1 deletion(-)`.
5. `python -c "import ast, pathlib; ast.parse(pathlib.Path('app/main.py').read_text())"` (verifica que app/ no quedó tocado).
6. `git checkout -b tmp origin/main` desde otra rama limpia — smoke test: el árbol se crea sin errores en este Linux.
7. `git push origin fix/811-remove-invalid-path-blob`.
8. `gh pr create --base main --head fix/811-remove-invalid-path-blob --title "fix(repo): drop invalid-path tracked blob (closes #811)" --body "..."`.
9. Esperar `ci / required` verde.
10. `gh pr merge --merge --body "ci/required run: <url>"`.

## Evidence trail

- `git ls-tree -r origin/main | grep -F 'eb_client'` → confirma blob en HEAD.
- `git log --all --diff-filter=A --name-only --pretty=format:'%h %s' | grep -B1 'eb_client'` → identifica `1c02d86` como introductor.
- `git cat-file -p 384bb5d47 | xxd` → contenido es ruido (`None = None,| None = None,\n`).
- `git grep -F 'eb_client,|g' $(git rev-list --all | head -50)` → 0 referencias en código.
- `gh issue view 811 --repo ardelperal/APAP_WEB` → issue existe, estado OPEN, reportada por `ardelperal`.

## Next steps post-merge

- Confirmar a DysTelefonica/team-skills que el bloqueante está resuelto (canal que reportó el issue).
- Considerar (issue separada, fuera de scope de este PR) agregar un job CI que haga `git ls-tree -r origin/main | git check-attr -a --stdin` o equivalente para detectar paths con caracteres no-ASCII antes de mergear.
