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

Todo cambio humano en `APAP_WEB` sigue este ciclo:

1. **Busque antes de crear.** Revise issues abiertas y cerradas; use la existente si ya cubre el problema.
2. **Abra una issue si falta.** Use el formulario correcto y complete el [contrato issue-as-spec](docs/codebase/issue-specifications.md).
3. **Espere `status:approved`.** Solo el mantenedor autoriza la implementación.
4. **Reclame la issue.** Comente que va a trabajar en ella y compruebe que nadie la ha reclamado antes.
5. **Cree la rama desde `main`.** Use `<type>/<issue>-<slug>` (ver [Convención de ramas](#convención-de-ramas)).
6. **Implemente con TDD.** La cobertura global es ≥ 85%; los `CRITICAL_HELPERS` exigen 100%.
7. **Valide localmente.** Ejecute los comandos aplicables antes del push.
8. **Abra un PR honesto.** Incluya referencia de cierre, validación real y un diff ≤ 400 líneas. El mantenedor comprueba manualmente que lleva exactamente un label `type:*`.
9. **Espere CI verde.** `ci / required`, `pr-name / branch-name` y `pr-size / pr-size` son bloqueantes.
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
ejecutados con su resultado real. Indique también cualquier skip, fallo conocido
o validación no aplicable.

| Check | Estado | Comando local |
|---|---|---|
| `ci / required` | bloqueante | `make verify` como subconjunto local |
| `pr-name / branch-name` | bloqueante | `scripts/check_branch_name.py` |
| `pr-size / pr-size` | bloqueante | `scripts/check_pr_size.py` |
| issue spec vinculada | agregada por `required` | Sin equivalente local; CI consulta la API de GitHub. |
| exactamente un `type:*` en el PR | control manual | El mantenedor lo comprueba antes del merge. |

Cite la URL del run verde de `ci.yml` en el cuerpo del PR o en el merge commit (premisa de `AGENTS.md` §15.1).

---

## Validación local

Ejecute antes de `git push`. `make verify` cubre el subconjunto determinista
local. CI añade PostgreSQL, Docker y Chromium.

```bash
uv sync --frozen --extra dev
make verify
python -m build
```

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

## Checklist del contribuidor

- [ ] La issue usa el formulario correcto, tiene un único `type:*` y está aprobada.
- [ ] Se buscaron duplicados y la issue se reclamó antes de crear la rama.
- [ ] La rama sigue `<type>/<issue>-<slug>` y parte de `main`.
- [ ] El cambio, sus tests y su documentación pertenecen al mismo alcance.
- [ ] El PR tiene una referencia de cierre y resultados reales.
- [ ] El mantenedor confirmó manualmente un único `type:*` en el PR.
- [ ] `make verify` y las pruebas específicas están en verde.
- [ ] El diff no supera 400 líneas o justifica `size:exception`.
- [ ] Todos los checks y conversaciones están resueltos antes del merge.

## Navegación

Anterior: [README](README.md) | Siguiente: [Proceso por issue](docs/proceso.md)
