---
name: access-vba-capability-docs
description: Trigger: Access/VBA capability docs, business rules, what the app does, regression-proof specs, legacy→web migration, generate SDDs from docs. Reverse-engineers features into SDD-grade, migration-ready docs with code as source of truth.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 3.1
  last_verified: 2026-09-16
  scope: ['vba', 'runtime']
  auto_invoke: ['writing capability docs for Access VBA']
  tiers: ['vba', 'runtime']
---

# Access/VBA Capability Documentation

> **Dysflow tool references.** This skill uses Dysflow tools for source↔binary verification (`import_modules`, `verify_code`, `test_vba`, etc.). Tool names, flag shapes, error codes, and invocation patterns are maintained by `dysflow-usage` — that skill is the canonical source of truth. If a tool is renamed or its signature changes there, this skill's references should be re-aligned in the same change. Inline references below intentionally keep tool names visible for readability; do not duplicate flag shapes, error codes, or argument schemas here — see `dysflow-usage` for those.
>
> **This is the VBA-specific instance.** For the stack-agnostic version of this pattern (any project, not just Access/VBA), see `capability-docs` skill. The fork exists because the generic core (capability docs as source-of-truth, SDD harvesting, confidence ledger, migration-ready, dependency map) is reusable across projects; this skill carries the VBA-specific anchors (Dysflow as the only verification path, Access/VBA templates, `access-vba-tdd-fundamentos` for tests).

## Activation

Use this skill to document Microsoft Access/VBA features so any AI can understand and reproduce them **without reading code** — for regression recovery, AI pre-code context, release traceability, and **legacy→web migration**. Trigger on: "document all features", "business rules", "what the app does", "make it reproducible", "regression-proof", "migrate to web", "release traceability".

**This is the documentation baseline for every Access/VBA project.** Each feature gets a capability doc, and the doc has two jobs at once: (1) be a regression-proof contract against the live binary, and (2) be a **migration-ready, platform-agnostic spec** complete enough that an AI can read it and generate the SDDs (proposal → spec → design → tasks) to rebuild the feature on a web stack — without ever reopening the Access code. The §6 migration spec and §8 SDD seed are what make the second job possible; treat them as deliverables, not notes.

## Hard Rules

- **HR-1** — Write all produced documentation in Spanish (Spain / castellano de España). This covers capability docs, index entries, and every filled template — the deliverables. Code identifiers, test names, and Dysflow tool references stay as they are in the code.
- **HR-2** — Code is the source of truth for behavior and implementation. SDD artifacts and the product owner are the source of truth for *intent* only. Verify every behavioral fact against code + Dysflow before marking it `Verified`.
- **HR-3** — Gate 0 first: before retro-documenting, check for existing SDD artifacts (engram `sdd/*`, `openspec/`). Harvest them; do not reinvent. Reverse-engineer only the gaps.
- **HR-4** — Surface SDD↔code divergence as a finding (`Divergent`), never paper over it. That gap is the "done well or not" signal.
- **HR-5** — Document business capabilities first, not modules or technical slices.
- **HR-6** — Use the Dysflow MCP as the only canonical path for source↔binary operations and verification: `import_modules`, `verify_code`, `test_vba` (current names per `dysflow-usage`). Never reference other sync/form skills. For current tool names, flags, and error codes, see `dysflow-usage` skill.
- **HR-7** — Fill one doc per capability against `assets/capability-doc-template.md`, at its `tier` (critical | standard | minimal).
- **HR-8** — Every feature and business rule — old or new, legacy or fresh — MUST carry a test proving it works. If a rule has no test, author one following the `access-vba-tdd-fundamentos` skill (which runs the canonical test runner `test_vba` per `dysflow-usage`) before claiming it works. No rule stays unproven; `Verified-static` is a debt to close, not a finish line. Reconciliation with form tiering: when `access-vba-e2e-methodology` deliberately leaves a low-value form untested (Tier 3), that decision is recorded here as `Verified-static` in §7 with its rationale — the sanctioned, documented exception, never a silent gap.
- **HR-9** — Never claim `passing` or regression closure without Dysflow test evidence (per `dysflow-usage`) and release/UAT traceability.
- **HR-10** — Mark every fact in the confidence ledger: `Verified-runtime` (passing test) / `Verified-static` (read in code, no test yet — transient, owes a test) / `Intended` / `Likely` / `Divergent`, with evidence and date.
- **HR-11** — Record a tracker reference when known (GH issue / PR), tracker-agnostic and optional. The tracker is intent/history, never a source of truth — code still rules.
- **HR-12** — Migration-ready by default. Capture the data model (§3) in platform-agnostic domain terms for every capability. When web migration is a stated goal — or for any `critical` capability — the migration spec (§6) and SDD seed (§8) are required deliverables, not optional notes. A capability whose §6/§8 still force a reader back into the Access code is not done.
- **HR-13** — The doc MUST be SDD-generative. §8 is the bridge: it maps each doc section to a layer of a future SDD so an AI can raise proposal→spec→design→tasks for the web port straight from the doc. The §2 behavioral contract is platform-agnostic on purpose — it doubles as the acceptance spec the rebuilt web version must pass.

## Decision Gates

| Question | Action |
|---|---|
| Existing SDD artifacts for this feature? | Harvest intent, then verify behavior against code. Mark `source: sdd`. |
| Legacy / no SDD? | Reverse-engineer from code; verify via Dysflow (per `dysflow-usage`). Mark `source: reverse-engineered`. |
| SDD says X but code does Y? | Mark `Divergent`, flag for human review. |
| Business rule has no test? | Author one via `access-vba-tdd-fundamentos` (test runner `test_vba` per `dysflow-usage`) until it reaches `Verified-runtime`. |
| Is this user-visible behavior? | Create/update a capability doc. |
| Is this implementation/test/cache support? | Link it as supporting feature evidence. |
| Goal is web migration? | Fill §3 data model + §6 migration spec + §8 SDD seed in full. The doc must let an AI generate the port's SDD without the code. |
| Logic lives in a form event / VBA UI? | Record it in §6 "lógica a extraer" with its platform-agnostic destination (service/use-case). UI-coupled logic is the migration's main risk. |
| Capability shares data/flows with another? | Record the dependency in §8 and the index dependency map — it drives migration ordering. |

## Execution Steps

1. **Gate 0** — discover existing SDD (`sdd/*` in engram, `openspec/`). Harvest proposal→spec→design→tasks into the matching template layers.
2. **Establish truth** — read the real code (forms, controls/events, modules/classes, queries, reports) as source of truth; confirm behavior via the Dysflow verification tools (test runner `test_vba` and drift/verify `verify_code`, per `dysflow-usage`).
3. Build a capability taxonomy by business domain (lifecycle, actions, tasks, documents, reports, notifications, indicators, configuration, security).
4. For each capability, fill `assets/capability-doc-template.md` at its `tier`. The behavioral contract (§2) is the regression anchor; the reconstruction recipe (§4) is the rebuild path.
5. For every §2 business rule lacking a passing test, author one per `access-vba-tdd-fundamentos` (test runner `test_vba` per `dysflow-usage`) so it reaches `Verified-runtime`. Record SDD↔code divergences as findings; set confidence per fact with date + evidence.
6. **Make it migration-ready** — fill §3 data model in domain terms; for web-migration goals and `critical` capabilities, complete §6 (migration spec: logic to extract, agnostic functional contract, UI/UX intent, integrations, data mapping, non-functional needs) and §8 (SDD seed mapping each section to a proposal/spec/design/tasks layer). Verify a reader could raise the port's SDD from the doc alone.
7. Keep two layers — `docs/capabilities/` and `docs/features/` — and maintain `capabilities-index.md` (see template), including the capability **dependency/data map**, so an agent can navigate index → capability → feature → tests → release/UAT and plan migration order.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `capability_docs` | array<object> | Capability docs created/updated, each with `tier` (critical \| standard \| minimal) and `source` (sdd \| reverse-engineered \| hybrid). |
| `divergences` | array<object> | SDD↔code divergences found, each flagged for human review. |
| `verification_evidence` | object | Dysflow verification evidence (test runner `test_vba` and drift/verify `verify_code`, per `dysflow-usage`) plus the list of facts still `Intended`/`Likely`. |
| `traceability` | object | Release/UAT or regression traceability added per capability. |
| `migration_readiness` | object | For web-migration goals / `critical` capabilities: §3 data model, §6 migration spec, and §8 SDD seed completion status — the doc MUST seed the port's SDD without the code. |
| `evidence_gaps` | array<object> | Open gaps left pending, each with the exact next action to close it. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| Re-documenting an existing SDD artifact instead of harvesting it. | Run Gate 0 first (`sdd/*` in engram, `openspec/`); harvest proposal → spec → design → tasks, then verify behavior against code. |
| Marking a fact `Verified-runtime` without `test_vba` evidence. | Every `Verified-runtime` row needs a passing test id + date (per `dysflow-usage`); otherwise downgrade to `Verified-static` and author the test via `access-vba-tdd-fundamentos`. |
| Writing a `critical` capability without §6 migration spec and §8 SDD seed. | §3 data model + §6 migration spec + §8 SDD seed are required deliverables for `critical` and web-migration goals. |
| Coupling §3 data model to Access-specific terminology. | §3 is platform-agnostic on purpose; it doubles as the acceptance spec for the web port. |
| Silently leaving a `Verified-static` fact in §7. | `Verified-static` is transient debt; author the test before closing the doc or record the rationale in the ledger. |

## References

- `capability-docs` skill — stack-agnostic version of this pattern (any project, not just Access/VBA).
- `dysflow-usage` — canonical source for current Dysflow tool names, flag shapes, error codes, and invocation patterns.
- `dysflow-arnes` — operating harness for Dysflow; bootstrap, schema, capabilities.
- `assets/capability-doc-template.md` — SDD-grade, tiered capability doc template to fill, incl. §3 data model, §6 web-migration spec, and §8 SDD seed.
- `assets/capabilities-index-template.md` — master registry of capabilities for navigation.
- `assets/example-capability.md` — a filled example showing every convention.
- `references/reproducibility-model.md` — truth layers, detect-and-reconstruct model, confidence semantics.
- `access-vba-tdd-fundamentos` skill — how to author the tests that move rules to `Verified-runtime`.
- `access-vba-e2e-methodology` skill — thin forms + decoupled helpers + the TDD ⇄ UAT contract; its form-tiering debt and testing debt are recorded in this doc's §7 ledger.
- Project `AGENTS.md` — exact paths, release tags, compile policy, Dysflow config. Follow it first.
