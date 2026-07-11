# Tasks: Correct Pre-Adoption Legacy Provenance

## Summary

7 tasks. All are docs-only corrections to remove the false claim that pre-adoptions expire
automatically after 20 days (a foster-care clause at `Plantilla.cls` L381-391 misattributed to
pre-adoption). One PR from `docs/correct-preadoption-legacy-provenance` → `main` was forecast.
The reconciliation audit found a raw branch diff of 1,382 additions and 540 deletions because
Task 1 normalized line endings and the SDD planning artifacts add 698 lines. No product code,
no migrations, no tests touched. ADOPT-01 invariants
in `tests/test_adopciones*` and `tests/test_domain.py` are explicitly out of scope and untouched.

---

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Original estimate | ~130 lines |
| Audited raw branch diff | 1,382 additions / 540 deletions |
| 400-line budget risk | **High in raw review diff** — semantic product-doc edits are surgical, but Task 1 contains line-ending normalization and three SDD planning artifacts add 698 lines |
| Chained PRs recommended | **Review decision required** — the original single-PR forecast no longer matches the actual diff |
| Suggested split | Pending mandatory review; do not open the PR until the raw-diff inflation is resolved or explicitly accepted |
| Delivery strategy | Originally `single-pr`; reconciliation routes to review before PR creation |
| Chain strategy | `stacked-to-main` |

**Reconciliation note:** The pre-apply decision was based on the ~130-line estimate. The actual
raw diff exceeds the budget, so review must resolve the line-ending/planning-artifact inflation
before PR creation. This pass does not rewrite commits or choose a size exception.

```
Decision needed before PR creation: Yes (review actual raw diff)
Chained PRs recommended: Pending review
Chain strategy: stacked-to-main
400-line budget risk: High in raw diff
```

---

## Task Inventory

### Task 1: `docs(discovery): correct pre-adoption lifecycle — remove invented Vencido state`

**Status:** [x] Complete in `6f86112` (semantic diff verified with end-of-line noise ignored).

**Files:**
- `docs/discovery/state-machines.md`
- `docs/discovery/data-model-completeness.md`

**Edits:**
- `state-machines.md` L111: `"from draft to signed or expired"` → `"from draft to signed (no automatic expiry)"`
- `state-machines.md` L120: Remove the entire `| Vencido | Contract has expired (e.g., pre-adoption 20-day window lapsed) |` row
- `state-machines.md` L129: Remove the `| Pendiente de Firma | Vencido | Signature deadline lapsed (pre-adoption: 20 days) |` row
- `state-machines.md` L132: Remove the `| Vencido | — | Terminal; new contract may be generated if needed |` row
- `state-machines.md` L143: `| PreAdopción | ... | 20-day decision window |` → `| PreAdopción | ... | None (manual close via definitive adoption or return through FDevolucion) |`
- `data-model-completeness.md` L273: Remove the `| Pre-adoption expiry (20-day window) | Application-only (date calculation) | Service layer + scheduled job |` row entirely (renumber remaining rows as needed); add footnote: *"Pre-adoption has no runtime expiry — activity is `FDevolucion IS NULL` (Adopcion.cls L2047-2054). The 20-day clause is foster-contract text (Plantilla.cls L381-391)."*

**Commit:** `docs(discovery): correct pre-adoption lifecycle — remove invented Vencido state`

**Verification:**
```bash
rg -i -n '\bVencido\b' docs/discovery/state-machines.md
# Expected: 0 matches (L120 row removed)

rg -i -n '20.días|20 days' docs/discovery/
# Expected: 0 matches in state-machines.md and data-model-completeness.md

rg -i -n 'pre-adoption expiry|pre-adopción expira' docs/discovery/
# Expected: 0 matches (data-model-completeness.md L273 removed)
```

**Risk:** Low. Pure documentation removal; no code, no tests.

**Review lens:** `code-review-expert`

---

### Task 2: `docs(discovery): correct pre-adoption contract clause — 20-day → one-month post-sterilization`

**Status:** [x] Complete in `d3043b2`.

**Files:**
- `docs/discovery/feature-04-documents-contracts-reports.md`

**Edits:**
- `feature-04-documents-contracts-reports.md` L74: `| Pre-adoption | 20-day decision clause in pre-adoption contracts |` → `| Pre-adoption | One-month post-sterilization signing clause (contract text, not runtime) | —` plus footnote: *"The 20-day decision clause belongs to foster contracts (Plantilla.cls, RellenarContratoAcogida, L381-391), not pre-adoption."*
- `feature-04-documents-contracts-reports.md` L84: `| PreAdopción | ... | 20-day decision clause | — |` → `| PreAdopción | ... | One-month post-sterilization signing clause | — |`

**Commit:** `docs(discovery): correct pre-adoption contract clause — 20-day → one-month post-sterilization`

**Verification:**
```bash
rg -i -n '20.días|20 days' docs/discovery/feature-04-documents-contracts-reports.md
# Expected: 0 matches

rg -i -n 'preadopción' docs/discovery/feature-04-documents-contracts-reports.md
# Expected: matches at L74 and L84 with corrected "One-month post-sterilization" text
```

**Risk:** Low. Docs-only.

**Review lens:** `code-review-expert`

---

### Task 3: `docs(roadmap): cancel ADOPT-02 from roadmap — invalid legacy provenance`

**Status:** [x] Complete in `fe3ce54`.

**Files:**
- `docs/roadmap.md`
- `README.md`

**Edits:**
- `roadmap.md` L16: `ADOPT-02..03 🔲 (#48..#49)` → `ADOPT-03 🔲 (#49)`
- `roadmap.md` L132: `ADOPT-02..03 🔲 (#48..#49)` → `ADOPT-03 🔲 (#49)`
- `roadmap.md` L259: Replace the `| #48 | ADOPT-02: expiración de pre-adopción tras ventana de 20 días | Fase 5c | 🔲 |` row with `| #48 | ~~ADOPT-02: expiración...~~ **CANCELADO** por provenancia inválida — cláusula de 20 días = foster (`Plantilla.cls` L381-391), no pre-adopción. Ref `correct-preadoption-legacy-provenance`. | — | ❌ |`
- `README.md` L68: `**Adoptions**: ADOPT-02 20-day pre-adoption expiry, ADOPT-03 4-state follow-up state machine (#48, #49).` → `**Adoptions**: ADOPT-03 4-state follow-up state machine (#49). ADOPT-02 (#48) cancelled for invalid legacy provenance — see `openspec/changes/correct-preadoption-legacy-provenance/`.`

**Commit:** `docs(roadmap): cancel ADOPT-02 from roadmap — invalid legacy provenance`

**Verification:**
```bash
rg -i -n 'ADOPT-02' docs/roadmap.md README.md
# Expected: only the CANCELADO row text referencing the strikethrough "ADOPT-02" remains

rg -i -n '20.días|20 days' docs/roadmap.md
# Expected: 0 matches in normative scope (the CANCELADO row contains it but is non-operative; acceptable)
```

**Risk:** Low. Docs-only.

**Review lens:** `code-review-expert`

---

### Task 4: `docs(showcase): remove Vencido state and 20-day pre-adoption claims from contract lifecycle`

**Status:** [x] Complete in `63ea18e`.

**Files:**
- `docs/features-showcase.html`

**Edits:**
- `features-showcase.html` L537: `<td>Acuerdo con cláusula de 20 días</td>` → `<td>Cláusula de firma un mes post-esterilización (texto de contrato)</td>`
- `features-showcase.html` L605: `<td>Cláusula de decisión de 20 días</td>` → `<td>Cláusula de firma un mes post-esterilización (texto de contrato)</td>`
- `features-showcase.html` L672: Remove the entire `<div class="state terminal" data-state="vencido" onclick="showTransitions('contract', this)">Vencido</div>` div
- `features-showcase.html` L941: `'pendiente-firma': ['Firmado', 'Vencido', 'Anulado']` → `'pendiente-firma': ['Firmado', 'Anulado']`
- `features-showcase.html` L943: Remove `'vencido': ['— Terminal —']` entirely

**Commit:** `docs(showcase): remove Vencido state and 20-day pre-adoption claims from contract lifecycle`

**Verification:**
```bash
rg -i -n '\bVencido\b|vencido' docs/features-showcase.html
# Expected: 0 matches (L672 div and L941/L943 transitions removed)

rg -i -n '20.días|20 days' docs/features-showcase.html
# Expected: 0 matches (L537 and L605 corrected)
```

**Risk:** Low. HTML docs-only.

**Review lens:** `code-review-expert`

---

### Task 5: `docs(correct-preadoption): add cancellation record and proposal banner`

**Status:** [x] Complete in `1cb67f8`. Review remains pending; the cancellation record's
issue-comment row describes the intended final state and is not evidence that the comment was posted.

**Files:**
- `openspec/changes/correct-preadoption-legacy-provenance/CANCELLATION.md` (create)
- `openspec/changes/correct-preadoption-legacy-provenance/proposal.md` (edit — prepend banner)

**Edits:**
- Create `CANCELLATION.md` with the full cancellation record: reason, forensic retention table, ADOPT-01 invariants preserved, external-work follow-up note. Template per design.md §4.2.
- Prepend the 4-line cancellation banner above the existing `# Proposal:` heading in `proposal.md`. Template per design.md §4.1.

**Commit:** `docs(correct-preadoption): add cancellation record and proposal banner`

**Verification:**
```bash
test -f openspec/changes/correct-preadoption-legacy-provenance/CANCELLATION.md && echo "EXISTS"

rg -i 'CANCELLATION|cancelled|invalid provenance' openspec/changes/correct-preadoption-legacy-provenance/CANCELLATION.md
# Expected: multiple matches (cancellation record is self-referential)

rg -i 'CANCELLATION SCOPE' openspec/changes/correct-preadoption-legacy-provenance/proposal.md
# Expected: ≥1 match (banner prepended)
```

**Risk:** Medium. Creates an OpenSpec traceability artifact; judgment-day is mandatory per design §9.

**Review lens:** `code-review-expert` + `judgment-day` (AGENTS.md §17.2: OpenSpec change artifact + issue traceability)

---

### Task 6: `docs(correct-preadoption): post cancellation comment to GitHub issue #48`

**Status:** [ ] Pending PR URL. The body-only payload is ready at
`openspec/changes/correct-preadoption-legacy-provenance/.comment-for-issue-48.md` with a
stable HTML comment marker `<!-- cancellation-marker:adopt-02 -->`. The apply phase does
NOT post to GitHub. The orchestrator runs the idempotent post only after the PR URL exists
and a single pre-post `gh issue view 48 --json comments` search confirms the marker is not
already present.

**Files:** None (gh issue comment only — body file already on disk)

**Edits:**
- Idempotent post: `gh issue view 48 --json comments --jq '.comments[].body' | rg -F '<!-- cancellation-marker:adopt-02 -->'`
  and stop if a hit is found (already posted).
- Otherwise: `gh issue comment 48 --body-file openspec/changes/correct-preadoption-legacy-provenance/.comment-for-issue-48.md`.
- After posting, capture the comment URL/id for the closeout follow-up reply at PR-merge time.

**Commit:** `docs(correct-preadoption): post cancellation comment to GitHub issue #48`

**Verification:**
```bash
gh issue view 48 --json comments --jq '.comments[-1].body' | rg -F '<!-- cancellation-marker:adopt-02 -->'
# Expected: 1 match (the marker is the first line of the posted body).
```

**Risk:** Medium. Touches GitHub issue traceability (AGENTS.md §17.2 high-stakes mapping: issue comment on #48).

**Review lens:** `code-review-expert` + `judgment-day` (AGENTS.md §17.2: issue traceability)

---

### Task 7: `docs(correct-preadoption): update Engram observations — ADOPT-02 cancelled; record external-work stub`

**Status:** [x] Complete (reconciliation evidence, performed in the same apply pass as
Tasks 1–5, NOT after the PR opens or merges). The five cancellation observations plus the
cumulative apply-progress observation were upserted in Engram by the previous apply pass
and remain the canonical record.

**Files:** Engram only (no source files edited)

**Edits — performed in Engram (observation IDs):**

| topic_key | type | Engram ID | What was saved |
|---|---|---|---|
| `sdd/adopt-02-expiry/proposal` | `decision` | #16694 | `superseded by correct-preadoption-legacy-provenance; provenance invalid (20-day foster ≠ pre-adoption expiry). Legacy: APAP_ACTUAL/src/classes/Plantilla.cls RellenarContratoAcogida L381-391.` |
| `sdd/adopt-02-expiry/spec` | `decision` | #16695 | `superseded; no automatic pre-adoption expiry exists in legacy. Activity is derived from FDevolucion IS NULL (Adopcion.cls L2047-2054).` |
| `sdd/adopt-02-expiry/design` | `architecture` | #16696 | `superseded by correct-preadoption-legacy-provenance; design not adopted; no timer, no worker, no scheduled job was ever required.` |
| `sdd/adopt-02-expiry/tasks` | `decision` | #16697 | `cancelled without execution; tasks.md never produced.` |
| `sdd/adopt-02-expiry/apply-progress` | `discovery` | #16698 | `audit found invalid work in commits 2ea1765/be43c14/40ce83f on feat/adopt-02-expiry + stash@{0}; not present on origin/main (071aaeb); cancellation marker in CANCELLATION.md.` |
| `sdd/correct-preadoption-legacy-provenance/apply-progress` | `architecture` | #16699 | Cumulative apply trace for this change (7 commits, 8 docs files, 4 Engram topics superseded, etc.). |
| `sdd/correct-preadoption-legacy-provenance/session-summary` | `session_summary` | #16706 | Session summary for the apply pass. |
| `sdd/correct-preadoption-legacy-provenance/resume-point` | `decision` | #16712 | Resume point for the next session. |

**Note:** Engram is persistent and CANNOT be transactionally reverted. The observations
above stay as historical evidence even if this cancellation is later re-opened.
Compensation is by re-save (upsert with `superseded by` note), not by delete. See
`CANCELLATION.md` "Rollback and Engram compensation/reconciliation".

**External-work follow-up draft (recorded in Engram observation #16699, NOT a file commit):**
```
APAP_ACTUAL external-work draft:
Title: Correct pre-adoption 20-day expiry false claim in APAP_ACTUAL docs
Body: Apply same corrections as correct-preadoption-legacy-provenance to:
- APAP_ACTUAL/docs/ (equivalent false references in state machine, contract types, data model)
- APAP_ACTUAL/src/classes/Plantilla.cls (correct any comment suggesting pre-adoption expiry)
- APAP_ACTUAL/src/classes/Adopcion.cls (correct any comment suggesting automatic expiry)
Note: Funciones Generales.bas requires no corrections (grep returned no false claims).
```

**Commit:** `docs(correct-preadoption): update Engram observations — ADOPT-02 cancelled`
(landed in `d08ee0c`)

**Verification:**
```bash
# Re-confirm each observation exists and is reachable:
mem_get_observation(id: 16694)  # proposal
mem_get_observation(id: 16695)  # spec
mem_get_observation(id: 16696)  # design
mem_get_observation(id: 16697)  # tasks
mem_get_observation(id: 16698)  # adopt-02-expiry apply-progress
mem_get_observation(id: 16699)  # correct-preadoption apply-progress
```

**Risk:** Low. Memory updates only; no source files.

**Review lens:** `code-review-expert`

---

## Dependency Order

| # | Task | Depends on | Reason |
|---|---|---|---|
| 1 | Discovery docs (state-machines + data-model) | — | Foundation; all other tasks cite this correction |
| 2 | Feature-04 docs | 1 | References the same legacy evidence correction |
| 3 | Roadmap + README | 1 | Removes ADOPT-02 references; needs discovery correction as justification |
| 4 | Features showcase HTML | 1 | Removes Vencido state; same lifecycle model as state-machines |
| 5 | OpenSpec artifacts (CANCELLATION.md + proposal banner) | 1–4 | Must cite the exact corrections made in tasks 1–4 |
| 7 | Engram observations + external-work stub | 1–5 (NOT Task 6) | Engram is a non-blocking reconciliation record. The 5 cancellation observations and the apply-progress observation were saved in the same apply pass as Tasks 1–5; Task 7 is not gated on the GitHub issue comment (Task 6). |
| 6 | GitHub issue #48 comment | 5 + PR URL | Orchestrator side-effect after PR opens. Body file is ready; the comment is idempotent via a stable HTML marker. |

**First task to apply:** Task 1 (discovery docs — largest blast radius).
**Last task to apply:** Task 7 (Engram + external-work stub).

---

## Commit Strategy

**Originally forecast as a single PR.** The reconciliation audit found the raw diff exceeds the
400-line budget. Mandatory review must first decide whether to remove line-ending noise and/or
separate planning artifacts; this pass does not rewrite the existing commits. The target remains
`main` under the pre-MVP policy (AGENTS.md §15).

Commits (in apply order):
1. `docs(discovery): correct pre-adoption lifecycle — remove invented Vencido state`
2. `docs(discovery): correct pre-adoption contract clause — 20-day → one-month post-sterilization`
3. `docs(roadmap): cancel ADOPT-02 from roadmap — invalid legacy provenance`
4. `docs(showcase): remove Vencido state and 20-day pre-adoption claims from contract lifecycle`
5. `docs(correct-preadoption): add cancellation record and proposal banner` ← judgment-day required
6. `docs(correct-preadoption): post cancellation comment to GitHub issue #48` ← judgment-day required
7. `docs(correct-preadoption): update Engram observations — ADOPT-02 cancelled`

No chained PRs needed. All commits are docs-only; they can merge in any order (though the
dependency order above is the recommended sequence).

---

## Out-of-Scope Tasks (recorded for follow-up)

- **APAP_ACTUAL docs correction** — Separate repository PR required. Do NOT edit
  `C:/00repos/codigo/APAP_ACTUAL/docs/` in this change. Equivalent false references in:
  - `APAP_ACTUAL/docs/` (state machine, contract types, data model)
  - `APAP_ACTUAL/src/classes/Plantilla.cls` (comment above `RellenarContratoAcogida` if it asserts pre-adoption expiry)
  - `APAP_ACTUAL/src/classes/Adopcion.cls` (comment for `AnimalConAdopcionesActivas` if it suggests automatic expiry)
  Note: `Funciones Generales.bas` requires no corrections (grep found no false claims).
- **Optional CI grep test** — Design §7 risk mitigation: add a CI job that fails on
  `rg 'Vencido|expiración pre-adopción' docs/` returning non-zero. Not included in this slice;
  record as out-of-scope follow-up.
- **Archive cleanup of `openspec/changes/adopt-02-expiry/` deletion candidates** — The audit
  surfaced `openspec/changes/archive/2026-07-05-adopt-02-expiry/` as a potential cleanup
  candidate, but this artifact does NOT exist on `origin/main` (`071aaeb`); it lives on
  `feat/adopt-02-expiry` at `40ce83f`. No archive cleanup is in scope. The forensic branch
  and stash are retained per design §4.

---

## Definition of Done — whole change

- [x] All 7 tasks applied; 7 commits on `docs/correct-preadoption-legacy-provenance`; corrective closeout commit added on top (see `apply-progress.md` for the merged evidence).
- [ ] Single PR opened against `main`; PR body cites `correct-preadoption-legacy-provenance/design.md` and this `tasks.md`. **Budget disposition: BLOCKED on user disposition** (semantic diff > 400 lines; no user-approved `size:exception` found in Engram). See `apply-progress.md` "Risks and deviations" #3.
- [x] All ripgrep acceptance commands in design.md §5 return expected counts (see `apply-progress.md` "Work Unit Evidence" for the corrected closeout scenarios):
      - `rg -i '\bVencido\b' docs/` → 0 in normative scope
      - `rg -i '20 días|20 days' docs/` → 1 match, the `docs/roadmap.md` CANCELLED row (non-operative)
      - `rg -i 'expiración|expirar|expira' docs/` → 1 match, the same CANCELLED row
      - `rg -i 'pre-adoption expiry|pre-adopción expira' docs/` → 0
      - `rg -i '\b(cron|worker|timer|scheduled job)\b' docs/` → only unrelated hits
      - `rg -i 'notificación de venc' docs/` → 0
      - `rg -i '\bVencido\b|vencido' docs/features-showcase.html` → 0
      - `rg -i 'pre.?adop|preadop' docs/features-showcase.html` → only corrected text (the 2 corrected rows in L537 and L605)
- [x] `python -m pytest tests/test_adopciones.py tests/test_adopciones_routes.py tests/test_domain.py::test_adopciones_create_table_sql_columns -v` is green (66 passed in 1.01s; no tests touched)
- [x] `ruff check .` is green (exit 0)
- [ ] `gh issue comment 48 --body-file openspec/changes/correct-preadoption-legacy-provenance/.comment-for-issue-48.md` posted (idempotent via stable HTML marker `<!-- cancellation-marker:adopt-02 -->`). PENDING PR URL.
- [x] Engram observations updated for all 5 `sdd/adopt-02-expiry/*` topic keys (cancellation note + link to this change). Engram IDs: #16694 (proposal), #16695 (spec), #16696 (design), #16697 (tasks), #16698 (adopt-02-expiry apply-progress), #16699 (correct-preadoption apply-progress), #16706 (session summary), #16712 (resume point).
- [x] External-work follow-up issue draft recorded in Engram #16699 (ready to be opened against `APAP_ACTUAL` later)
- [x] No `stash@{0}` popped. No cherry-pick of invalid local-main commits (`2ea1765`, `be43c14`, `40ce83f`). No `APAP_ACTUAL` edits.
- [ ] `code-review-expert` review completed on the corrected branch (orchestrator post-merge)
- [ ] `judgment-day` review completed on Tasks 5 and 6 (and the corrective closeout) before PR merge
