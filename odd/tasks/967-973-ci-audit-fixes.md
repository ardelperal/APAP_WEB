# #967 — #973 — Fixes de la auditoría CI/CD 2026-09-24 (umbrella)

## Goal

Cerrar los 7 issues abiertos por la auditoría de fricción de CI del
2026-09-24 (umbrella #957, épica #935), cada uno en su propia rama/PR
siguiendo la convención `<type>/<issue>-<slug>` del repo.

## Scope

| # | Issue | Rama | Prioridad | Estado |
|---|---|---|---|---|
| 1 | #967 (high, bug) — API key InsForge en historial público | `chore/967-insforge-final-cleanup` → PR #988 | high | ✅ Mergeado. Allowlist por fingerprint en `.gitleaksignore` con protocolo documentado en `docs/codebase/security.md`. Cierra también #641, #666, #670 como bonus. |
| 2 | #968 (high, chore) — `check_mutation_sites` informativo | `chore/968-mutation-sites-informational` → PR #977 | high | ✅ Mergeado |
| 3 | #969 (high, chore) — `check_crap` informativo + sin baseline exacto | `chore/969-crap-informational` → PR #978 | high | ✅ Mergeado |
| 4 | #970 (low, chore) — `check_docstring_coverage` informativo | `chore/970-docstring-coverage-informational` → PR #979 | low | ✅ Mergeado |
| 5 | #971 (medium, chore) — Cycles: entry obsoleta = NOTE, no fail | `chore/971-import-cycles-stale-as-notice` → PR #982 | medium | ✅ Mergeado |
| 6 | #972 (medium, chore) — `required_conversation_resolution` CodeQL | `chore/972-codeql-conversation-resolution` → PR #980 | medium | ✅ Mergeado. Branch protection `required_conversation_resolution.enabled = false` aplicada vía `gh api PUT`. |
| 7 | #973 (low, chore) — MinIO e2e fijado por digest | `chore/973-minio-digest-pin` → PR #981 + #995 + #997 | low | ✅ **Cerrado 2026-09-26** con réplica GHCR: imagen construida desde el source de MinIO CE pineado y e2e fijado por digest `sha256:6140fe70…dae8f`. Los secrets de Docker Hub se descartaron: las imágenes CE ya no existen en ningún registro. |

## Constraints

- TDD estricto: test que falla por el comportamiento actual → fix → verde.
- `make verify` en verde antes de cada commit.
- Conventional Commits; un PR por issue con `Closes #NNN`.
- No tocar nada fuera del "Alcance y no objetivos" declarado en cada issue.
- No hacer merge sin confirmación explícita del usuario en cada PR (autorización standing activa según §15.6).
- Nunca borrar ramas remotas.
- Pre-MVP single-branch → todos los PRs van contra `main`.
- Presupuesto de revisión 400 líneas por PR; este umbrella está muy por debajo (cada PR ~50-100 LOC).

## Patrón compartido: gates informativos

Las issues #968, #969, #970 y #971 comparten un patrón: pasar un gate
de CI a informativo (avisa, no bloquea) preservando el informe. El
criterio uniforme aplicado es:

- **Mantener el script ejecutándose** en el mismo job (`lint` o `test`).
  No se quita el step del workflow — el pineo en `tests/test_ci_workflow.py`
  sigue vigente.
- **Cambiar el contrato** del script: `main()` sale con exit 0 mientras
  no haya defectos reales; las "violaciones" que eran headroom
  (mejorar un baseline, entrada obsoleta, fichero sin entry que crece)
  pasan a `NOTE`.
- **Documentar** en `docs/codebase/quality-gates.md` la tabla de gates
  con su estado (bloqueante / informativo) y la razón.

Este patrón está alineado con `check_ruff_ratchet.py`, que ya emite
`NOTE` para entradas obsoletas / mejoras (precedente en el repo).

## Acceptance criteria

Cada fila de la tabla de Scope pasa a "PR abierto, CI verde, esperando
confirmación de merge" con el número de PR anotado. #967 queda
bloqueado por la evidencia humana de revocación.

## Progress log

- 2026-09-25 — Documento creado tras planificación inicial con el
  usuario. 7 worktrees dedicados bajo
  `/home/ubuntu/repos/apap-app-worktrees/chore-{issue}-*`, uno por
  issue, ramas `chore/{issue}-{slug}` desde `main`. Arranque con
  #968 y #969 (high priority).

- 2026-09-25 — **#968, #969, #970, #971 mergeados como PRs (#977,
  #978, #979, #982)**. Cada uno con TDD real (RED → GREEN), commit
  con conventional commits sin atribución IA, `make verify` local
  verde. Doc compartido `docs/codebase/quality-gates.md` actualizado
  solo en #968 (los demás PRs no tocan docs/codebase para evitar
  conflicto de merge); la tabla 'Estado de los gates' lista los 4
  issues de la auditoría.

- 2026-09-25 — **#972 mergeado (PR #980)**. Documentación de la
  decisión de desactivar `required_conversation_resolution` en
  `docs/codebase/merge-workflow.md` (sección §15.7). El comando
  `gh api` se ejecutó como follow-up tras el merge con OK explícito
  del usuario: `required_conversation_resolution.enabled = false`
  verificado por read-back.

- 2026-09-25 — **#973 PR abierto (#981)**. Cambio estructural:
  `services.minio` gana bloque `credentials:` referenciando
  `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN`. Bloqueador humano:
  mantenedor debe añadir los dos secrets al repo para que el job
  e2e pueda descargar la imagen autenticada. El pin por digest queda
  como follow-up tras el primer pull autenticado. Consideramos usar
  el MinIO de Coolify como alternativa; usuario decidió mantener el
  approach de Docker Hub.

- 2026-09-25 — **#967 mergeado (PR #988)**. Usuario confirmó que
  InsForge está deprecado en código (#924). PR elimina el último
  shim vivo (`app/core/adapters/insforge/__init__.py`), añade
  allowlist por fingerprint en `.gitleaksignore` con comentario
  documentando el protocolo (revocar + desactivar runtime + allowlist
  + verificación), refresca nota stale de CHANGELOG.md, y añade
  sección 'Secretos históricos en git history' en
  `docs/codebase/security.md`. Bonus: cierra #641, #666, #670.

- 2026-09-25 — **#641 cerrado (PR #992)**. Sweep final del cleanup
  InsForge en un solo PR grande: 22 archivos, +54/-57, 4309 tests
  verde, ruff limpio. Renombra `APAP_INSFORGE_*` → `APAP_LOCAL_BACKEND_*`
  en `migration/` + tests; elimina alias `get_insforge_client_dep`
  en 3 routes; limpia whitelist de `scripts/check_alantyle.py` y
  `.atl/skill-registry.md`; renombra fixture `fake_insforge` →
  `fake_backends` en `tests/test_auth_flow.py`; actualiza runbooks
  y roadmap; marca `docs/audits/secret-startup-validation-2026-Q3.md`
  como superseded por #658. Comentarios históricos en audit docs,
  snapshots y archivos renombrados se mantienen porque documentan
  el "por qué" del cleanup.

- 2026-09-25 — **Worktrees locales podados** tras los merges:
  `chore-insforge-cleanup-A` y `chore-insforge-rest` removidos
  (las ramas remotas se retienen según §15.2 — granularidad por
  unidad de trabajo). También removidos los worktrees
  `chore-970-docstring-info` y `chore-972-codeql-conv-resolution`
  de los PRs ci-audit mergeados.

- 2026-09-26 — **Reencuadre de #973 por evidencia de registry**.
  Verificado en vivo: `minio/minio` ya no es pullable de forma
  anónima — `quay.io/minio/minio` devolvió `unauthorized` (repo
  ya no público), `mirror.gcr.io` / `public.ecr.aws` / mirrors
  de terceros sin la imagen, y Docker Hub niega el fetch de
  manifest con `UNAUTHORIZED` a nivel repo. Búsqueda web confirma
  la causa raíz: MinIO Community Edition pasó a distribución
  source-only a fines de 2025 (issue `minio/minio#21662`;
  StableBuild: "MinIO images disappeared from Docker Hub") y las
  imágenes binarias se removieron. Consecuencia: el approach del
  PR #981 (bloque `credentials:` + secrets `DOCKERHUB_USERNAME`/
  `DOCKERHUB_TOKEN`) es inviable por diseño — no hay imagen que
  bajar. Usuario eligió (2026-09-26): **réplica GHCR construida
  desde el source oficial pineado** — workflow one-shot clona
  `minio/minio` en un `RELEASE.*` pin, construye la imagen y la
  publica en `ghcr.io/ardelperal/APAP_WEB/*`; el job e2e
  referencia el digest y autentica el pull con el `GITHUB_TOKEN`
  efímero (packages:read), cero secrets almacenados.

- 2026-09-26 — **#973 cerrado en 3 PRs**. PR #981 (merge
  `bebb676`): reemplaza el approach de secrets por la réplica
  GHCR + workflow `minio-replica.yml` + runbook
  `docs/operations/minio-replica.md` + 3 tests pin, rebased/merged
  sobre main tras los PRs de UI (#990/#993/#994). PR #995 (merge
  `b6eaabb`): el primer dispatch real (run 36249625652 predecesor
  36247204251 falló) reveló que el `Dockerfile` upstream es un
  wrapper `FROM minio/minio:latest` sobre la imagen removida y que
  `dl.min.io` devuelve 410 para CE — reescrito como build
  multi-stage desde source (golang:1.24-alpine → ubuntu:24.04 con
  curl para el healthcheck), test pin extendido (RED→GREEN).
  PR #997 (merge `8889a77`): build exitoso publicó
  `ghcr.io/ardelperal/minio:{RELEASE.2025-10-15T17-29-55Z,ci}` al
  digest `sha256:6140fe7015bd97e4e6340c9a8ead775c09bc1a226b7c36e41d24852f839dae8f`
  (run 36249625652); ci.yml pineado por digest con test constante
  `MINIO_REPLICA_DIGEST`. Pull autenticado con `GITHUB_TOKEN`
  (packages:read) — cero secrets almacenados. Nota de fricción: el
  gate `issue-spec` requiere `Closes #N` en el body (PR #995 lo
  necesito; `gh run rerun --failed` reutiliza el payload original
  del evento — cerrar y reabrir el PR para regenerarlo).

## Estado final

- **6 de 7 issues de la épica ci-audit cerrados** (#967, #968,
  #969, #970, #971, #972).
- **#641 cerrado** como bonus del cleanup InsForge (también cierra
  #666, #670).
- **#973 reencuadrado y CERRADO el 2026-09-26** (PRs #981, #995,
  #997): secrets de Docker Hub descartados porque las imágenes CE
  ya no existen en ningún registro; réplica GHCR desde source con
  e2e fijado por digest. Los 7 issues de la épica ci-audit quedan
  cerrados.
- **8 PRs mergeados** (#977, #978, #979, #980, #982, #988, #992,
  más el #891/893 que eran merges previos de la sesión) + 3 PRs de
  #973 (#981, #995, #997).
