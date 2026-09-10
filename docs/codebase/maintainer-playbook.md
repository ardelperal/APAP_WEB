# Maintainer playbook

[Back to Codebase Guide](../CODEBASE-GUIDE.md)

Esta página posee el workflow operativo de mantenedor: pre-flight, triaje, SDD, TDD, validación local, merge, cierre con trazabilidad y sync del roadmap. No posee las reglas del proyecto — esas viven en [AGENTS.md](../../AGENTS.md) §15 y §16 — ni el contrato del stack — eso es [Arquitectura LocalBackend](../architecture/architecture-local-backend-stack.md).

## Core invariants

- **Pre-MVP single-branch**: todo trabajo aterriza en `main`; no se crea ni persiste `staging` (AGENTS §15.2).
- **Trazabilidad por SHA**: el cierre de la issue cita commit SHA y path de test; el roadmap se refresca en la misma sesión (AGENTS §16).
- **P1 fidelidad al legacy**: cualquier cambio se valida primero contra el Access original; las brechas se abren como `gap:legacy` (P1 en [proceso.md](../proceso.md)).
- **Revisión con lentes obligatorias**: cada slice ejecuta `code-review-expert`; los slices de alto riesgo ejecutan además `judgment-day` (AGENTS §17.2).
- **Standing merge autorizado**: en pre-MVP el orquestador puede mergear a `main` cuando los gates están verdes y cita el `ci.yml` run URL (AGENTS §15.6).

## Workflow por issue (per docs/proceso.md)

| Step | Acción | Referencia |
|---|---|---|
| 1. Pre-flight | `codegraph status .`, `git status --short --branch`, `git branch --show-current` | [proceso.md](../proceso.md) §1 |
| 2. Triaje | Clasificar la issue (`feature` / `bug` / `refactor` / `docs`), refrescar el roadmap si cambia el alcance | [proceso.md](../proceso.md) §2 |
| 3. SDD o directo | Si el cambio es grande o estructural, abrir `openspec/changes/<name>/` con `propose.md`, `design.md`, `tasks.md` | [proceso.md](../proceso.md) §3 |
| 4. TDD | Rojo → verde → refactor; tests de slice nuevo en `tests/`; E2E si toca UI (§23) | [proceso.md](../proceso.md) §4 |
| 5. Validación local | `pytest -W error::DeprecationWarning`, `ruff check .`, `python scripts/check_rules.py .`, gates de tamaño y capas | [proceso.md](../proceso.md) §5 |
| 6. PR y CI | Push a `docs/<scope>` o `feat/<scope>`, abrir PR con Conventional Commits en inglés y exactamente una etiqueta `type:*` | [proceso.md](../proceso.md) §6, AGENTS §15.2 |
| 7. Merge | Cuando los gates están verdes y §15.6 lo autoriza; merge con `--no-ff`, sin `--delete-branch`; cita el `ci.yml` run URL en el cuerpo | [proceso.md](../proceso.md) §6, AGENTS §15.6 |
| 8. Cierre con trazabilidad | Comentario de cierre con commit SHA, path de test, ruta de doc afectada; refrescar [roadmap.md](../roadmap.md) en la misma sesión | [proceso.md](../proceso.md) §6 |

## Checklists por tipo de cambio

| Tipo | Checklist |
|---|---|
| `type:feature` | [ ] Spec en `openspec/specs/<slice>/spec.md` o `propose.md` en `openspec/changes/<name>/`. [ ] Tests rojos primero (TDD). [ ] Si toca UI: E2E en `tests/e2e/`. [ ] Si toca auth/secretos/CSRF/PII/migración: audit en [`docs/audits/`](../../docs/audits/). |
| `type:bug` | [ ] Reproducir con test rojo antes del fix. [ ] Si rompe P1 (fidelidad legacy): label `gap:legacy`. [ ] Si toca un path sensible: audit y runbook asociados. [ ] Cita SHA + path de test en el comentario de cierre. |
| `type:refactor` | [ ] Sin cambio de comportamiento; los tests existentes siguen verdes. [ ] Si toca un módulo en `app/modules/` y lo mueve a hexagonal, sigue §33.3. [ ] Si rompe el ratchet de tamaño, el `BASELINE` decrece (no crece) (§21, §28). |
| `type:docs` | [ ] Sigue el contrato de la skill [documentation-alan-style](../../../../../../.config/opencode/skills/documentation-alan-style/SKILL.md). [ ] Sin emojis, sin marketing fluff, párrafos < 200 chars. [ ] Castellano peninsular formal, usted. |

## Gates locales pre-push

| Gate | Comando | Source of truth |
|---|---|---|
| Tests con DeprecationWarning como error | `python -m pytest -W error::DeprecationWarning` | AGENTS §15.1, §19 |
| Lint ruff | `ruff check .` | AGENTS §20 |
| Lint AGENTS (APAP001/APAP003 + detectores 2–12) | `python scripts/check_rules.py .` | AGENTS §20 |
| Tamaño de módulo | `python scripts/check_module_size.py` | AGENTS §21 |
| Tamaño de route | `python scripts/check_route_size.py` | AGENTS §28 |
| Capas y slices | `python scripts/check_layers.py` | AGENTS §33 |
| Docstrings sincronizados | `python scripts/check_docstring_coverage.py` | AGENTS §30 |
| Typecheck mypy | `python -m mypy` | AGENTS §24 |
| Cobertura ≥ 85% global + 100% CRITICAL_HELPERS | pytest con `--cov-fail-under=85` + gate plugin | AGENTS §11, §19 |

## Contributor checklist

- [ ] Antes de abrir el PR, ejecute el gate local completo de la tabla anterior; no empuje con un gate rojo.
- [ ] Antes de mergear, confirme que el comentario de cierre cita el SHA del commit y el path del test, y que el [roadmap.md](../roadmap.md) está sincronizado con el cambio.
- [ ] Antes de declarar un cambio como `type:refactor`, confirme que no hay cambio de comportamiento mediante tests que sigan verdes sin modificación.
- [ ] Antes de etiquetar como `size:exception`, confirme que la división en chained PRs no es viable; cite el motivo en el PR.
- [ ] Si el diff toca `AGENTS.md`, `docs/proceso.md`, `docs/roadmap.md`, `docs/audits/*`, `docs/runbooks/*` o `docs/uat/*`, el cambio pasa por el flow de §17.3 (delegación a subagente, PR separado).

## Navigation

Previous: [Integrations](integrations.md) | Next: [Sync and cloud](sync-and-cloud.md)