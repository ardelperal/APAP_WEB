# Guía de contribución

**Workflow de contribución, label system, convención de rama y commit, y validación local para PRs en APAP_WEB.**

Consulte esta guía antes de abrir un issue o un PR. El contrato completo vive en [`AGENTS.md`](AGENTS.md) y [`docs/proceso.md`](docs/proceso.md).

Esta guía es el subconjunto que un contribuidor externo necesita para arrancar.

---

## Issue-first workflow

Todo cambio en `APAP_WEB` arranca con un issue aprobado. La trazabilidad de cada commit queda atada al número de issue en el nombre de la rama y en el cuerpo del PR.

1. **Abra una issue.** Use el formulario del tipo correspondiente y complete el [contrato issue-as-spec](docs/codebase/issue-specifications.md).
2. **Espere `status:approved`.** El maintainer revisa el issue y aplica la etiqueta cuando lo aprueba para implementación. Las issues con `status:needs-review` requieren conversación previa.
3. **Cree la rama desde `main`.** Nombre siguiendo la convención `<tipo>/<nº issue>-<kebab-slug>` (ver [Branch naming](#branch-naming)).
4. **Implemente con TDD.** Tests primero. Cubra el caso feliz y los bordes. La regla 19 de `AGENTS.md` exige cobertura global ≥ 80% y los `CRITICAL_HELPERS` requieren 100%.
5. **Ejecute la validación local** antes de push (ver [Local validation](#local-validation)).
6. **Abra un PR pequeño.** Cuerpo con `Closes #N` o `Refs #N`. Mantenga el diff bajo el presupuesto de revisión de 400 líneas. Use `size:exception` solo en diffs inevitables.
7. **Espere CI verde.** Los jobs `lint`, `typecheck`, `test` y `build` son bloqueantes; `e2e` y `deploy` son condicional.
8. **Integre con `--no-ff`.** El orquestador tiene autorización vigente (2026-07-26, `AGENTS.md` §15.6) para mergear sin pedir OK por push. La rama remota se conserva; limpie solo el worktree local.

---

## Label system

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

## Branch naming

El nombre de la rama es la primera señal de intención. El CI valida el patrón `<tipo>/<nº issue>-<kebab-slug>`.

| Tipo | Prefijo | Uso |
|---|---|---|
| Feature | `feat/<issue>-<slug>` | Nueva capacidad de producto. |
| Bug fix | `fix/<issue>-<slug>` | Corrección de comportamiento. |
| Refactor | `refactor/<issue>-<slug>` | Reorganización sin cambio funcional. |
| Documentación | `docs/<issue>-<slug>` | Cambios de docs raíz, `docs/` y skills. |
| CI | `ci/<issue>-<slug>` | Workflows, gates, scripts de CI. |
| Test | `test/<issue>-<slug>` | Solo tests, sin cambio de producto. |

El slug va en kebab-case, minúsculas, sin artículos innecesarios. Ejemplo: `feat/552-docs-root-files`.

---

## Commit convention

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

## PR requirements

Un PR se considera mergeable cuando cumple todos los checks bloqueantes. La integración queda en `AGENTS.md` §15.

| Check | Estado | Comando local |
|---|---|---|
| `lint` (ruff + detector propio) | bloqueante | `make lint` |
| `typecheck` (mypy sobre `app/` y `migration/`) | bloqueante | `make typecheck` |
| `test` (pytest con `DeprecationWarning` como error) | bloqueante | `make test` |
| `build` (`python -m build`) | bloqueante | `make build` |
| `e2e` (Playwright) | condicional | salta cuando faltan secrets OAuth |
| `deploy` (webhook Coolify) | condicional | salta en merge commits y cuando no hay webhook |
| branch-name pattern | bloqueante | `scripts/check_branch_name.py` |
| PR size ≤ 400 líneas | bloqueante | `scripts/check_pr_size.py` |
| issue spec vinculada | bloqueante | `scripts/check_issue_specs.py pr-event "$GITHUB_EVENT_PATH"` |

Cite la URL del run verde de `ci.yml` en el cuerpo del PR o en el merge commit (premisa de `AGENTS.md` §15.1).

---

## Local validation

Ejecute antes de `git push`. El set mínimo es `make verify` (lint + check-rules + check-module-size + check-route-size + check-layers). El set extendido añade tests y build.

```bash
# Set mínimo (rápido, recomendado antes de cada commit)
make verify

# Set extendido (necesario antes de abrir PR)
python -m pytest -W error::DeprecationWarning \
    --ignore=tests/e2e \
    --deselect tests/test_voluntarios_concurrent.py
python -m build
```

Las reglas de cada gate viven en `scripts/` y están pinneadas por tests bajo `tests/`. Una regresión en un script de gate trae su propio test.

---

## Code of conduct

Sea técnico y directo. Critique el código y la decisión, no a la persona. Las revisiones usan `code-review-expert` (cada slice) y `judgment-day` (alto riesgo: auth, secretos, CSRF, PII, migraciones).

Si una conversación pierde el foco técnico, pause y retome por escrito en la issue o el PR.

[← Back to README](README.md) · [Next: CHANGELOG →](CHANGELOG.md)
