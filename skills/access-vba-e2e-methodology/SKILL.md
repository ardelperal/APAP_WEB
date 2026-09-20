---
name: access-vba-e2e-methodology
description: Trigger: Access VBA forms, helpers, UAT, TDD VBA bridge. Forms finos + helpers desacoplados y testeables; átomos TDD espejo de escenarios UAT. Coordina access-vba-tdd-fundamentos + feature-acceptance-uat.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 1.4
  last_verified: 2026-09-16
  scope: ['vba', 'runtime']
  auto_invoke: ['writing e2e tests for Access VBA']
  tiers: ['vba', 'runtime']
---

# Access/VBA E2E Testing Bridge — TDD ⇄ UAT

> **Dysflow tool references.** This skill uses Dysflow tools (test runner `test_vba`, import `import_modules`, etc.) for the TDD loop. Tool names, flag shapes, error codes, and invocation patterns are maintained by `dysflow-usage` — that skill is the canonical source of truth. If a tool is renamed or its signature changes there, this skill's references should be re-aligned in the same change. Inline references below intentionally keep tool names visible for readability; do not duplicate flag shapes, error codes, or argument schemas here — see `dysflow-usage` for those.

## Activation Contract

Apply on any Microsoft Access / VBA project (Dysflow runtime, Form → ViewModel → Servicio → Repositorio) when the same business feature needs BOTH an automated TDD layer and a manual UAT validation. The goal: when TDD atoms are green, the UAT in the quality team's hands **must not find a defect that blocks the workflow**.

This is a bridge between two skills: **`access-vba-tdd-fundamentos`** (TDD) and **`feature-acceptance-uat`** (UAT). It enforces one architecture so both layers are possible: **forms thin, helpers decoupled and testable, TDD atoms mirror UAT scenarios.**

## The Essence (read first)

1. **Forms are thin UI wiring.** A form event handler does exactly: read controls → call a helper → render the result. Nothing else.
2. **All testable logic lives in decoupled helpers** with an honest signature. The decoupling test: *"would removing `db` change what the helper returns?"* If yes, `db` is a required injected dependency. If the output is a pure function of the other parameters, omit `db` — a `db` nothing reads is a smell, not a precaution.
3. **Every TDD atom mirrors a user scenario**, so a quality user could re-run the same input/expected from the UAT card. When in doubt, start from the UAT scenario and back-derive the atom.

See `assets/e2e-canonical-example.md` for the one worked example (fat handler → thin form + helper + atom + UAT card). Copy that shape.

## Hard Rules

HR-1. **No business logic in event handlers.** Any rule, SQL, decision, validation, refresh algorithm, or report logic in `CmdSave_Click`/`AfterUpdate`/etc. is untestable debt; extract it to a helper BEFORE the feature is done.
HR-2. **Honest helper signatures.** Inject the collaborator the helper actually needs — and only that. DB-touching helpers accept `Optional ByRef db As DAO.Database = Nothing` (atoms inject the sandbox via `TestHelper.GetTestDb()`); pure helpers omit it. For business logic, prefer injecting a **repository interface** (`IRepositorioX`) over raw `DAO.Database`, so the helper is tested with an in-memory fake. Apply the decoupling test above.
HR-3. **A form `.cls` MUST NOT call another form's `.cls`.** No `Form_FormX.MetodoY()`, no `Forms("X").Controls(...)`, no `Me.ParentForm.X`. Form-to-form goes through a helper/service or events. If you can't unit-test the interaction without opening two forms in COM, it's wrong.
HR-4. **Public business methods in a form are an anti-pattern.** A `Public Sub`/`Function` in `Form_FormX.cls` is allowed only for event wiring, lifecycle hooks, or tiny UI adapters. If another form needs `Form_FormX.SomeMethod`, that behavior belongs in a helper.
HR-5. **Public names MUST be globally unique** — use a per-module prefix (`<ModuleName>_<FunctionName>`). Run the collision audit before declaring any `Public` export. See `references/helper-naming.md`.
HR-6. **Create shared utilities FIRST** when extracting more than one helper: `modFormInteractionHelper.bas` (form/control access) and `modTestingCoreHelper.bas` (test infra: `BuildOk`/`BuildFail`/`RaiseError`/`InitLogs`). No `Test_*.bas` redefines these locally. See the canonical example.
HR-7. **No `MsgBox`/`InputBox` in helpers under test.** Helpers receive `Optional ByRef p_PromptResult` (Long or String) so atoms assert the message without a real modal blocking COM; the form renders the result.
HR-8. **Run the preflight audit before writing ANY code.** Verify schema, entity properties, form controls, and method signatures against the live source/binary — no assumptions. Hard gate: see `references/preflight-audit.md`.
HR-9. **TDD ⇄ UAT contract.** Every UAT case has a `ref` (commit hash + atom name) to a green TDD atom; every user-observable atom has a UAT scenario. No jargon (`BR-x`, `Form_FormX`, atom names) in the user card body — it goes in the `ref` inside the signed record.
HR-10. **100% TDD green is a hard gate before UAT** goes to the quality team. UAT on a red suite tests blind.
HR-11. **Gemelo invariant** (CONDOR-style): helpers shared across PC / CDCA / CDCASUB / PCSUB must stay aligned. Audit all 4 before changing, or split into a separate SDD.
HR-12. **Balanced test pyramid via interface seams.** VBA supports `Implements`. Test business logic with an in-memory fake implementing the same interface (fast, no sandbox); reserve sandbox E2E for the data layer (repositorios). Never fake to skip a real integration test. Pattern + mandatory adoption spike: `access-vba-tdd-fundamentos` `assets/interface-seams.md`.
HR-13. **Tier forms deliberately — not every form earns the full refactor.** Classify each form by blast radius, churn, rule complexity, and gemelo sharing. Tier 1 = full treatment; Tier 2 = logic-only extraction; Tier 3 = leave as-is. Tier 3 is **documented debt in the cap-doc §7 confidence ledger (`Verified-static`), never a silent skip**. See `references/form-tiering.md`.

## Compile / test discipline

| Change scope | Who compiles | Then |
|---|---|---|
| **Module-only** (`.bas`: helpers, tests, services) | **Humano** compila en Access (Debug → Compile) | Agente corre el runner de tests (current: `test_vba`, per `dysflow-usage`) después del compile humano |
| **Touches forms** (`.cls` behavior, `.form.txt`) | **User**, manually (Debug → Compile) | Agent waits for "OK", then corre el runner de tests (per `dysflow-usage`) |

- Nunca correr el test runner contra un binario no compilado. Para los nombres actuales de tools Dysflow y el contrato de compile humano, ver `dysflow-usage` skill.
- Import and compile one `.bas` at a time, not in batches.
- On a compile error, do not guess — follow the compile-error protocol in `references/helper-naming.md`.

## Decision Gates

| Situation | Action |
|---|---|
| Logic in event handler | Extract to `mod<Feature>Helper.bas` FIRST, then atoms |
| Workflow step uncovered | Add a TDD atom (not just a UAT case) |
| UAT scenario with no atom | Add the atom first; reference it from `ref` |
| Defect found in UAT | Fix helper + add regression atom + update UAT card `ref` |
| Gemelo helper change | Audit all 4 gemelos before merge; align in one slice or split SDD |
| Untestable logic (coupling) | Document debt in cap-doc §7 confidence ledger (`Verified-static`); do NOT accept feature as done |
| UAT case too narrow/broad | Re-scope to one user-actionable rule per card |
| Form in scope (new or legacy) | Tier it first (`references/form-tiering.md`); only Tier 1 gets the full treatment, Tier 3 is documented debt |
| Helper needs data only to read a collaborator | Inject a repository interface + test with an in-memory fake; reserve the sandbox for the repo's own E2E test |

Full table: `assets/decision-gates.md`.

## Execution Steps

1. **Onboard** (new project): read `AGENTS.md` + pre-flight A/B/C — `references/onboarding-playbook.md`.
2. **Map the workflow** using `DatosXxxServicio.cls` as source of truth; method names = atom name anchors.
3. **Preflight audit** + duplicate-name audit (`references/preflight-audit.md`, `references/helper-naming.md`).
4. **Create shared utilities** (`modFormInteractionHelper`, `modTestingCoreHelper`); import + compile each.
5. **Extract helpers, red-first**: atom red against current behavior → extract → atom green. One helper at a time; compile between each.
6. **Write UAT-oriented atoms**: schema-first fixture, concrete user-actionable inputs, cardinalidad before/after, adversarial scenarios (`access-vba-tdd-fundamentos` §1.2/§1.3/§4.5).
7. **Build UAT scenarios** per `feature-acceptance-uat`: DADO/CUANDO/ENTONCES, one card per user-visible rule, `pasos` click-by-click, `esperado` user-visible, `ref` = commit + atom.
8. **Verify all green** via el tool de tests con `testsPath` apuntando al manifest del área (per `dysflow-usage`). 100% green before UAT.
9. **Generate webs** via `feature-acceptance-uat`: `usuario` cases → user web (`docs/uat/uat-staging-<date>.html`); `desarrollo` cases → signed developer web (`docs/uat/uat-dev-<date>.html`). Both self-contained, Telefónica-branded.

Full detail: `assets/workflow.md`.

## Output Contract

Return an object with the following keys:

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Outcome of the E2E bridge pass. |
| `form_audit` | object[] | Forms with inline logic, each with `{form, inline_logic_summary, target_helpers[]}`. |
| `helpers_extracted` | string[] | Helper modules created in `mod<Feature>Helper.bas` style. |
| `tdd_atoms` | object[] | Atoms with `{name, scenario_class: "happy"\|"sad"\|"edge"\|"adversarial", file}`. |
| `uat_scenarios` | object[] | UAT cards with `{title, card_body: dado_cuando_entonces, pasos, ref}`. |
| `verification` | object | `{total, passed, failed, dysflow_import_response}` from `test_vba` (per `dysflow-usage`). |
| `uat_web_paths` | object | `{user_web, developer_web?}` — paths to the signed acceptance webs. |
| `traceability_rows` | object[] | Rows per `assets/tdd-uat-traceability-template.md`. |
| `open_questions` | string[] | Open questions and gemelo-alignment risks. |
| `evidence` | object | `{files: string[], diff_stat: string, test_count: number}` attached to every done claim. |
| `next_recommended` | `"commit" \| "uat" \| "fix_helpers" \| "none"` | Next phase. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| Business logic in `CmdSave_Click` / `AfterUpdate` | Extract to `mod<Feature>Helper.bas` before marking the feature done (HR-1). |
| `Public Sub/Function` in `Form_FormX.cls` consumed by another form | Move the behavior into a helper; form-to-form must go through a service or event (HR-4). |
| UAT card published without a green TDD atom referenced in `ref` | Add the atom first; then reference commit + atom name in the `ref` (HR-9). |
| Feature accepted with a red TDD suite | Fix the suite to green; UAT on a red suite tests blind (HR-10). |

## References

- `dysflow-usage` — canonical source for current Dysflow tool names, flag shapes, error codes, and invocation patterns.
- `dysflow-arnes` — operating harness for Dysflow; bootstrap, schema, capabilities.
- `references/preflight-audit.md` — mandatory 4-step audit before any code.
- `references/helper-naming.md` — naming, collision audit, compile-error protocol.
- `references/onboarding-playbook.md` — new-project onboarding + pre-flight A/B/C.
- `references/agent-anti-patterns.md` — agent's own anti-patterns + compile/test discipline.
- `references/communication-script.md` — scripted messages with the user.
- `references/subagent-failure-modes.md` — delegation failure modes.
- `references/form-tiering.md` — which forms earn the full refactor vs documented debt.
- `assets/e2e-canonical-example.md` — the one worked example.
- `assets/workflow.md`, `assets/decision-gates.md`, `assets/anti-patterns.md`, `assets/tdd-uat-traceability-template.md`.
- `access-vba-tdd-fundamentos` skill — schema-first, sandbox-safe, JSON contract, cardinalidad, `assets/interface-seams.md` (fakes vía `Implements`).
- `feature-acceptance-uat` skill — DADO/CUANDO/ENTONCES, `pasos`, audience split, signed webs.
- Project `AGENTS.md` — gemelos invariant, `getdb()` discipline, Dysflow tooling.
