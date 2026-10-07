# #1169/#1170 — ci-pattern governance HRs (HR-23 a HR-28)

## Goal

Destilar en la skill `ci-pattern` las lecciones de gobernanza del tramo final
de la épica #935 (2026-10-01), dual-write: canónica
(`personal-skills/personal/ardelperal/ci-pattern/SKILL.md`) y espejo
(`skills/ci-pattern/SKILL.md` del repo APAP_WEB, vía worktree fresco).

## Acceptance criteria

1. SKILL.md canónico lleva HR-23 a HR-28 con verbo observable e incidente que
   las creó; cuerpo ≤700 líneas.
2. `odd/skill-ci-portable/source-notes.md` lleva R16-R19 con su evidencia.
3. `check_alantyle.py` exit 0 sobre los ficheros tocados.
4. Canónica: commit conventional sin atribución de IA + push a main;
   `~/.agents/skills/ci-pattern/` refleja el push vía hook
   (refresh-personal-symlinks).
5. Espejo: worktree fresco `/home/ubuntu/repos/apap-app-worktrees/ci-pattern-hr23`
   (regla un worktree por actor, HR-24 aplicada a sí misma), rama
   `docs/1169-ci-pattern-governance-hrs` desde `origin/main` (455ae9b), commit
   único, PR #1199 con `Refs #1169` + `Refs #1170` (sin Closes) y auto-merge
   armado (MERGE). Nota: el nombre `docs/ci-pattern-governance-hrs` prescrito
   falló el gate `branch-name` (exige `<tipo>/<N>-<slug>`); la rama se renombró
   y el PR #1198 inicial quedó cerrado por el renombrado (superseded).

## Lecciones destiladas

- HR-23: orquestación determinista, jerarquía mecanismo > script > IA
  (playbook regla 20; vigías zombis 2026-09-29).
- HR-24: un worktree por actor concurrente (colisión de shared-checkout
  2026-10-01).
- HR-25: las prescripciones del orquestador son hipótesis (vivid 4×:
  preflight 19 vs 20, §15.8 inexistente, SHA de slice-2 distinto, ruta de
  tests inexistente).
- HR-26: toolchains pineadas para mediciones (baseline local 11503 vs runner
  11559, xdebug sin pinear).
- HR-27: read-back doble con delay tras PATCH de settings + plan de la org
  (#1150; `allow_auto_merge` paywalled descartado con 200 OK).
- HR-28: suite aislada del `.env` local (5 rojos ambientales, `APAP_*`).

## Resultado verificado en vivo

- Canónica: push `24de7ee..880319a` (merge con el pase portable del
  mantenedor PR #148, que aterrizó durante el vuelo). El reconciliador
  (post-commit → refresh-personal-symlinks) NO cubre ci-pattern: su
  `SOURCE_DIR` es `$REPO_ROOT/skills` y la skill vive en
  `personal/ardelperal/`; `~/.agents/skills/ci-pattern/` queda stale
  (brecha de cobertura, no el bug de overlay rollback).
- Sin `Closes` en el PR espejo; `Refs #1169` + `Refs #1170`.

## Restricciones respetadas

- El working tree compartido de apap-app quedó intacto (otro actor corre en
  `chore/1187-preflight-hardening`); solo edición de ficheros untracked
  autorizados (`odd/`) y worktree fresco para el espejo.
