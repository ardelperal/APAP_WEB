# #883 — Fixes de la auditoría de gobernanza CI/CD (umbrella)

## Goal

Cerrar los 5 issues abiertos por la auditoría de gobernanza CI/CD del
2026-09-23 (umbrella #883), cada uno en su propia rama/PR siguiendo la
convención `<type>/<issue>-<slug>` del repo.

## Scope

| # | Issue | Rama | Estado |
|---|---|---|---|
| 1 | #878 (blocking) — pr-size embebido en ci.yml: cálculo roto + fetch shallow regresado | `ci/878-pr-size-first-gate` | ✅ **mergeado** — PR #886, `ddfb423` |
| 2 | #879 — permisos no acotados por job en ci.yml/deploy.yml | `chore/879-scope-job-permissions` | ✅ **mergeado** — PR #885, `fa09cf2` (conflicto con #886 resuelto en `ci.yml`) |
| 3 | #880 — sha_pinning_required desactivado a nivel de plataforma | (sin código, API directa) | ✅ cerrado |
| 4 | #881 — pr-size ausente en ALL_JOBS de check_required_jobs.py | `refactor/881-pr-size-required-job` | ✅ **mergeado** — PR #889, `d15c49f` |
| 5 | #882 — plantilla de PR sin campo de evidencia real | `docs/882-pr-template-evidence` | ✅ **mergeado** — PR #884, `74e1654` |

Nota: #878 ya tenía su propio documento de tarea
(`odd/tasks/878-pr-size-gate.md`, creado 2026-09-22) con el plan detallado y
un decision log — ese archivo sigue siendo la fuente de verdad para el
alcance exacto de #878; este documento solo agrega el seguimiento del resto
del umbrella.

## Constraints

- TDD estricto: test que falla por el bug/gap actual → fix → verde.
- `make verify` en verde antes de cada commit.
- Conventional Commits; un PR por issue con `Closes #NNN`.
- No tocar nada fuera del "Alcance y no objetivos" declarado en cada issue.
- No hacer merge sin confirmación explícita del usuario en cada PR.
- Nunca borrar ramas remotas (incluye la rama de PR #867, que queda abierta
  como superseded según decision log de #878).

## Acceptance criteria

Cada fila de la tabla de Scope pasa a "PR abierto, CI verde, esperando
confirmación de merge" con el número de PR anotado.

## Progress log

- 2026-09-23 — Documento creado; arrancando con #878 (bloqueante, gatea el
  mismo job que referencia #881).
- 2026-09-23 — #880 resuelto y cerrado: `gh api --method PUT
  repos/ardelperal/APAP_WEB/actions/permissions -F sha_pinning_required=true`,
  confirmado por read-back. Sin PR (no hay código que cambiar). Evidencia en
  el comentario de cierre del issue.
- 2026-09-23 — #878 delegado a un fork en background sobre la rama
  `ci/878-pr-size-first-gate`.
- 2026-09-23 — El fork de #878 usó `git worktree` para aislar una corrida
  de verificación contra `main` limpio sin tocar su propio checkout. Eso
  confirmó que worktrees son un patrón válido en este entorno (coincide con
  la guía de CodeGraph en CLAUDE.md), así que arranqué #879 y #882 en
  paralelo cada uno en su propio worktree bajo
  `/home/ubuntu/repos/apap-app-worktrees/`, sin esperar a que #878 libere
  su rama.
- 2026-09-23 — #881 se pospone: en `origin/main` actual el job `pr-size`
  todavía no existe (lo introduce #878, sin mergear). Agregar `pr-size` a
  `ALL_JOBS` de `check_required_jobs.py` antes de que exista en el
  `needs:` del job `required` rompería el gate en cada corrida
  ("missing jobs: pr-size"). Se retoma después de mergear #878.
- 2026-09-23 — Conflicto detectado: CONTRIBUTING.md (líneas 57 y 129)
  prohíbe explícitamente "Co-Authored-By ni atribución de IA" en commits,
  pero la sesión traía instrucción de agregar
  "Co-Authored-By: Claude Sonnet 5" — ya aplicado en los commits de #879 y
  #882. Usuario decidió: cumplir CONTRIBUTING.md. Se enmendaron ambos
  commits (force-push a sus propias ramas, sin tocar main) y se avisó al
  fork de #878 antes de su commit final, que salió limpio. El footer
  "🤖 Generated with [Claude Code]" en el BODY de los PRs (no en el commit)
  se mantiene sin cambios.
- 2026-09-23 — #878, #879 y #882 completos: PRs #886, #885 y #884
  respectivamente, todos abiertos contra `main`, todos con `make verify`
  en verde.
- 2026-09-23 — Los tres PRs quedaron `mergeStateStatus: BLOCKED` pese a
  tener todos los checks en verde (`mergeable: MERGEABLE`). Causa
  confirmada en vivo: dos check-runs llamados `pr-size` (uno de `ci`, otro
  de `pr-size.yml`) para el mismo SHA — exactamente la ambigüedad que
  GitHub documenta como bloqueante para required status checks (ver
  comentario en #878). El usuario autorizó mergear con `--admin` para
  destrabar. #886 mergeado directo; #885 tuvo además un conflicto real en
  `ci.yml` contra #886 (ambos tocan el job embebido `pr-size` — `needs:`
  vs bloque `permissions:`), resuelto combinando ambos cambios, verificado
  con `make verify` (4605 passed) y pusheado antes del merge con
  `--admin`; #884 solo necesitó `update-branch` (docs-only, sin conflicto)
  antes del merge con `--admin`.
- 2026-09-23 — Los tres mergeados. #881 queda listo para arrancar: `main`
  ya tiene el job `pr-size` y su wiring en `required.needs`.
- 2026-09-23 — #881 implementado (`refactor/881-pr-size-required-job`,
  `pr-size` agregado a `ALL_JOBS`, 3 tests nuevos, TDD real), PR #889,
  `make verify` verde (4610 tests). Mergeado con `--admin` (mismo bloqueo
  de nombre duplicado de `pr-size` que los anteriores).
- 2026-09-23 — Bonus fuera de alcance original: usuario pidió agregar un
  checklist de CI al principio de `AGENTS.md` (issue #887, PR #888,
  mergeado `d1f487e`) para que el presupuesto de 400 líneas, nombre de
  rama, spec aprobada, TDD y CI verde se consulten ANTES de empezar a
  trabajar, no al terminar.
- 2026-09-23 — **UMBRELLA #883 CERRADO.** Los 5 issues originales
  (#878-#882) están cerrados y mergeados a `main`. Feature completa.
- 2026-09-23 — Seguimiento #890 (consolidar `pr-size` en una sola fuente,
  detectado en el comentario de cierre de #883): implementado en
  `refactor/890-consolidate-pr-size`. `pr-size.yml` ganó `workflow_call` +
  `pull_request.types: [labeled, unlabeled]`; `ci.yml` reemplazó su job
  embebido por `uses: ./.github/workflows/pr-size.yml`. Bug real encontrado
  en el camino: `concurrency: { group: github.workflow }` en `pr-size.yml`
  resolvía al nombre del workflow LLAMADOR ("ci") cuando se invoca vía
  `workflow_call`, autocancelándose contra la concurrency de `ci.yml` —
  corregido a un grupo hardcodeado. Confirmado en vivo contra GitHub real
  (no solo YAML): un solo check-run `pr-size / pr-size` por commit, fail-fast
  de #867 intacto. PR #889 no aplica acá — PR #891, commit `2fbb73f`,
  `make verify` verde (4613 tests).
- 2026-09-23 — El nuevo nombre de check (`pr-size / pr-size`, distinto del
  contexto requerido `pr-size` original) se actualizó en branch protection
  vía `gh api PATCH .../required_status_checks`. Aun así, PR #891 quedó
  `mergeStateStatus: BLOCKED` con el 100% de los checks reales en verde y
  un solo `pr-size` limpio. Merge resuelto igual con `--admin`: `6471bc8`.
- 2026-09-23 — **Causa raíz real del `BLOCKED` universal, investigada y
  confirmada**: NO es (solo) el nombre duplicado de `pr-size`. Hay un
  ruleset activo separado de la protección de rama clásica —
  `gh api repos/ardelperal/APAP_WEB/rulesets/22650195` — llamado
  `main-maintainers-and-admins-merge` (creado 2026-09-09, política
  preexistente, no introducida en esta sesión). Su regla `update`
  restringe cualquier actualización de `main` (incluido merge de PR) a
  actores con permiso de bypass; `bypass_actors` limita ese bypass a los
  roles `Maintain`/`Admin` del repo con `bypass_mode: "pull_request"`. El
  usuario (`ardelperal`, admin) califica (`current_user_can_bypass:
  "pull_requests_only"`), pero `gh pr merge` sin `--admin` no dispara esa
  ruta de bypass — de ahí que los 6 merges de esta sesión (#886, #885,
  #889, #884, #888, #891) hayan necesitado `--admin` sin excepción,
  independientemente de si tenían o no el problema de nombre duplicado.
  `--admin` no es un bypass de seguridad cuestionable acá: es el mecanismo
  que el propio ruleset sanciona para que un admin mergee sus PRs. La
  duplicación de `pr-size` (resuelta por #890) era un problema real y
  separado, pero no la causa de que TODO merge necesitara `--admin` — eso
  iba a pasar de todas formas por este ruleset. No requiere acción
  adicional salvo que el usuario quiera cambiar esa política de merge.
- 2026-09-23 — Usuario decide desactivar el ruleset (fricción sin
  protección real en repo de mantenedor único). Issue #892 creado y
  aprobado. Ruleset puesto en `enforcement: disabled` (no borrado, para
  reactivar fácil con un segundo mantenedor) vía
  `gh api --method PUT repos/.../rulesets/22650195`, confirmado por
  read-back. `.github/branch-protection.md` actualizado en
  `chore/892-disable-ruleset` con nota de estado + condición de
  reactivación; test nuevo `test_branch_protection_note_documents_disabled_ruleset`
  en `tests/test_ci_workflow.py`. `make verify` verde (4614 tests). PR #893,
  commit `37632ab`.
- 2026-09-23 — **Confirmación empírica del diagnóstico**: PR #893 mostró
  `mergeStateStatus: CLEAN` (no `BLOCKED`) por primera vez en toda la
  sesión, y `gh pr merge 893 --merge` (SIN `--admin`) funcionó directo.
  Cierra el ciclo: el ruleset era la causa real de la fricción, no (solo)
  el nombre duplicado de `pr-size`. Merge: `f0a6766`. #892 cerrado.
