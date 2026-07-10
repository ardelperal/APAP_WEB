# Tasks: Correct Pre-Adoption Legacy Provenance

## Summary

7 tasks. All are docs-only corrections to remove the false claim that pre-adoptions expire
automatically after 20 days (a foster-care clause at `Plantilla.cls` L381-391 misattributed to
pre-adoption). One PR from `docs/correct-preadoption-legacy-provenance` → `main`. Estimated
total changed lines: ~130. No product code, no migrations, no tests touched. ADOPT-01 invariants
in `tests/test_adopciones*` and `tests/test_domain.py` are explicitly out of scope and untouched.

---

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Total estimated changed lines | ~130 (docs: ~8 files × avg 5 lines changed = ~40 del/add; CANCELLATION.md new ~120 lines) |
| 400-line budget risk | **Low** — all edits are 1-5 line surgical changes; new file is a single template |
| Chained PRs recommended | **No** — single PR fits well under budget |
| Suggested split | Single PR, one branch |
| Delivery strategy | `single-pr` (pre-MVP §15, diff < 400 lines) |
| Chain strategy | `stacked-to-main` |

**Decision needed before apply:** No. Diff is well under 400 lines; `single-pr` is the correct
strategy. No exception needed.

```
Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
400-line budget risk: Low
```

---

## Task Inventory

### Task 1: `docs(discovery): correct pre-adoption lifecycle — remove invented Vencido state`

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

**Files:** None (gh issue comment only)

**Edits:**
- Post the cancellation comment template (design.md §4.3) to GitHub issue #48 via:
  `gh issue comment 48 --body-file <(cat <<'EOF'
  Issue #48 cancelled for invalid legacy provenance.
  [... full template from design.md §4.3 ...]
  EOF
  )`
  (The apply phase constructs the exact body from the §4.3 template.)

**Commit:** `docs(correct-preadoption): post cancellation comment to GitHub issue #48`

**Verification:**
```bash
gh issue view 48 --json comments --jq '.comments[-1].body'
# Expected: body contains "cancelled for invalid legacy provenance" and "correct-preadoption-legacy-provenance"
```

**Risk:** Medium. Touches GitHub issue traceability (AGENTS.md §17.2 high-stakes mapping: issue comment on #48).

**Review lens:** `code-review-expert` + `judgment-day` (AGENTS.md §17.2: issue traceability)

---

### Task 7: `docs(correct-preadoption): update Engram observations — ADOPT-02 cancelled; record external-work stub`

**Files:** Engram only (no source files edited)

**Edits — mem_save for each topic_key:**

| topic_key | type | content |
|---|---|---|
| `sdd/adopt-02-expiry/proposal` | `decision` | `superseded by correct-preadoption-legacy-provenance; provenance invalid (20-day foster ≠ pre-adoption expiry). Legacy: Plantilla.cls RellenarContratoAcogida L381-391.` |
| `sdd/adopt-02-expiry/spec` | `decision` | `superseded; no automatic pre-adoption expiry in legacy. Activity is FDevolucion IS NULL (Adopcion.cls L2047-2054).` |
| `sdd/adopt-02-expiry/design` | `architecture` | `superseded by correct-preadoption-legacy-provenance; no timer, no worker, no scheduled job required.` |
| `sdd/adopt-02-expiry/tasks` | `decision` | `cancelled without execution; tasks.md never produced.` |
| `sdd/adopt-02-expiry/apply-progress` | `discovery` | `audit found invalid work in commits 2ea1765/be43c14/40ce83f + stash@{0}; not on origin/main (071aaeb); cancellation in CANCELLATION.md.` |

**Also record external-work follow-up draft (in tasks.md §6, not as a file commit):**
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

**Verification:**
```bash
# After mem_save calls, verify each observation:
gh run list --workflow=... # N/A for Engram — verify via mem_get_observation on each ID returned
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
| 6 | GitHub issue #48 comment | 5 | Must reference the CANCELLATION.md artifact |
| 7 | Engram observations + external-work stub | 6 | Last; closes all traceability loops |

**First task to apply:** Task 1 (discovery docs — largest blast radius).
**Last task to apply:** Task 7 (Engram + external-work stub).

---

## Commit Strategy

**Single PR.** Diff is ~130 lines (well under 400-line budget). All 7 tasks land in one PR
from `docs/correct-preadoption-legacy-provenance` → `main`. Pre-MVP single-branch policy
(AGENTS.md §15) applies.

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

- [ ] All 7 tasks applied, each commit pushed to `docs/correct-preadoption-legacy-provenance`
- [ ] Single PR opened against `main`; PR body cites `correct-preadoption-legacy-provenance/design.md`
      and this `tasks.md`
- [ ] All ripgrep acceptance commands in design.md §5 return expected counts:
      - `rg -i '\bVencido\b' docs/` → 0 in normative scope
      - `rg -i '20 días|20 days' docs/` → 0 in normative scope
      - `rg -i 'expiración|expirar|expira' docs/` → 0 in normative scope
      - `rg -i 'pre-adoption expiry|pre-adopción expira' docs/` → 0
      - `rg -i '\b(cron|worker|timer|scheduled job)\b' docs/` → only unrelated hits
      - `rg -i 'notificación de venc' docs/` → 0
      - `rg -i '\bVencido\b|vencido' docs/features-showcase.html` → 0
      - `rg -i 'pre.?adop|preadop' docs/features-showcase.html` → only corrected text
- [ ] `python -m pytest tests/test_adopciones.py tests/test_adopciones_routes.py tests/test_domain.py::test_adopciones_create_table_sql_columns -v` is green (no tests touched; assert 0 changed)
- [ ] `ruff check .` is green
- [ ] `gh issue comment 48 --body "Issue #48 cancelled for invalid legacy provenance..."` posted with link to PR (template per design.md §4.3)
- [ ] Engram observations updated for all 5 `sdd/adopt-02-expiry/*` topic keys (cancellation note + link to this change)
- [ ] External-work follow-up issue draft recorded in §6 (ready to be opened against `APAP_ACTUAL` later)
- [ ] No `stash@{0}` popped. No cherry-pick of invalid local-main commits (`2ea1765`, `be43c14`, `40ce83f`). No `APAP_ACTUAL` edits.
- [ ] `judgment-day` review completed on Tasks 5 and 6 before PR merge
