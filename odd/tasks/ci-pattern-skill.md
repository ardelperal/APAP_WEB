# Skill ci-pattern — destilación de la épica de CI (§8 del handoff)

> **Retirado (2026-10-01, #1233):** el espejo `skills/ci-pattern/` se eliminó de
> este repo — `ci-pattern` es una herramienta con interfaz de skill, no una
> convención a vendorizar; se usa a demanda por su CLI
> (`~/.agents/skills/ci-pattern/assets/bin/ci-pattern`, contrato en
> `references/cli-spec.md` del canónico). Este documento se conserva como
> registro histórico de su creación y de los PRs de sync que motivaron la baja.

**Claimed:** 2026-09-30. Escritura de `skills/ci-pattern/` con su registro en
AGENTS.md y skills/README.md, cerrando el entregable §8 de
`odd/HANDOFF-ci-2026-09-30.md`.

## Root-cause position (verified)

La épica #935 acumuló 18 reglas pagadas con rojos reales
(`odd/skill-ci-portable/ci-playbook.md`), 14 reglas de diseño con evidencia
(`odd/skill-ci-portable/source-notes.md`, incluida la R15 añadida en sesión:
gates dormidos tras policy file, no retirados) y un benchmark de otro CI
(`gentle-ai-ci-research-report.md`). Ese material estaba disperso en `odd/` y
sin versión: la skill lo empaqueta parameterizado para otro repo.

## Tasks

- [x] `skills/ci-pattern/SKILL.md` — skill-style-guide: frontmatter prescrito,
  §1-§8 canónicos, HR-1 a HR-18 trazables a evidencia, decision gates,
  anti-patterns en tabla, output contract; 245 líneas.
- [x] `skills/ci-pattern/assets/parameters.md` — los ocho parámetros extraíbles
  por repo + forma del policy file de gates dormibles (R15) + scripts de
  referencia.
- [x] `skills/ci-pattern/references/fricciones.md` — catálogo destilado con
  antídoto (25 entradas trazables a #935/#4368/F-001-F-007).
- [x] `skills/ci-pattern/references/gate-verdicts.md` — veredicto por gate
  (se queda / se refuerza / se duerme / falta) con base.
- [x] `skills/ci-pattern/references/benchmark-gentle-ai.md` — T1-T9, COL1-COL5,
  NC1-NC6 y claims verificados/no verificados.
- [x] Registro en AGENTS.md §Project-context skills y skills/README.md.

## Evidence

- `python3 scripts/check_alantyle.py skills/ci-pattern/` → `OK (5 archivos)`,
  exit 0 (2026-09-30).
- Body de SKILL.md: 245 líneas, bajo el budget de 700 de skill-style-guide.
- Trazabilidad HR-N: cada HR cita su fricción o regla de origen (R2-R15,
  A9/A11/B1-B13, F-001-F-007, playbook reglas 1-18, benchmark T1/T7).
- Los scripts referenciados existen: `scripts/preflight.py`,
  `check_pr_size.py`, `check_issue_specs.py`, `check_required_jobs.py`,
  `check_release_evidence.py`, `check_release_e2e_required.py`,
  `production_smoke.py`, `.github/release-e2e-paths.txt`.

## Pendiente (fuera de este PR)

- Referencias a `odd/skill-ci-portable/` siguen siendo fuentes de trabajo sin
  versionar; si se versionan, actualizar los punteros de `references/`.
- Criterios 3, 4, 5 y 7 de la definición de «hecho» del handoff §8 siguen
  pendientes y son previos a declarar el patrón «adoptado» en un segundo repo.
