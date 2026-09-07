# Design: Correct Pre-Adoption Legacy Provenance

Change key: `correct-preadoption-legacy-provenance`
Branch: `docs/correct-preadoption-legacy-provenance` (based on `origin/main` @ `071aaeb`).

## 1. Summary

This change cancels the false legacy-parity claim that pre-adoptions expire automatically after 20 days, correcting APAP_WEB discovery, state-machine, data-model, roadmap, README, and feature-showcase documentation with the actual legacy source evidence. The 20-day decision clause belongs to **foster care** (contract template text), not pre-adoption; pre-adoption remains active until definitive adoption or explicit return, governed by `FDevolucion IS NULL`. ADOPT-01 invariants are preserved unchanged. Issue #48 and SDD `adopt-02-expiry` are cancelled with explicit markers; the `feat/adopt-02-expiry` branch, `stash@{0}`, and local-main's three invalid commits are retained for forensic reconstruction but are NOT delivered. Equivalent false references in `APAP_ACTUAL/docs/` are recorded for a separate repository PR.

## 2. Affected Files Inventory

| File path | Kind | Action | Reason |
|---|---|---|---|
| `docs/discovery/state-machines.md` | existing-doc | edit | `Vencido` state (L120) and the `Pendiente de Firma -> Vencido` transition (L129) plus the `Vencido -> terminal` row (L132) mis-attribute a 20-day pre-adoption window that does not exist as executable lifecycle. L111 prose says contracts "follow a lifecycle from draft to signed or expired" — change to "draft to signed (no automatic expiry)". |
| `docs/discovery/data-model-completeness.md` | existing-doc | edit | L273 row `Pre-adoption expiry (20-day window) | Application-only (date calculation) | Service layer + scheduled job` is invented; remove the row. |
| `docs/discovery/feature-04-documents-contracts-reports.md` | existing-doc | edit | L74 rule `Pre-adoption | 20-day decision clause in pre-adoption contracts` is misattributed — the 20-day clause is foster-contract text (Plantilla.cls L381-391). L84 table cell `PreAdopción | Species-specific template | - | 20-day decision clause | -` — change to the pre-adoption contract's one-month post-sterilization signing clause, with a footnote citing the foster source. |
| `docs/roadmap.md` | existing-doc | edit | L16 and L132: `ADOPT-02..03 [#48..#49]` — drop ADOPT-02 from the in-flight list (issue is cancelled). L259 row `#48 | ADOPT-02: expiración ... | Fase 5c | 🔲` — replace with a CANCELLED row pointing to this change. |
| `README.md` | existing-doc | edit | L68 line `ADOPT-02 20-day pre-adoption expiry, ADOPT-03 4-state follow-up state machine (#48, #49)` — drop ADOPT-02/#48 and add a one-line pointer to `openspec/changes/correct-preadoption-legacy-provenance/`. |
| `docs/features-showcase.html` | existing-doc | edit | L537/L605 pre-adoption `Acuerdo con cláusula de 20 días` rows — change to the pre-adoption one-month post-sterilization signing clause. L672 `data-state="vencido"` div — remove. L941 transitions `'pendiente-firma': ['Firmado', 'Vencido', 'Anulado']` — drop `'Vencido'`. L943 `'vencido': ['— Terminal —']` — drop the entry. |
| `docs/architecture/architecture-local_backend-stack.md` | existing-doc | review-only | Grep for `scheduled | cron | worker | Vencido | 20 d` returned 0 matches; nothing to edit. Recorded as reviewed so the verification phase does not re-prove it. |
| `docs/proceso.md`, `docs/architecture/decisiones-proyecto.md` | existing-doc | review-only | Only contain the legacy-fidelity rule; no false claims. |
| `openspec/changes/correct-preadoption-legacy-provenance/CANCELLATION.md` | openspec-artifact | create (apply phase) | Single-file cancellation record: reason, forensic-retention table, ADOPT-01 invariants preserved, external-work follow-up. See §4 for full text. |
| `openspec/changes/correct-preadoption-legacy-provenance/proposal.md` | openspec-artifact | edit header (apply phase) | Add a 4-line banner at the very top pointing at this change and naming the cancelled SDD + branch. See §4 for the banner template. |
| `openspec/changes/adopt-02-expiry/` | openspec-artifact | NOT edited | Lives only on `feat/adopt-02-expiry` (heads `40ce83f`) and on local-main as part of that branch. This change is based on `origin/main` (`071aaeb`) where the directory does NOT exist. Touching it would amount to cherry-picking the cancelled work; do not do it. The cancellation marker lives in our own artifact + Engram + the GitHub issue, not in the cancelled tree. |
| `openspec/changes/archive/` | openspec-artifact | review-only | `2026-07-05-adopt-02-expiry` does NOT exist in archive (the archive commit `40ce83f` lives on the feat branch, not on origin/main). No archive cleanup is in scope. |
| Engram topic `sdd/adopt-02-expiry/proposal` | engram-topic | create (apply phase) | Type `decision`, content: "superseded by `correct-preadoption-legacy-provenance`; provenance invalid (20-day foster ≠ pre-adoption expiry)". |
| Engram topic `sdd/adopt-02-expiry/spec` | engram-topic | create (apply phase) | Type `decision`, content: "superseded; no automatic pre-adoption expiry exists in legacy". |
| Engram topic `sdd/adopt-02-expiry/design` | engram-topic | create (apply phase) | Type `architecture`, content: "superseded by `correct-preadoption-legacy-provenance`". |
| Engram topic `sdd/adopt-02-expiry/tasks` | engram-topic | create (apply phase) | Type `decision`, content: "cancelled without execution". |
| Engram topic `sdd/adopt-02-expiry/apply-progress` | engram-topic | create (apply phase) | Type `discovery`, content: "audit found invalid work in commits `2ea1765`/`be43c14`/`40ce83f` and `stash@{0}`; work excluded from `main`". |
| `C:/00repos/codigo/APAP_ACTUAL/src/classes/Plantilla.cls` | external-evidence | review-only | Lines 381-391 contain the foster-contract 20-day decision clause — quoted in §3. Read-only evidence; no edits. |
| `C:/00repos/codigo/APAP_ACTUAL/src/classes/Adopcion.cls` | external-evidence | review-only | Lines 1991-2054 contain `AnimalConAdopcionesActivas` (pre-adoption activity derived from `FDevolucion IS NULL`) — quoted in §3. Read-only. |
| `C:/00repos/codigo/APAP_ACTUAL/src/modules/Funciones Generales.bas` | external-evidence | review-only | Grep returned no pre-adoption timer/expiry; only unrelated health-test periodicity logic. |
| `C:/00repos/codigo/APAP_ACTUAL/docs/` | external-evidence | follow-up (separate PR) | Equivalent false references; recorded in §8. |
| `stash@{0}` (`adopt-02-invalid-work-2026-07-10`) | git-stash | NOT touched | Forensic retention; do not pop, do not drop. |
| Local `main` ahead by 3 commits (`2ea1765`, `be43c14`, `40ce83f`) | git-local | NOT touched | Out of scope per hard constraints. |

## 3. Search-and-Replace Strategy (exact prose)

**Legacy evidence (verbatim, used as the replacement anchor):**

- `APAP_ACTUAL/src/classes/Plantilla.cls` lines 381-391 (inside `RellenarContratoAcogida`, which begins at L258) substitute into the foster-contract template `[PARRAFO1]`:
  ```
  If strTipoAcogida = "Temporal" Then
      m_ColParaSustituir.Add "[PARRAFO1]", ""
  Else
      strParrafo1 = "La persona que realiza esta acogida temporal dispone del plazo de 20 DÍAS, desde el día de la firma de este contrato, " & _
                      "para decidir si firma un contrato de adopción definitivo o si el animal pasa a considerarse disponible para adopción. " & _
                      "La firma del mencionado contrato de adopción definitivo deberá producirse en las dos semanas siguientes, " & _
                      "a partir de la comunicación de dicha intención de adoptarlo. En caso de producirse la firma, " & _
                      "el animal pasará a estar disponible para su adopción, comprometiéndose el firmante de este contrato a ponerlo en " & _
                      "disposición de la Asociación."
  ```
  The `Else` branch (`strTipoAcogida <> "Temporal"`) is the foster contract (not pre-adoption). The 20 days is the foster caregiver's decision window before they must commit to adoption or release the animal back.

- `APAP_ACTUAL/src/classes/Adopcion.cls` lines 1991-2054 (function `AnimalConAdopcionesActivas`):
  ```
  Public Function AnimalConAdopcionesActivas(strNChip As String, Optional strIDAdopcionAExcluir As String) As String
  ...
  strSQLParaComprobar = "SELECT TbAdopcion.Nchip, TbAdopcion.IDAdopcion " & _
                      "FROM TbAdopcion " & _
                      "WHERE (((TbAdopcion.Nchip)='" & strNChip & "') AND ((TbAdopcion.FDevolucion) Is Null));"
  ```
  Pre-adoption is "active" iff there is a `TbAdopcion` row with `FDevolucion IS NULL`. No timer, no cron, no scheduled job.

**Per-file replacement targets:**

| File | Line | Current prose | Replacement |
|---|---|---|---|
| `docs/discovery/state-machines.md` | 111 | `from draft to signed or expired` | `from draft to signed (no automatic expiry)` |
| `docs/discovery/state-machines.md` | 120 | `\| Vencido \| Contract has expired (e.g., pre-adoption 20-day window lapsed) \|` | REMOVE the row |
| `docs/discovery/state-machines.md` | 129 | `\| Pendiente de Firma \| Vencido \| Signature deadline lapsed (pre-adoption: 20 days) \|` | REMOVE the row |
| `docs/discovery/state-machines.md` | 132 | `\| Vencido \| — \| Terminal; new contract may be generated if needed \|` | REMOVE the row |
| `docs/discovery/state-machines.md` | 143 | `\| PreAdopción \| ... \| 20-day decision window \|` | `\| PreAdopción \| ... \| None (manual close via definitive adoption or return through FDevolucion) \|` |
| `docs/discovery/data-model-completeness.md` | 273 | `\| Pre-adoption expiry (20-day window) \| Application-only (date calculation) \| Service layer + scheduled job \|` | REMOVE the row (and renumber). Footnote: "Pre-adoption has no runtime expiry — activity is `FDevolucion IS NULL` (Adopcion.cls L2047-2054). The 20-day clause is foster-contract text (Plantilla.cls L381-391)." |
| `docs/discovery/feature-04-documents-contracts-reports.md` | 74 | `\| Pre-adoption \| 20-day decision clause in pre-adoption contracts \|` | `\| Pre-adoption \| One-month post-sterilization signing clause (contract text, not runtime) \| — plus footnote: "The 20-day decision clause belongs to foster contracts (Plantilla.cls, RellenarContratoAcogida, L381-391), not pre-adoption."` |
| `docs/discovery/feature-04-documents-contracts-reports.md` | 84 | `\| PreAdopción \| ... \| 20-day decision clause \| — \|` | `\| PreAdopción \| ... \| One-month post-sterilization signing clause \| — \|` |
| `docs/roadmap.md` | 16 | `ADOPT-02..03 🔲 (#48..#49)` | `ADOPT-03 🔲 (#49)` |
| `docs/roadmap.md` | 132 | `ADOPT-02..03 🔲 (#48..#49)` | `ADOPT-03 🔲 (#49)` |
| `docs/roadmap.md` | 259 | `\| #48 \| ADOPT-02: expiración de pre-adopción tras ventana de 20 días \| Fase 5c \| 🔲 \|` | `\| #48 \| ~~ADOPT-02: expiración...~~ **CANCELADO** por provenancia inválida — cláusula de 20 días = foster (`Plantilla.cls` L381-391), no pre-adopción. Ref `correct-preadoption-legacy-provenance`. \| — \| ❌ \|` |
| `README.md` | 68 | `**Adoptions**: ADOPT-02 20-day pre-adoption expiry, ADOPT-03 4-state follow-up state machine (#48, #49).` | `**Adoptions**: ADOPT-03 4-state follow-up state machine (#49). ADOPT-02 (#48) cancelled for invalid legacy provenance — see `openspec/changes/correct-preadoption-legacy-provenance/`.` |
| `docs/features-showcase.html` | 537 | `<td>Acuerdo con cláusula de 20 días</td>` | `<td>Cláusula de firma un mes post-esterilización (texto de contrato)</td>` |
| `docs/features-showcase.html` | 605 | `<td>Cláusula de decisión de 20 días</td>` | `<td>Cláusula de firma un mes post-esterilización (texto de contrato)</td>` |
| `docs/features-showcase.html` | 672 | `<div class="state terminal" data-state="vencido" ...>Vencido</div>` | REMOVE the entire `<div>` block |
| `docs/features-showcase.html` | 941 | `'pendiente-firma': ['Firmado', 'Vencido', 'Anulado']` | `'pendiente-firma': ['Firmado', 'Anulado']` |
| `docs/features-showcase.html` | 943 | `'vencido': ['— Terminal —']` | REMOVE the line |

## 4. Cancellation Markers

### 4.1 Banner to insert at the top of `openspec/changes/correct-preadoption-legacy-provenance/proposal.md`

The proposal already references the cancellation; the apply phase prepends this 4-line banner above the existing `# Proposal:` heading so the cancel reason is the first thing a reader sees:

```markdown
> **CANCELLATION SCOPE (2026-07-10).** This change cancels SDD `adopt-02-expiry` and
> issue #48 for invalid legacy provenance. The 20-day decision clause belongs to foster care
> (`APAP_ACTUAL/src/classes/Plantilla.cls`, `RellenarContratoAcogida`, lines 381-391), NOT to
> pre-adoption expiry. Pre-adoption remains active until definitive adoption or explicit
> return, governed by `FDevolucion IS NULL` (`Adopcion.cls`, `AnimalConAdopcionesActivas`,
> lines 1991-2054). See `CANCELLATION.md` for forensic retention.

```

### 4.2 `openspec/changes/correct-preadoption-legacy-provenance/CANCELLATION.md` (new file, apply phase creates)

```markdown
# Cancellation Notice — SDD `adopt-02-expiry`

**Date:** 2026-07-10
**Cancelling change:** `correct-preadoption-legacy-provenance`
**Reason:** Invalid legacy provenance. The 20-day decision clause belongs to foster care
(`APAP_ACTUAL/src/classes/Plantilla.cls`, `RellenarContratoAcogida`, lines 381-391), NOT to
pre-adoption lifecycle. Pre-adoption remains active until definitive adoption or explicit
return, governed by `FDevolucion IS NULL` (`Adopcion.cls`, `AnimalConAdopcionesActivas`,
lines 1991-2054). No automatic expiry, no timer, no worker, no notification.

## Forensic retention (NOT delivered)

| Artifact | State | Location |
|---|---|---|
| `feat/adopt-02-expiry` branch | KEPT at `40ce83f` (not deleted) | local git |
| `stash@{0}: adopt-02-invalid-work-2026-07-10` | KEPT (not popped, not dropped) | local git stash |
| Local-main 3 invalid commits (`2ea1765`, `be43c14`, `40ce83f`) | KEPT ahead of `origin/main` | local `main`; not cherry-picked into this change |
| `openspec/changes/adopt-02-expiry/` OpenSpec tree | KEPT on `feat/adopt-02-expiry` | not present on `docs/correct-preadoption-legacy-provenance` |
| GitHub issue #48 | Cancelled with provenance reason | `gh issue comment` posted by apply phase |
| Engram (5 topic keys) | `superseded` / `cancellation` notes | apply phase `mem_save` |

## ADOPT-01 invariants preserved (NOT changed by this cancellation)

1. `TipoAdopcion` enum (regular / preadopcion / judicial)
2. Manual contracts and follow-up (no automation)
3. Sterilization commitment and formalization (`donativo_preadopcion` / `donativo_adopcion`)
4. Return through `FDevolucion` only (no state derivation from elapsed time)

## External follow-up (NOT in this change)

`APAP_ACTUAL/docs/` contains equivalent false references and requires a separate repository PR
(see design §8).
```

### 4.3 GitHub issue #48 — comment template (apply phase posts via `gh issue comment 48 --body-file …`)

```markdown
Issue #48 cancelled for invalid legacy provenance.

The 20-day decision clause belongs to foster care
(`APAP_ACTUAL/src/classes/Plantilla.cls`, `RellenarContratoAcogida`, lines 381-391), NOT to
pre-adoption lifecycle. Pre-adoption remains active until definitive adoption or explicit
return, governed by `FDevolucion IS NULL` (`APAP_ACTUAL/src/classes/Adopcion.cls`,
`AnimalConAdopcionesActivas`, lines 1991-2054). No automatic expiry, no timer, no worker,
no notification.

Cancelled by change `correct-preadoption-legacy-provenance` on branch
`docs/correct-preadoption-legacy-provenance`. ADOPT-01 invariants preserved unchanged.

Forensic preservation:
- `feat/adopt-02-expiry` branch kept at `40ce83f` (not deleted)
- `stash@{0}` `adopt-02-invalid-work-2026-07-10` kept (not popped)
- 3 invalid local-main commits (`2ea1765`, `be43c14`, `40ce83f`) kept ahead of `origin/main`
- ADOPT-01 test locks in `tests/test_adopciones.py`, `tests/test_adopciones_routes.py`,
  `tests/test_domain.py::test_adopciones_create_table_sql_columns` untouched

If a real expiry policy is ever needed, it must be a separately approved business change.
```

### 4.4 Engram observations (apply phase `mem_save` for each)

Each uses `topic_key` from the orchestrator's list, `type` as noted, `capture_prompt: false`
(because these are automated artifact notes, per the Engram protocol).

| topic_key | type | content |
|---|---|---|
| `sdd/adopt-02-expiry/proposal` | `decision` | `superseded by correct-preadoption-legacy-provenance; provenance invalid (20-day foster ≠ pre-adoption expiry). Legacy source: APAP_ACTUAL/src/classes/Plantilla.cls RellenarContratoAcogida L381-391.` |
| `sdd/adopt-02-expiry/spec` | `decision` | `superseded; no automatic pre-adoption expiry exists in legacy. Activity is derived from FDevolucion IS NULL (Adopcion.cls L2047-2054).` |
| `sdd/adopt-02-expiry/design` | `architecture` | `superseded by correct-preadoption-legacy-provenance; design not adopted; no timer, no worker, no scheduled job was ever required.` |
| `sdd/adopt-02-expiry/tasks` | `decision` | `cancelled without execution; tasks.md never produced.` |
| `sdd/adopt-02-expiry/apply-progress` | `discovery` | `audit found invalid work in commits 2ea1765/be43c14/40ce83f on feat/adopt-02-expiry + stash@{0}; not present on origin/main (071aaeb); cancellation marker in CANCELLATION.md.` |

## 5. Targeted-Search Acceptance

The verification phase runs the following `rg` commands and confirms the expected counts. All
searches are **case-insensitive** and scoped to normative docs (the cancellation banner
inside `correct-preadoption-legacy-provenance/` is exempt — it is itself a historical
reference). Scope excludes `openspec/changes/archive/` per the spec's scenario 4 ("historical
and cancellation hits pass only when clearly non-normative").

```bash
# Operative automatic-expiry claims — MUST be 0 matches in normative scope
rg -i -n '\bVencido\b' docs/ README.md openspec/changes/correct-preadoption-legacy-provenance/
# Expected: 0 matches (the state-machine Vencido row and the showcase data-state div are removed).

rg -i -n '20 días|20 days' docs/ README.md openspec/changes/correct-preadoption-legacy-provenance/
# Expected: 0 matches in docs/. The foster clause "20 DÍAS" only appears in the verbatim
# quote inside CANCELLATION.md (intentional, non-operative) — accept that as the only hit.

rg -i -n 'expiración|expirar|expira' docs/ README.md openspec/changes/correct-preadoption-legacy-provenance/
# Expected: 0 matches in docs/ (cookie-session "expira" hits in features/autenticacion-y-autorizacion.md
# and audits/* are unrelated to pre-adoption — they refer to the auth cookie TTL).

rg -i -n 'pre-adoption expiry|pre-adopción expira' docs/ README.md openspec/changes/correct-preadoption-legacy-provenance/
# Expected: 0 matches (data-model-completeness.md L273 removed; roadmap L259 cancelled).

rg -i -n '\b(cron|worker|timer|scheduled job)\b' docs/ README.md openspec/changes/correct-preadoption-legacy-provenance/
# Expected: only auth-cache / cookie-rotation / migration-lock worker hits — none
# in docs/discovery/* related to pre-adoption. Confirm by reading context of any hit.

rg -i -n 'notificación de venc' docs/ README.md openspec/changes/correct-preadoption-legacy-provenance/
# Expected: 0 matches.

rg -i -n '\bVencido\b|vencido' docs/features-showcase.html
# Expected: 0 matches (L672 div and L941/L943 transitions removed).

rg -i -n 'pre.?adop|preadop' docs/features-showcase.html
# Expected: hits at L537 and L605 now read "Cláusula de firma un mes post-esterilización (texto de contrato)".
```

Acceptance: each `rg` returns `0 matches` for operative claims, OR returns only the
verbatim historical reference inside `correct-preadoption-legacy-provenance/CANCELLATION.md`.
The verification phase records the actual output of each command in the verify report.

## 6. ADOPT-01 Invariant Lock

Per AGENTS.md §11 (CRITICAL_HELPERS), the apply phase MUST NOT modify these tests; they
already cover the four ADOPT-01 invariants and are the regression barrier for any future
"automatic pre-adoption expiry" claim. Existence verified via `codegraph_explore` over
`tests/test_adopciones*.py` and `tests/test_domain.py`; do NOT re-Read the tests, only
confirm names via the index.

| ADOPT-01 invariant | Lock test (path + identifier) |
|---|---|
| `TipoAdopcion` enum (`regular` / `preadopcion` / `judicial`) | `tests/test_domain.py::test_adopciones_create_table_sql_columns` (pins the column + CHECK constraint `tipo_adopcion IN ('regular','preadopcion','judicial')`) + `tests/test_adopciones.py` parametrized create-path tests |
| Manual contracts + follow-up, no automation | `tests/test_adopciones_routes.py::test_adopciones_routes_require_authorized_user` + `tests/test_adopciones_routes.py::test_adopciones_write_routes_reject_reader_with_403` (writer-gate per #144) |
| Sterilization commitment + formalization (`donativo_preadopcion` numeric) | `tests/test_adopciones.py` parametrized `donativo_preadopcion` validation (incl. line 439 `ValueError, match="donativo_preadopcion"`) |
| Return through `FDevolucion` only (no elapsed-time derivation) | `tests/test_domain.py::test_adopciones_create_table_sql_columns` pins the `fecha_devolucion` column; `tests/test_adopciones.py` update/delete paths treat `fecha_devolucion` as the only closing event |

If any of these tests fail after this change, the change is a regression — STOP and revisit.

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Future merge re-adds an automatic-expiry claim | Medium | Targeted searches (§5) + ADOPT-01 test pin (§6). Optional follow-up: add a CI grep test that fails on `rg 'Vencido|expiración pre-adopción' docs/` returning non-zero. Recorded as out-of-scope for this slice but flagged. |
| Cancellation markers are too aggressive and erase forensic context | Low | The cancellation marker (§4) is text-only on this branch. The cancelled branch `feat/adopt-02-expiry` (heads `40ce83f`) is NOT deleted; `stash@{0}` is NOT popped; the 3 invalid local-main commits are NOT rebased away. |
| Drift between APAP_WEB docs and APAP_ACTUAL docs | Medium | External follow-up recorded in §8; APAP_ACTUAL PR is a separate repository PR with the same correction pattern. |
| `openspec/changes/adopt-02-expiry/` is mistakenly re-created on this branch | Low | Apply-phase instructions explicitly forbid it; the only file we create under `openspec/changes/correct-preadoption-legacy-provenance/` is `proposal.md`, `specs/...`, `design.md`, and `CANCELLATION.md`. |
| Cherry-pick of invalid work into this branch | Low | This branch is based on `origin/main` (`071aaeb`); the invalid commits live on `feat/adopt-02-expiry` (heads `40ce83f`). Apply phase MUST NOT `git merge feat/adopt-02-expiry` or `git cherry-pick 2ea1765/be43c14/40ce83f`. |
| Per-spec scenario "active pre-adoption remains active" not observable from docs alone | Medium | The state-machine correction (§3) makes the lifecycle explicit: no transition from `Pendiente de Firma` to `Vencido`; pre-adoption closure is `Firma -> Anulado` or external return through `FDevolucion`. |

## 8. External Work (separate PR, NOT in this change)

The following live in `C:/00repos/codigo/APAP_ACTUAL/` and require a separate repository PR.
Do NOT edit them in this change.

- `APAP_ACTUAL/docs/` — equivalent false references to the 20-day pre-adoption expiry (state
  machine, contract types, data model). Apply the same corrections as APAP_WEB §3.
- `APAP_ACTUAL/src/classes/Plantilla.cls` — keep lines 381-391 verbatim (they are the
  legacy-truth text); if any comment block above the function asserts pre-adoption expiry,
  correct it to point at foster-care origin.
- `APAP_ACTUAL/src/classes/Adopcion.cls` — keep `AnimalConAdopcionesActivas` lines 1991-2054
  verbatim; correct any surrounding comment that suggests automatic expiry.
- `APAP_ACTUAL/src/modules/Funciones Generales.bas` — no corrections required (grep for
  timer / expiry returned no false claims).
- The `feat/adopt-02-expiry` branch and `stash@{0}` — leave intact for forensic; do not
  delete from APAP_WEB or APAP_ACTUAL.

## 9. Review Lens Selection

Per AGENTS.md §17.2:

- **`code-review-expert`** is **mandatory** for every slice in this change (one PR).
  The orchestrator launches it on the diff `main...docs/correct-preadoption-legacy-provenance`
  after apply lands.

- **`judgment-day`** is **NOT required** for the docs slice itself. The diff does not touch
  auth, secrets, CSRF, session, migration SQL, or fixtures (AGENTS.md §17.2 high-stakes
  triggers). All edits are in `docs/`, `README.md`, and `openspec/changes/correct-preadoption-legacy-provenance/`.

- **`judgment-day` IS required for the cancellation commit itself** because it touches the
  OpenSpec change artifact (`openspec/changes/correct-preadoption-legacy-provenance/`) AND
  GitHub issue #48 traceability. The apply phase MUST call `judgment-day` on the cancellation
  commit (`docs(correct-preadoption): cancel ADOPT-02 and #48 for invalid provenance`) before
  opening the PR; the orchestrator records this requirement here so it does not get lost
  between design and apply.

## 10. Verification Strategy

The verification phase executes the eight `rg` commands in §5 in order and records:

1. The actual output line count for each command.
2. The canonical pass criteria: `0 matches` for operative automatic-expiry claims
   (`Vencido`, `expiración pre-adopción`, `notificación de venc`, `cron/worker/timer/scheduled job`
   tied to pre-adoption), or hits only inside `openspec/changes/correct-preadoption-legacy-provenance/CANCELLATION.md`
   (the verbatim historical reference, treated as non-operative).
3. A short prose verdict per command.

If any command returns operative hits, the verification report flags them as **BLOCKER** and
the apply phase MUST re-open the doc tree to remove them. ADOPT-01 regression is verified by
running `python -m pytest tests/test_adopciones.py tests/test_adopciones_routes.py tests/test_domain.py::test_adopciones_create_table_sql_columns tests/test_domain.py::test_adopciones_create_table_sql_nombre_adoptante_not_null -v`
and confirming 100% green (these tests do not require product code changes; they should
already be passing on `origin/main`).