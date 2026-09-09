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

Todo cambio en `APAP_WEB` arranca con un issue aprobado. La trazabilidad de cada commit queda atada al número de issue en el nombre de la rama y en el cuerpo del PR.

1. **Abra una issue.** Use el formulario del tipo correspondiente y complete el [contrato issue-as-spec](docs/codebase/issue-specifications.md).
2. **Espere `status:approved`.** El maintainer revisa el issue y aplica la etiqueta cuando lo aprueba para implementación. Las issues con `status:needs-review` requieren conversación previa.
3. **Cree la rama desde `main`.** Nombre siguiendo la convención `<tipo>/<nº issue>-<kebab-slug>` (ver [Convención de ramas](#convención-de-ramas)).
4. **Implemente con TDD.** Tests primero. Cubra el caso feliz y los bordes. La regla 19 exige cobertura global ≥ 85% y 100% para los `CRITICAL_HELPERS`.
5. **Ejecute la validación local** antes de push (ver [Validación local](#validación-local)).
6. **Abra un PR pequeño.** Cuerpo con `Closes #N`, `Fixes #N` o `Resolves #N`. Mantenga el diff bajo el presupuesto de revisión de 400 líneas. Use `size:exception` solo en diffs inevitables.
7. **Espere CI verde.** `ci / required`, `pr-name / branch-name` y `pr-size / pr-size` son bloqueantes.
8. **Integre con `--no-ff`.** El orquestador tiene autorización vigente (2026-07-26, `AGENTS.md` §15.6) para mergear sin pedir OK por push. La rama remota se conserva; limpie solo el worktree local.

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
| `status:approved` | Aprobado para implementación. |
| `status:in-progress` | Tiene una persona trabajando en ella. |
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

| Check | Estado | Comando local |
|---|---|---|
| `ci / required` | bloqueante | `make verify` como subconjunto local |
| `pr-name / branch-name` | bloqueante | `scripts/check_branch_name.py` |
| `pr-size / pr-size` | bloqueante | `scripts/check_pr_size.py` |
| issue spec vinculada | agregada por `required` | Sin equivalente local; CI consulta la API de GitHub. |

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
- [ ] La rama sigue `<type>/<issue>-<slug>` y parte de `main`.
- [ ] El cambio, sus tests y su documentación pertenecen al mismo alcance.
- [ ] `make verify` y las pruebas específicas están en verde.
- [ ] El PR cierra la issue y respeta el límite o justifica `size:exception`.
- [ ] Todos los checks y conversaciones están resueltos antes del merge.

## Navegación

Anterior: [README](README.md) | Siguiente: [Proceso por issue](docs/proceso.md)
