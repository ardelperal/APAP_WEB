# Cancellation Notice — SDD `adopt-02-expiry`

**Date:** 2026-07-10
**Cancelling change:** `correct-preadoption-legacy-provenance`
**Reason:** Invalid legacy provenance. The 20-day decision clause belongs to foster care
(`APAP_ACTUAL/src/classes/Plantilla.cls`, `RellenarContratoAcogida`, lines 381-391), NOT to
pre-adoption lifecycle. Pre-adoption remains active until definitive adoption or explicit
return, governed by `FDevolucion IS NULL` (`Adopcion.cls`, `AnimalConAdopcionesActivas`,
lines 1991-2054). No automatic expiry, no timer, no worker, no notification. The runtime
registry (`Entorno.cls` L793) selects the same `CONTRATO DE ADOPCIÓN_V02.docx` for both
Adopción and PreAdopción; `RellenarContratoPreAdopcion` (`Plantilla.cls` L620-689) contains
no one-month or other automatic timer.

## Intended vs evidence-backed state

This notice records the cancellation of `adopt-02-expiry` / GitHub issue #48 with two
distinct columns. **Intended** items are not yet performed by the apply phase. **Evidence-backed**
items are already done and the evidence is listed.

| Artifact | State | Intended vs evidence-backed | Evidence |
|---|---|---|---|
| `feat/adopt-02-expiry` branch | KEPT at `40ce83f` (not deleted) | Evidence-backed | local git |
| `stash@{0}: adopt-02-invalid-work-2026-07-10` | KEPT (not popped, not dropped) | Evidence-backed | local git stash |
| Local-main 3 invalid commits (`2ea1765`, `be43c14`, `40ce83f`) | KEPT ahead of `origin/main` | Evidence-backed | local `main`; not cherry-picked into this change |
| `openspec/changes/adopt-02-expiry/` OpenSpec tree | KEPT on `feat/adopt-02-expiry` | Evidence-backed | not present on `docs/correct-preadoption-legacy-provenance` |
| Engram (5 cancellation topic keys) | `superseded` / `cancellation` notes | Evidence-backed | Engram observations #16694 (`proposal`), #16695 (`spec`), #16696 (`design`), #16697 (`tasks`), #16698 (`apply-progress`) |
| Engram `correct-preadoption-legacy-provenance/apply-progress` | Cumulative apply trace | Evidence-backed | Engram observation #16699 |
| Engram session summary | Session context retained | Evidence-backed | Engram observations #16706, #16712 |
| ADOPT-01 invariants preserved | `TipoAdopcion`, manual contracts, sterilization, return through `FDevolucion` only | Evidence-backed | `python -m pytest tests/test_adopciones.py tests/test_adopciones_routes.py tests/test_domain.py::test_adopciones_create_table_sql_columns -q` → 66 passed in ~1.0s |
| `ruff check .` on this branch | Lint clean | Evidence-backed | exit 0, all checks passed |
| GitHub issue #48 cancellation comment | Body file ready; **PENDING post** | Intended | Body-only payload at `openspec/changes/correct-preadoption-legacy-provenance/.comment-for-issue-48.md` (stable marker `<!-- cancellation-marker:adopt-02 -->`). Orchestrator runs `gh issue comment 48 --body-file <path>` post-PR-review. |
| Pull request to `main` | **PENDING push + open** | Intended | Branch `docs/correct-preadoption-legacy-provenance` is 7 commits ahead of `origin/main` (`071aaeb`); no `gh pr create` run yet |
| PR-merge closeout comment on issue #48 | **PENDING** | Intended | Requires PR URL; produced at close-with-evidence time per `docs/proceso.md` P3 |

## ADOPT-01 invariants preserved (NOT changed by this cancellation)

1. `TipoAdopcion` enum (regular / preadopcion / judicial)
2. Manual contracts and follow-up (no automation)
3. Sterilization commitment and formalization (`donativo_preadopcion` / `donativo_adopcion`)
4. Return through `FDevolucion` only (no state derivation from elapsed time)

## Rollback and Engram compensation/reconciliation

This change is documentation-only — there is no product code, no migration, no test, and no
expiry-worker to roll back. The corrective documentation can be reverted by `git revert` of
the 7 commits on this branch.

**Engram is a persistent memory store and CANNOT be transactionally reverted by this
change.** The five cancellation observations (#16694-#16698) and the apply-progress
observation (#16699) remain valid as historical evidence of the cancellation decision,
even if the cancellation itself is later re-opened. Compensation is by **re-save, not by
delete**: if a future change re-opens the topic, it MUST record a new observation under
the same `topic_key` (upsert) with a `superseded by <new change>` note pointing at the
new lineage. The historical record stays intact for forensic traceability. **Do not
attempt to delete or rewrite past Engram observations to "undo" a cancellation.**

## External follow-up (NOT in this change)

`APAP_ACTUAL/docs/` contains equivalent false references and requires a separate repository PR
(see design §8).
