# Guía de contribución

**Flujo de contribución, sistema de labels, convenciones y validación local para PRs en APAP_WEB.**

Consulte esta guía antes de abrir un issue o un PR. El contrato completo vive en [`AGENTS.md`](AGENTS.md) y [`docs/proceso.md`](docs/proceso.md).

Esta guía es el subconjunto que un contribuidor externo necesita para arrancar.

---

## Preparación del entorno

Requiere Python 3.11 o posterior, Git, `uv` y Docker para los gates que levantan
PostgreSQL o escanean imágenes.

```bash
git clone https://github.com/ardelperal/APAP_WEB.git
cd APAP_WEB
uv sync --frozen --extra dev
```

La configuración completa vive en [`DOCS.md`](DOCS.md) y
[`docs/development.md`](docs/development.md).

---

## Workflow issue-first

Todo cambio humano en `APAP_WEB` sigue este ciclo. Si contribuye una IA, lea antes la [travesía completa del contribuidor](#travesía-del-contribuidor-vista-completa): enumera, en orden, cada gate que encontrará y la firma documental que la CI le exigirá.

1. **Busque antes de crear.** Revise issues abiertas y cerradas; use la existente si ya cubre el problema.
2. **Abra una issue si falta.** Use el formulario correcto y complete el [contrato issue-as-spec](docs/codebase/issue-specifications.md).
3. **Espere `status:approved`.** Solo el mantenedor autoriza la implementación.
4. **Reclame la issue.** Comente que va a trabajar en ella y compruebe que nadie la ha reclamado antes.
5. **Cree la rama desde `main`.** Use `<type>/<issue>-<slug>` (ver [Convención de ramas](#convención-de-ramas)).
6. **Implemente con TDD.** La cobertura global es ≥ 85%; los `CRITICAL_HELPERS` exigen 100%.
7. **Valide localmente.** Ejecute los comandos aplicables antes del push.
8. **Abra un PR honesto.** Incluya referencia de cierre, validación real y un diff ≤ 400 líneas. El mantenedor comprueba manualmente que lleva exactamente un label `type:*`.
9. **Espere CI verde.** Los checks requeridos de `main` son `branch-name`, `required` (rollup de `ci.yml`) y `pr-size / pr-size`.
10. **Integre con `--no-ff`.** Solo `Maintain` o `Admin` pueden mergear. Mientras el equipo sea unipersonal se exigen cero aprobaciones humanas.

Las secciones obligatorias son `Problema y contexto`, `Evidencia verificable`,
`Alcance y no objetivos`, `Criterios de aceptación`, `Plan de validación` y
`Dependencias y riesgos`.

Dependabot es la única excepción al origen humano de la spec. Sus PR conservan
los demás gates.

---

## Contribuciones asistidas por IA

La asistencia de IA está permitida. El autor revisa cada línea, elimina
contenido inventado o ajeno al alcance, comprende los tradeoffs y publica los
resultados reales de las pruebas.

No añada `Co-Authored-By` ni atribución de IA a los commits.

---

## Sistema de labels

Use estas etiquetas en issues y PRs. La convención combina tipo (`type:*`), estado (`status:*`), prioridad (`priority:*`) y trazabilidad (`gap:legacy`, `audit-*`, `scan-*`).

| Label | Uso |
|---|---|
| `bug` | Defecto verificable en comportamiento actual. |
| `documentation` | Mejora o adición de documentación. |
| `enhancement` | Mejora sobre capacidad existente. |
| `duplicate` | Issue o PR ya reportado. |
| `good first issue` | Tarea apta para contribuidor nuevo. |
| `help wanted` | Requiere atención extra o pairing. |
| `invalid` | No aplica al proyecto; se cierra sin acción. |
| `question` | Pide información; no implica cambio de código. |
| `wontfix` | Revisado y descartado por el maintainer. |
| `status:needs-review` | Espera revisión del maintainer antes de implementación. |
| `status:approved` | El mantenedor autoriza la implementación. |
| `status:in-progress` | La issue ha sido reclamada. |
| `status:blocked` | Espera otra decisión o entrega. |
| `priority:high` | Bug crítico o trabajo urgente. |
| `priority:medium` | Importante pero no bloqueante. |
| `priority:low` | Deseable, no urgente. |
| `type:chore` | Mantenimiento o tooling sin cambio funcional. |
| `type:feature` | Nueva capacidad. |
| `type:docs` | Cambio de documentación. |
| `type:bug` | Corrección de comportamiento. |
| `type:refactor` | Reorganización sin cambio de alcance. |
| `audit-2026-07-25` | Hallazgo del audit completo del 2026-07-25. |
| `audit-2026-07-30` | Hallazgo del audit de capas/tests/specs/observabilidad. |
| `audit-2026-07-30-reverted` | Fix del audit 2026-07-30 revertido en `main` y nunca reaplicado. |
| `scan-2026-08-01` | Hallazgo del sweep estático (pip-audit, ruff extendido, vulture, SonarQube). |
| `size:exception` | Override del presupuesto de 400 líneas por PR. Requiere `size-exception-reason:` en el cuerpo. |

---

## Convención de ramas

El nombre de la rama es la primera señal de intención. El CI valida el patrón `<tipo>/<nº issue>-<kebab-slug>`.

| Tipo | Prefijo | Uso |
|---|---|---|
| Feature | `feat/<issue>-<slug>` | Nueva capacidad de producto. |
| Bug fix | `fix/<issue>-<slug>` | Corrección de comportamiento. |
| Refactor | `refactor/<issue>-<slug>` | Reorganización sin cambio funcional. |
| Documentación | `docs/<issue>-<slug>` | Cambios de docs raíz, `docs/` y skills. |
| CI | `ci/<issue>-<slug>` | Workflows, gates, scripts de CI. |
| Test | `test/<issue>-<slug>` | Solo tests, sin cambio de producto. |
| Rendimiento | `perf/<issue>-<slug>` | Mejora medible de rendimiento. |
| Mantenimiento | `chore/<issue>-<slug>` | Dependencias y tooling. |

El slug va en kebab-case, minúsculas, sin artículos innecesarios. Ejemplo: `feat/552-docs-root-files`.

---

## Convención de commits

Use Conventional Commits en inglés. El header (≤ 72 chars) sigue `<tipo>(<scope>): <imperativo>`. El cuerpo explica el porqué, no el cómo.

| Tipo | Ejemplo | Uso |
|---|---|---|
| `feat` | `feat(animals): add foster override audit endpoint` | Nueva capacidad. |
| `fix` | `fix(csrf): validate token on PATCH routes` | Corrección. |
| `refactor` | `refactor(salud): split routes by sub-resource` | Reorganización. |
| `docs` | `docs(repo): add missing root files` | Cambios de documentación. |
| `test` | `test(entradas): cover batch atomicity edge cases` | Solo tests. |
| `ci` | `ci(lint): pin check_rules detector order` | Workflows y gates. |
| `chore` | `chore(deps): bump fastapi to 0.119` | Mantenimiento. |

No añada `Co-Authored-By` ni atribución de IA. Los mensajes viven en inglés; los documentos raíz en Castellano peninsular formal.

---

## Requisitos del pull request

Un PR se considera mergeable cuando cumple todos los checks bloqueantes. La integración queda en `AGENTS.md` §15.

El cuerpo usa `Closes #N`, `Fixes #N` o `Resolves #N` y declara los comandos
ejecutados con su resultado real en la sección «Comandos ejecutados» de la
plantilla de PR. Indique también cualquier skip, fallo conocido o validación
no aplicable.

| Check requerido | Qué valida | Reproducción local |
|---|---|---|
| `required` | Rollup de `ci.yml`: lint, typecheck, test, integration, security, e2e, build y el resto de jobs. | `make verify` (gates deterministas del job `lint`, `typecheck` y `check-issue-specs` en modo `forms`; incluye `test-ci`) más los comandos de [Validación local](#validación-local) para el resto. |
| `pr-size / pr-size` | Presupuesto de 400 líneas contra la rama base del PR. | `scripts/check_pr_size.py` (el total del diff lo calcula la CI contra `github.base_ref`). |
| `branch-name` | Patrón `<tipo>/<nº issue>-<slug>`. | `scripts/check_branch_name.py`. |
| exactamente un `type:*` en el PR | control manual | El mantenedor lo comprueba antes del merge. |

La validación del enlace issue-PR corre dentro de `ci.yml` (job `issue-spec`) y agrega al rollup `required`. En local, `make check-issue-specs` valida únicamente los formularios de issue (modo `forms`); la comprobación del `Closes #N` y del estado de la issue enlazada consulta la API de GitHub y solo corre en CI.

---

## PR encadenados

Cuando el cambio no cabe en el presupuesto de 400 líneas, divídalo en PR encadenados ([D-35](docs/architecture/decisiones/d-35-presupuesto-400-lineas-pr.md)). Hoy `main` impone a cada tramo estas tres condiciones:

- **Enlace a issue.** El gate `issue-spec` no lee el cuerpo del PR: toma el número `N` de la rama `<tipo>/<N>-<slug>` y exige que la issue `#N` exista, esté abierta, tenga `status:approved` y una spec completa. El cierre es el nativo de GitHub: el gate consulta `closingIssuesReferences` (lo que GitHub cerrará al fusionar) y las etiquetas del PR. Un PR único o el tramo final escribe `Closes #N` y no lleva etiqueta. Un tramo intermedio lleva la etiqueta `chain:partial`, no cierra la issue (use `Refs #N` en el cuerpo) y mantiene el mismo `N` en su rama; con `chain:partial`, un cierre de `#N` falla por cierre prematuro (#931), y sin ella, la ausencia de cierre de `#N` también falla. Cualquier otra issue que el PR cierre debe estar aprobada. No abra sub-issues solo para satisfacer el gate (#954, #955).
- **Tamaño.** `pr-size` mide cada tramo contra su propia rama base (`github.base_ref`), no contra `main`; cada slice paga su propio diff.
- **CI.** Los triggers de `pull_request` de `ci.yml` y de CodeQL filtran por rama base (`main`, `staging`): un tramo cuya base es otro PR encadenado no obtiene run de `ci` hasta que el tramo apunte a `main` **y reciba un push nuevo** (o se lance `ci` a mano): el cambio de rama base por sí solo no dispara el trigger. La eliminación de este filtro está propuesta en #962; planifique la validación final sobre el tramo que apunta a `main`.

---

## Excepción de tamaño

Si el diff supera las 400 líneas y no cabe dividirlo más, pida el label `size:exception` e incluya `size-exception-reason:` con el motivo en el cuerpo del PR.

Añadir (o quitar) el label en un PR ya abierto no recalcula el check requerido `pr-size / pr-size`: el evento `labeled`/`unlabeled` refresca solo el camino directo de `pr-size.yml`, no la llamada desde `ci`. Relance la CI a mano con `gh run rerun <run-id-del-run-de-ci>` (re-ejecuta el run completo, así `pr-size` vuelve a ejecutarse y lee los labels vivos por la API y pone el check en verde). No use `gh workflow run ci.yml --ref <rama>` para esto: en un `workflow_dispatch` el paso de diff corta a `total=0` y el paso de labels se salta (solo corre en `pull_request`), de modo que el check queda verde **sin** evaluar ni el diff ni el label — no es una revalidación. El re-run ve el label añadido; el refresco automático sin intervención manual está pendiente en #941.

Cite la URL del run verde de `ci.yml` en el cuerpo del PR o en el merge commit (premisa de `AGENTS.md` §15.1).

---

## Validación local

Ejecute antes de `git push`. Los comandos siguientes replican los jobs bloqueantes de `ci.yml`; `make verify` agrupa el subconjunto determinista (gates del job `lint`, `typecheck`, `check-issue-specs` en modo `forms` y el ratchet CRAP, que depende de `test-ci`).

```bash
uv sync --frozen --extra dev
source .venv/bin/activate
make verify
```

| Job de `ci.yml` | Comando local | Requisitos |
|---|---|---|
| `lint` | `make verify`; cada gate es además un target individual (`make lint`, `make check-rules`, …) | — |
| `typecheck` | `make typecheck` | — |
| `test` | `make test-ci` | `mdbtools` para los smoke tests de Access; `APAP_TEST_POSTGRES_DSN` opcional y `APAP_TEST_PG_DSN` opcional (sin ellos se saltan los tests que los usan) |
| `integration` | comando siguiente | Postgres real con `APAP_TEST_POSTGRES_DSN` obligatorio |

`make test-ci` replica la invocación exacta del job `test` (cobertura de `app` + `migration` con suelo del 85 %) e ignora `tests/e2e`, `tests/e2e_ci` y `tests/integration`. El job `integration` corre contra un Postgres real:

```bash
export APAP_TEST_POSTGRES_DSN=postgresql://postgres@127.0.0.1:5432/apap_test
export APAP_LOCAL_DB_URL="$APAP_TEST_POSTGRES_DSN"
export APAP_SESSION_SECRET=test-secret-for-ci-only-minimum-32-chars
python -m pytest \
  --override-ini="addopts=-ra --strict-markers --strict-config --randomly-dont-reorganize" \
  -W error::DeprecationWarning \
  --ignore=tests/e2e \
  --no-cov \
  tests/integration \
  -m integration
```

Los jobs que requieren servicios de CI (Postgres efímero, Docker, Chromium, MinIO: `security`, `e2e`, `verify-fallback-ready`, `mutation`, `security-deep`) no se reproducen en una estación de trabajo; `python -m build` cubre la parte reproducible del job `build`.

Las reglas de cada gate viven en `scripts/` y están pinneadas por tests bajo `tests/`. Una regresión en un script de gate trae su propio test.

---

## Control del merge

`main` exige PR, checks verdes y conversaciones resueltas. Solo los roles
`Maintain` y `Admin` pueden mergear; `Write` puede contribuir y revisar, pero no
actualizar la rama protegida.

No se exige una segunda aprobación humana mientras exista un único mantenedor.
Esto no permite omitir CI, hacer push directo ni usar force-push.

El merge conserva `--no-ff` y la rama remota. Consulte
[`docs/codebase/merge-workflow.md`](docs/codebase/merge-workflow.md) y
[`.github/branch-protection.md`](.github/branch-protection.md).

---

## Código de conducta

Sea técnico y directo. Critique el código y la decisión, no a la persona. Las revisiones usan `code-review-expert` (cada slice) y `judgment-day` (alto riesgo: auth, secretos, CSRF, PII, migraciones).

Si una conversación pierde el foco técnico, pause y retome por escrito en la issue o el PR.

## Travesía del contribuidor (vista completa)

Esta sección es el mapa previo del recorrido: qué va a exigirle la CI en cada
etapa, antes de que la encuentre a mitad del camino. El orden es el orden real
de ejecución.

1. **Issue aprobada y con spec completa.** El gate `issue-spec` valida el cuerpo
   de la issue enlazada, no el de la PR: debe declarar las secciones «Problema y
   contexto», «Evidencia verificable», «Alcance y no objetivos», «Plan de
   validación» y «Dependencias y riesgos», tener `status:approved` y la PR debe
   referenciarla con `Closes #N` fuera de bloques de código. Una issue sin estas
   secciones pone la CI en rojo aunque el código sea correcto.
2. **Rama y worktree.** `<tipo>/<nº issue>-<kebab-slug>` desde `main`, en un
   worktree dedicado fuera del repositorio. El nombre lo valida el gate
   `branch-name`.
3. **Firma documental.** La CI ejecuta `check_alantyle` sobre todos los docs:
   castellano peninsular formal (usted) en documentos raíz, inglés en código,
   comentarios y commits. No escriba secuencias en mayúsculas fuera de los
   acróbnimos técnicos admitidos — escriba «false positive», nunca esa
   secuencia en versalitas (fallo real de CI en la PR #1050). No hay firma
   criptográfica de commits exigida:
   Conventional Commits en inglés, sin atribución de IA.
4. **TDD cuando aplique.** RED → GREEN → REFACTOR con los tests junto al código;
   los tests de integración corren contra PostgreSQL real y no cuentan en local
   si falta el DSN (los verá como saltos, no como éxitos).
5. **Batería local antes de `git push`.** La de [Validación local](#validación-local):
   `make verify`, `make typecheck`, `make test-ci`, el comando `integration` con
   su DSN, y `check_alantyle` sobre cada doc que haya tocado. El verde local
   contra una base obsoleta no cuenta: sincronice la rama con `main` antes de
   pedir revisión.
6. **Apertura de PR.** Presupuesto de 400 líneas; si lo supera, divida o pida
   `size:exception` con `size-exception-reason:` en el cuerpo. Recuerde que el
   label sobre una PR abierta no recalcula el check: relance el run de `ci`
   (ver [Excepción de tamaño](#excepción-de-tamaño)).
7. **Ciclos de rebase.** Con merges concurrentes en `main`, espere de dos a
   tres ciclos de «rama por detrás, merge de `main`, CI fresca» por PR.
   Actualice la rama con un merge de `origin/main` (nunca force-push) y espere
   la CI sobre la head nueva.
8. **Cambios high-stakes.** Auth, secretos, CSRF, datos personales o
   migraciones: antes de pedir merge corresponde la doble revisión adversarial
   (judgment-day) con rondas de corrección limitadas. Si el cambio añade una
   variable de entorno o un flag, coordine con el operador su valor en
   producción **antes** del merge: el orden de despliegue es parte del cambio
   (precedente: la PR #1052).
9. **Cierre.** El merge cierra la issue enlazada; el worktree local se poda y
   la rama remota se conserva referenciable.

---

## Checklist del contribuidor

- [ ] La issue usa el formulario correcto, tiene un único `type:*` y está aprobada.
- [ ] Se buscaron duplicados y la issue se reclamó antes de crear la rama.
- [ ] La rama sigue `<type>/<issue>-<slug>` y parte de `main`.
- [ ] El cambio, sus tests y su documentación pertenecen al mismo alcance.
- [ ] El PR tiene una referencia de cierre y resultados reales.
- [ ] El mantenedor confirmó manualmente un único `type:*` en el PR.
- [ ] `make verify` y las pruebas específicas están en verde.
- [ ] El diff no supera 400 líneas o justifica `size:exception` (con `size-exception-reason:` en el cuerpo y el re-run de `ci` si el label se añadió a un PR abierto).
- [ ] Todos los checks y conversaciones están resueltos antes del merge.

## Navegación

Anterior: [README](README.md) | Siguiente: [Proceso por issue](docs/proceso.md)
