# CI audit — friction log (live)

Auditoría viva del CI de APAP_WEB. Objetivo: eliminar cada fricción experimentada
en primera persona durante el trabajo diario, y destilar el resultado en una skill
de «CI perfecto» (ver épica #935 y memoria Engram #4344).

Regla: cada entrada se registra cuando se experimenta, con evidencia ejecutable
(comando, run, output). Estado: `open` → hay que quitarla; `fixed` → PR/run que la
quitó; `wontfix` → decisión documentada.

## F-001 — El ratchet de ruff falla en CI pero no existe paridad local

- **Estado:** open
- **Experiencia:** PR #1111 (rama `fix/956-issue-spec-deterministic`). Local pasó
  `ruff check scripts/... tests/...` limpio; el job `lint` de CI falló a los 36 s
  por `check_ruff_ratchet.py` (TRY003: 188 > baseline 186, +2 del script nuevo).
- **Causa raíz:** el ratchet evalúa rulesets extendidos (S,ERA,ARG,FAST,N,C901,PLR,
  SIM,RET,TRY,PTH, issue #380) que `ruff check` por defecto no corre; el
  checklist del repo lo incluye, pero no hay un comando único de pre-flight que
  lo ejecute siempre.
- **Evidencia:** run 36592991754, job lint
  (`FAIL TRY003: 188 violation(s), exceeds baseline of 186`).
- **Remedio propuesto:** un comando canónico `make preflight` (o
  `scripts/preflight.py`) que corra exactamente lo que corre CI, y que el
  checklist del PR lo referencie. Criterio: cero divergencia local↔CI en lint.

## F-002 — El ratchet pide «lock in the improvement» pero nadie puede hacerlo sin trabajo manual

- **Estado:** open
- **Experiencia:** el mismo run imprime 9 NOTEs
  (`ARG001: 28 < 31 — update BASELINE to lock in the improvement`, etc.) desde
  hace días; el baseline vive como constantes editables en
  `scripts/check_ruff_ratchet.py:~172` y bajarlo es un edit manual + commit.
- **Causa raíz:** shrink-only sin mecanismo de lock-in automático; el gate es
  fail-loud para subidas pero mudo para bajadas.
- **Remedio propuesto:** script `--update-baseline` que reescriba las constantes
  cuando el conteo baja (o job semanal que abra PR de lock-in). Criterio: el
  baseline baja solo; ningún humano edita constantes a mano.

## F-003 — Un fallo de raíz se enmascara como 7 fallos de `required`

- **Estado:** open
- **Experiencia:** el mismo run de #1111: `lint` falla por TRY003 y los jobs
  dependientes se saltan; el job `required` lista
  `FAIL required jobs: build/e2e/integration/security/test/verify-fallback-ready/lint`
  con un volcado JSON crudo. El lector ve 7 fallos y tiene que inferir que la
  causa es una sola.
- **Causa raíz:** la política de required jobs no distingue `skipped-por-cascada`
  de fallo real, y el output no jerarquiza causa raíz primero.
- **Remedio propuesto:** que `check_required_jobs.py` imprima primero los jobs
  con `result='failure'` como causa raíz y agrupe los `skipped` como
  consecuencias (`skipped (upstream: lint)`). Criterio: un fallo de raíz = una
  línea de causa + N consecuencias etiquetadas.

## F-004 — size:exception es una danza manual (ya conocida, confirmada en vivo)

- **Estado:** open (issue #941/#896; regla de diseño en Engram #4344-c)
- **Experiencia:** PR #1110 y #1111: añadir label `size:exception` + escribir
  `size-exception-reason:` a mano en el cuerpo; pr-size puede no refrescarse en
  el evento `labeled` (#926/#936 histórico).
- **Remedio propuesto:** que el propio gate acepte la excepción declarada en el
  cuerpo (parse determinista) o que el workflow relea el label en rerun; en la
  skill: «toda excepción se declara en datos, no en gestos».

## F-005 — Recuperar una review interrumpida exige conocer hashes y tokens internos

- **Estado:** open (fricción del arnés de review, no del CI puro; afecta al gate
  humano que el CI asume)
- **Experiencia:** reanudar la review de #956 tras un corte de sesión requirió:
  `review start` (replay con consent) → `review status` con
  `--repository-context` emitido por el start → `capture-result` con
  `--expected-revision`, `--subject-hash` copiados a mano del JSON de estado →
  `acknowledge-approved` con `--token` extraído del state file interno de
  `.git/gentle-ai/`. Cinco pasos, tres hashes, un token; sin comando `resume`
  que los encadene.
- **Remedio propuesto (para el arnés, fuera del repo):** comando
  `review resume --lineage` que derive contexto/revision/subject/token del
  estado y ofrezca la ranura pendiente en un solo paso. Documentado aquí porque
  la skill de CI perfecto debe asumir que las reviews se interrumpen.

## F-006 — El entorno local no tiene `python` en PATH

- **Estado:** open (menor)
- **Experiencia:** `python -m pytest` → command not found; hay que descubrir
  `.venv/bin/python` a mano. Los docs de validación del repo dicen `uv run …` en
  unos sitios y `.venv` en otros.
- **Remedio propuesto:** el comando canónico de pre-flight (F-001) abstrae el
  intérprete; documentar uno solo.

## F-007 — Los workers en segundo plano no pueden commitear ni pushear sin aprobación interactiva

- **Estado:** open
- **Experiencia:** WU-1 (fix TRY003 de #1111) hizo la edición y la verificación
  completas, pero `git commit` fue auto-rechazado por la política de permisos
  de opencode («The user rejected permission to use this specific tool call»);
  no hay nadie para aprobar en un run desatendido.
- **Causa raíz:** el perfil del agente (`gentle-ai-worker`) no pre-autoriza
  `git commit`/`git push`, y el run en background no puede preguntar.
- **Remedio propuesto:** pre-autorizar git commit/push al worker de confianza
  en el worktree del slice, o contrato de dos fases (worker deja staged +
  evidencia; orchestrator aplica commit tras verificar DoD, como se hizo esta
  vez). Criterio: un worker delegado completa su ciclo sin intervención.

## Entradas pendientes de registrar

(esta sección crece mientras dure la auditoría)
